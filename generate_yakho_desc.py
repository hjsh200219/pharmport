"""
Phase 2-B: LLM 약효설명 Generation

Per-약효설명ID generation pipeline:
  1. 터울약효설명 테이블의 각 약효설명ID에 대해
  2. 연결된 심평원성분코드 목록 조회 (터울주성분.약효설명ID)
  3. edb_mechanism, edb_drug_disease에서 enrichment 데이터 수집
  4. Claude API로 English 약효설명 생성 (2-3 paragraphs)
  5. DeepL API로 영→한 번역
  6. Claude API로 한국어 후처리 (약학 용어 정제)
  7. v2 DB 터울약효설명 테이블에 저장

Usage:
    python generate_yakho_desc.py                            # Generate for all pending
    python generate_yakho_desc.py --yakho-id 123             # Generate for specific ID
    python generate_yakho_desc.py --batch-size 20            # Custom batch size
    python generate_yakho_desc.py --dry-run                  # Show what would be generated
    python generate_yakho_desc.py --skip-translation         # English only
    python generate_yakho_desc.py --regenerate               # Force regenerate existing
    python generate_yakho_desc.py --stats                    # Show generation statistics
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Optional

import anthropic
import httpx

from common import get_connection, get_v2_connection
from enrich_base import ProgressTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

CLAUDE_MODEL = "claude-sonnet-4-20250514"
DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"
MODIFIED_BY = "enrichment_llm"
LLM_VERSION = 1

# Rate limiting: max 10 LLM calls/minute, max 20 DeepL calls/minute
CLAUDE_REQUESTS_PER_MINUTE = 10
CLAUDE_SLEEP_BETWEEN = 60.0 / CLAUDE_REQUESTS_PER_MINUTE  # 6초

DEEPL_REQUESTS_PER_MINUTE = 20
DEEPL_SLEEP_BETWEEN = 60.0 / DEEPL_REQUESTS_PER_MINUTE  # 3초

DEFAULT_BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# Prompt Templates
# ---------------------------------------------------------------------------

YAKHO_PROMPT = """You are a pharmaceutical information specialist writing drug efficacy descriptions.

Drug Class: {yakho_description_context}
Related Ingredients: {ingredient_names}

Existing Description (if any):
{existing_text}

Evidence from enrichment data:
{enrichment_context}

Generate a comprehensive but concise drug efficacy description that:
1. Explains the therapeutic mechanism in clear terms
2. Describes primary therapeutic effects and indications
3. Notes the drug class and related compounds
4. Uses evidence-based language
5. Is suitable for healthcare professionals and informed patients

Output: 2-3 paragraphs in English."""


KOREAN_REFINEMENT_PROMPT = """You are a Korean pharmaceutical terminology specialist. Review and refine this Korean translation.

Original English:
{english_text}

Machine Translation (Korean):
{korean_translation}

Refine the Korean:
1. Use standard Korean pharmaceutical terms (약학 용어)
2. Ensure medical accuracy
3. Maintain professional but accessible tone
4. Fix machine translation artifacts

Output: Refined Korean text only."""


# ---------------------------------------------------------------------------
# Source DB: 약효설명 및 enrichment 데이터 조회
# ---------------------------------------------------------------------------

def fetch_all_yakho_ids(src_conn, regenerate: bool = False) -> list[dict]:
    """처리 대상 약효설명ID 목록을 반환한다.

    Args:
        src_conn: source DB connection
        regenerate: True면 이미 생성된 건도 포함

    Returns:
        [{"약효설명ID": int, "터울버전": str, "EnglishText": str}, ...]
    """
    with src_conn.cursor() as cur:
        cur.execute("""
            SELECT
                "약효설명ID",
                "터울버전",
                "EnglishText"
            FROM "터울약효설명"
            WHERE "IsDeleted" = FALSE
            ORDER BY "약효설명ID"
        """)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_single_yakho(src_conn, yakho_id: int) -> Optional[dict]:
    """단일 약효설명ID 데이터를 반환한다."""
    with src_conn.cursor() as cur:
        cur.execute("""
            SELECT
                "약효설명ID",
                "터울버전",
                "EnglishText"
            FROM "터울약효설명"
            WHERE "약효설명ID" = %s
              AND "IsDeleted" = FALSE
        """, (yakho_id,))
        row = cur.fetchone()
        if row:
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))
    return None


def fetch_linked_ingredients(src_conn, yakho_id: int) -> list[dict]:
    """약효설명ID에 연결된 심평원성분코드 목록을 반환한다."""
    with src_conn.cursor() as cur:
        cur.execute("""
            SELECT
                "심평원성분코드",
                "성분명",
                "성분명한글"
            FROM "터울주성분"
            WHERE "약효설명ID" = %s
              AND "IsDeleted" = FALSE
            ORDER BY "심평원성분코드"
        """, (yakho_id,))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_mechanism_data(src_conn, code: str) -> list[dict]:
    """성분코드의 MoA 데이터를 반환한다."""
    with src_conn.cursor() as cur:
        cur.execute("""
            SELECT
                action_type,
                mechanism_description,
                target_name,
                target_type,
                target_organism,
                direct_interaction,
                disease_efficacy
            FROM edb_mechanism
            WHERE "심평원성분코드" = %s
              AND (target_organism IS NULL OR target_organism = 'Homo sapiens')
            ORDER BY disease_efficacy DESC NULLS LAST,
                     direct_interaction DESC NULLS LAST
            LIMIT 5
        """, (code,))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_disease_data(src_conn, code: str) -> list[dict]:
    """성분코드의 적응증 데이터를 반환한다 (association_score 상위 5건)."""
    with src_conn.cursor() as cur:
        cur.execute("""
            SELECT
                disease_name,
                therapeutic_area,
                clinical_phase,
                association_score
            FROM edb_drug_disease
            WHERE "심평원성분코드" = %s
              AND association_score >= 0.3
            ORDER BY association_score DESC
            LIMIT 5
        """, (code,))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# V2 DB: 약효설명 존재 확인 및 저장
# ---------------------------------------------------------------------------

def check_v2_exists(v2_conn, yakho_id: int) -> bool:
    """v2 DB에 해당 약효설명ID가 llm_generated로 이미 존재하는지 확인한다."""
    with v2_conn.cursor() as cur:
        cur.execute("""
            SELECT 1
            FROM "터울약효설명"
            WHERE "약효설명ID" = %s
              AND source_type = 'llm_generated'
            LIMIT 1
        """, (yakho_id,))
        return cur.fetchone() is not None


def upsert_yakho_desc(
    v2_conn,
    yakho_id: int,
    korean_text: Optional[str],
    english_text: str,
    original_korean: Optional[str],
    original_english: Optional[str],
    regenerate: bool = False,
) -> bool:
    """v2 DB 터울약효설명에 저장한다.

    약효설명ID를 유지하면서 v2 DB에 upsert한다.

    Args:
        v2_conn: v2 DB connection
        yakho_id: 약효설명ID
        korean_text: 정제된 한국어 텍스트 (None이면 English only)
        english_text: 생성된 영어 텍스트
        original_korean: 원본 터울버전 (백업)
        original_english: 원본 EnglishText (백업)
        regenerate: True면 기존 레코드 UPDATE

    Returns:
        True: 성공, False: 실패
    """
    # original_text: 기존 터울버전 + EnglishText 백업
    original_parts = []
    if original_korean:
        original_parts.append(f"[KO] {original_korean}")
    if original_english:
        original_parts.append(f"[EN] {original_english}")
    original_text = "\n---\n".join(original_parts) if original_parts else None

    try:
        with v2_conn.cursor() as cur:
            if regenerate:
                # UPDATE 기존 레코드
                cur.execute("""
                    UPDATE "터울약효설명"
                    SET "터울버전" = %s,
                        "EnglishText" = %s,
                        source_type = 'llm_generated',
                        llm_version = %s,
                        generated_at = NOW(),
                        original_text = COALESCE(original_text, %s),
                        "ModifiedBy" = %s,
                        "IsDeleted" = FALSE,
                        "수정일" = NOW()
                    WHERE "약효설명ID" = %s
                """, (
                    korean_text or english_text,
                    english_text,
                    LLM_VERSION,
                    original_text,
                    MODIFIED_BY,
                    yakho_id,
                ))
                if cur.rowcount == 0:
                    # 레코드가 없으면 INSERT
                    cur.execute("""
                        INSERT INTO "터울약효설명" (
                            "약효설명ID",
                            "터울버전",
                            "EnglishText",
                            source_type,
                            llm_version,
                            generated_at,
                            original_text,
                            "ModifiedBy",
                            "IsDeleted",
                            "등록일",
                            "수정일"
                        )
                        VALUES (%s, %s, %s, 'llm_generated', %s, NOW(), %s, %s, FALSE, NOW(), NOW())
                    """, (
                        yakho_id,
                        korean_text or english_text,
                        english_text,
                        LLM_VERSION,
                        original_text,
                        MODIFIED_BY,
                    ))
            else:
                # INSERT (신규)
                cur.execute("""
                    INSERT INTO "터울약효설명" (
                        "약효설명ID",
                        "터울버전",
                        "EnglishText",
                        source_type,
                        llm_version,
                        generated_at,
                        original_text,
                        "ModifiedBy",
                        "IsDeleted",
                        "등록일",
                        "수정일"
                    )
                    VALUES (%s, %s, %s, 'llm_generated', %s, NOW(), %s, %s, FALSE, NOW(), NOW())
                    ON CONFLICT ("약효설명ID") DO UPDATE SET
                        "터울버전" = EXCLUDED."터울버전",
                        "EnglishText" = EXCLUDED."EnglishText",
                        source_type = EXCLUDED.source_type,
                        llm_version = EXCLUDED.llm_version,
                        generated_at = EXCLUDED.generated_at,
                        original_text = COALESCE("터울약효설명".original_text, EXCLUDED.original_text),
                        "ModifiedBy" = EXCLUDED."ModifiedBy",
                        "수정일" = NOW()
                """, (
                    yakho_id,
                    korean_text or english_text,
                    english_text,
                    LLM_VERSION,
                    original_text,
                    MODIFIED_BY,
                ))
        v2_conn.commit()
        return True
    except Exception as e:
        logger.error("v2 DB 저장 실패 (약효설명ID=%d): %s", yakho_id, e)
        v2_conn.rollback()
        return False


# ---------------------------------------------------------------------------
# Enrichment 데이터 → 컨텍스트 문자열
# ---------------------------------------------------------------------------

def build_enrichment_context(
    src_conn, ingredient_codes: list[str],
) -> str:
    """여러 성분코드의 enrichment 데이터를 종합하여 컨텍스트 문자열을 반환한다."""
    all_mechanisms: list[str] = []
    all_diseases: list[str] = []

    for code in ingredient_codes:
        mechanisms = fetch_mechanism_data(src_conn, code)
        diseases = fetch_disease_data(src_conn, code)

        for m in mechanisms:
            parts = []
            if m.get("action_type"):
                parts.append(f"Action: {m['action_type']}")
            if m.get("mechanism_description"):
                parts.append(f"Mechanism: {m['mechanism_description']}")
            if m.get("target_name"):
                target_info = m["target_name"]
                if m.get("target_type"):
                    target_info += f" ({m['target_type']})"
                parts.append(f"Target: {target_info}")
            if parts:
                all_mechanisms.append(" | ".join(parts))

        for d in diseases:
            parts = []
            if d.get("disease_name"):
                parts.append(d["disease_name"])
            if d.get("therapeutic_area"):
                parts.append(f"[{d['therapeutic_area']}]")
            if d.get("clinical_phase"):
                parts.append(f"Phase {d['clinical_phase']}")
            if d.get("association_score"):
                parts.append(f"score={d['association_score']:.2f}")
            if parts:
                all_diseases.append(" | ".join(parts))

    # 중복 제거
    all_mechanisms = list(dict.fromkeys(all_mechanisms))
    all_diseases = list(dict.fromkeys(all_diseases))

    sections = []
    if all_mechanisms:
        moa_text = "\n".join(f"  - {line}" for line in all_mechanisms[:10])
        sections.append(f"Mechanisms of Action:\n{moa_text}")
    if all_diseases:
        disease_text = "\n".join(f"  - {line}" for line in all_diseases[:10])
        sections.append(f"Therapeutic Indications:\n{disease_text}")

    return "\n\n".join(sections) if sections else "(no enrichment data available)"


# ---------------------------------------------------------------------------
# Claude API 호출
# ---------------------------------------------------------------------------

def call_claude(
    client: anthropic.Anthropic,
    prompt: str,
    max_tokens: int = 1500,
) -> Optional[str]:
    """Claude API를 호출하여 텍스트를 생성한다."""
    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except anthropic.APIError as e:
        logger.error("Claude API 오류: %s", e)
        return None
    except Exception as e:
        logger.error("Claude 호출 실패: %s", e)
        return None


# ---------------------------------------------------------------------------
# DeepL 번역
# ---------------------------------------------------------------------------

def translate_to_korean(text: str) -> Optional[str]:
    """DeepL API를 호출하여 영어 텍스트를 한국어로 번역한다."""
    api_key = os.getenv("DEEPL_API")
    if not api_key:
        logger.error("DEEPL_API 환경변수가 설정되지 않았습니다.")
        return None

    try:
        response = httpx.post(
            DEEPL_API_URL,
            data={
                "auth_key": api_key,
                "text": text,
                "source_lang": "EN",
                "target_lang": "KO",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        translations = response.json().get("translations", [])
        if translations:
            return translations[0].get("text", "").strip()
        logger.error("DeepL 응답에 번역 결과 없음")
        return None
    except httpx.HTTPStatusError as e:
        logger.error("DeepL HTTP 오류: %s", e)
        return None
    except Exception as e:
        logger.error("DeepL 번역 실패: %s", e)
        return None


# ---------------------------------------------------------------------------
# 단건 약효설명 생성 파이프라인
# ---------------------------------------------------------------------------

def generate_yakho_description(
    yakho_id: int,
    src_conn,
    v2_conn,
    claude_client: anthropic.Anthropic,
    dry_run: bool = False,
    skip_translation: bool = False,
    regenerate: bool = False,
) -> bool:
    """단일 약효설명ID에 대한 생성 파이프라인.

    1. Get existing 터울버전 and EnglishText from source DB
    2. Find all 심평원성분코드 linked to this 약효설명ID
    3. Gather enrichment data (edb_mechanism, edb_drug_disease) for those codes
    4. Build LLM prompt with existing text + enrichment evidence
    5. Call Claude API to generate enhanced English description
    6. Translate English -> Korean via DeepL
    7. Call Claude API to refine Korean
    8. Store in v2 DB with source_type='llm_generated'

    Returns:
        True: 성공, False: 실패
    """
    label = f"약효설명ID={yakho_id}"

    # 0. v2 DB 이미 존재 확인 (--regenerate 아니면 skip)
    if not regenerate and check_v2_exists(v2_conn, yakho_id):
        logger.debug("  [SKIP] %s — v2에 이미 존재 (llm_generated)", label)
        return False  # skipped

    # 1. 기존 데이터 조회
    yakho_data = fetch_single_yakho(src_conn, yakho_id)
    if not yakho_data:
        logger.warning("  [SKIP] %s — source DB에 데이터 없음", label)
        return False

    existing_korean = yakho_data.get("터울버전") or ""
    existing_english = yakho_data.get("EnglishText") or ""
    existing_text = ""
    if existing_english:
        existing_text += f"English: {existing_english}"
    if existing_korean:
        if existing_text:
            existing_text += "\n"
        existing_text += f"Korean: {existing_korean}"
    if not existing_text:
        existing_text = "(none)"

    # 2. 연결된 성분코드 조회
    ingredients = fetch_linked_ingredients(src_conn, yakho_id)
    ingredient_codes = [ing["심평원성분코드"] for ing in ingredients]

    ingredient_names_parts = []
    for ing in ingredients:
        name = ing.get("성분명") or ing.get("성분명한글") or ing["심평원성분코드"]
        ingredient_names_parts.append(name)
    ingredient_names = ", ".join(ingredient_names_parts[:10])
    if len(ingredient_names_parts) > 10:
        ingredient_names += f" (and {len(ingredient_names_parts) - 10} more)"

    # 약효설명 컨텍스트 (기존 터울버전 기반)
    yakho_description_context = existing_korean or existing_english or "(unknown drug class)"

    logger.info("  %s — 연결 성분: %d건", label, len(ingredients))

    # 3. Enrichment 데이터 수집
    enrichment_context = build_enrichment_context(src_conn, ingredient_codes)

    # 4. LLM 프롬프트 구성
    prompt = YAKHO_PROMPT.format(
        yakho_description_context=yakho_description_context,
        ingredient_names=ingredient_names,
        existing_text=existing_text,
        enrichment_context=enrichment_context,
    )

    if dry_run:
        print(f"\n{'='*60}")
        print(f"약효설명ID: {yakho_id}")
        print(f"연결 성분: {len(ingredients)}건")
        print(f"{'='*60}")
        print(prompt)
        print(f"{'='*60}\n")
        return True

    # 5. Claude API: English 약효설명 생성
    time.sleep(CLAUDE_SLEEP_BETWEEN)
    english_text = call_claude(claude_client, prompt, max_tokens=1500)

    if not english_text:
        logger.error("  [FAIL] %s — Claude 영문 생성 실패", label)
        return False

    logger.debug("  [EN] %s", english_text[:120])

    korean_text: Optional[str] = None

    if not skip_translation:
        # 6. DeepL: 영→한 번역
        time.sleep(DEEPL_SLEEP_BETWEEN)
        korean_translation = translate_to_korean(english_text)

        if not korean_translation:
            logger.warning("  [WARN] %s — DeepL 번역 실패, English only로 저장", label)
        else:
            # 7. Claude API: 한국어 정제
            refinement_prompt = KOREAN_REFINEMENT_PROMPT.format(
                english_text=english_text,
                korean_translation=korean_translation,
            )
            time.sleep(CLAUDE_SLEEP_BETWEEN)
            refined_korean = call_claude(claude_client, refinement_prompt, max_tokens=1500)

            if refined_korean:
                korean_text = refined_korean
                logger.debug("  [KO] %s", korean_text[:120])
            else:
                # 정제 실패 시 DeepL 번역 그대로 사용
                korean_text = korean_translation
                logger.warning("  [WARN] %s — 한국어 정제 실패, DeepL 번역 사용", label)

    # 8. v2 DB에 저장
    ok = upsert_yakho_desc(
        v2_conn,
        yakho_id=yakho_id,
        korean_text=korean_text,
        english_text=english_text,
        original_korean=existing_korean or None,
        original_english=existing_english or None,
        regenerate=regenerate,
    )

    if ok:
        logger.info("  [OK] %s — 저장 완료", label)
    else:
        logger.error("  [FAIL] %s — v2 DB 저장 실패", label)

    return ok


# ---------------------------------------------------------------------------
# 통계 출력
# ---------------------------------------------------------------------------

def show_stats(src_conn, v2_conn) -> None:
    """생성 통계를 출력한다."""
    with src_conn.cursor() as cur:
        # Source DB 전체 약효설명 건수
        cur.execute("""
            SELECT COUNT(*) FROM "터울약효설명" WHERE "IsDeleted" = FALSE
        """)
        total_source = cur.fetchone()[0]

        # 연결된 성분코드가 있는 약효설명 건수
        cur.execute("""
            SELECT COUNT(DISTINCT y."약효설명ID")
            FROM "터울약효설명" y
            JOIN "터울주성분" t ON t."약효설명ID" = y."약효설명ID"
            WHERE y."IsDeleted" = FALSE
              AND t."IsDeleted" = FALSE
        """)
        with_ingredients = cur.fetchone()[0]

    with v2_conn.cursor() as cur:
        # v2 DB 전체 약효설명 건수
        cur.execute("""
            SELECT COUNT(*) FROM "터울약효설명" WHERE "IsDeleted" = FALSE
        """)
        total_v2 = cur.fetchone()[0]

        # LLM 생성 건수
        cur.execute("""
            SELECT COUNT(*)
            FROM "터울약효설명"
            WHERE source_type = 'llm_generated'
              AND "IsDeleted" = FALSE
        """)
        llm_generated = cur.fetchone()[0]

        # Legacy 건수
        cur.execute("""
            SELECT COUNT(*)
            FROM "터울약효설명"
            WHERE (source_type = 'legacy' OR source_type IS NULL)
              AND "IsDeleted" = FALSE
        """)
        legacy_count = cur.fetchone()[0]

    print("\n" + "=" * 50)
    print("약효설명 Generation Statistics")
    print("=" * 50)
    print(f"\nSource DB (터울약효설명):")
    print(f"  전체 약효설명:         {total_source:,}건")
    print(f"  성분 연결 있는 건:     {with_ingredients:,}건")
    print(f"\nV2 DB (터울약효설명):")
    print(f"  전체:                  {total_v2:,}건")
    print(f"  LLM 생성:             {llm_generated:,}건")
    print(f"  Legacy:               {legacy_count:,}건")
    pending = total_source - llm_generated
    print(f"  미생성 (추정):         {max(0, pending):,}건")
    if total_source > 0:
        pct = 100 * llm_generated / total_source
        print(f"  생성률:               {pct:.1f}%")
    print("=" * 50 + "\n")


# ---------------------------------------------------------------------------
# 메인 파이프라인
# ---------------------------------------------------------------------------

def run_pipeline(
    src_conn,
    v2_conn,
    batch_size: int = DEFAULT_BATCH_SIZE,
    yakho_id: Optional[int] = None,
    dry_run: bool = False,
    skip_translation: bool = False,
    regenerate: bool = False,
) -> dict:
    """약효설명 생성 파이프라인.

    Returns:
        {"total": int, "success": int, "failed": int, "skipped": int}
    """
    # Claude 클라이언트 초기화
    if not dry_run:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
            sys.exit(1)
        claude_client = anthropic.Anthropic(api_key=api_key)
    else:
        claude_client = None  # type: ignore[assignment]

    # 처리 대상 결정
    if yakho_id is not None:
        # 단건 처리
        yakho_data = fetch_single_yakho(src_conn, yakho_id)
        if not yakho_data:
            logger.error("약효설명ID=%d 를 찾을 수 없습니다.", yakho_id)
            return {"total": 0, "success": 0, "failed": 1, "skipped": 0}
        target_ids = [yakho_id]
    else:
        # 전체 대상 조회
        all_yakho = fetch_all_yakho_ids(src_conn, regenerate=regenerate)
        target_ids = [y["약효설명ID"] for y in all_yakho]

        # regenerate가 아니면 v2 DB에 이미 있는 건 제외
        if not regenerate:
            filtered_ids = []
            for yid in target_ids:
                if not check_v2_exists(v2_conn, yid):
                    filtered_ids.append(yid)
            logger.info(
                "전체 %d건 중 미생성 %d건 (이미 생성: %d건)",
                len(target_ids), len(filtered_ids), len(target_ids) - len(filtered_ids),
            )
            target_ids = filtered_ids

        # batch_size 적용
        if batch_size > 0 and len(target_ids) > batch_size:
            target_ids = target_ids[:batch_size]
            logger.info("배치 크기 제한: %d건", batch_size)

    total = len(target_ids)
    if total == 0:
        logger.info("처리할 약효설명이 없습니다.")
        return {"total": 0, "success": 0, "failed": 0, "skipped": 0}

    logger.info(
        "처리 대상: %d건%s%s",
        total,
        " [DRY-RUN]" if dry_run else "",
        " [REGENERATE]" if regenerate else "",
    )

    tracker = ProgressTracker(total=total, source="yakho_desc", log_interval=10)

    for i, yid in enumerate(target_ids, 1):
        logger.info("[%d/%d] 약효설명ID=%d", i, total, yid)

        try:
            ok = generate_yakho_description(
                yakho_id=yid,
                src_conn=src_conn,
                v2_conn=v2_conn,
                claude_client=claude_client,
                dry_run=dry_run,
                skip_translation=skip_translation,
                regenerate=regenerate,
            )
            if ok:
                tracker.update(success=True)
            else:
                tracker.update(success=False, skipped=True)
        except KeyboardInterrupt:
            logger.info("사용자 중단.")
            break
        except Exception as e:
            logger.error("  [ERROR] 약효설명ID=%d — %s", yid, e)
            tracker.update(success=False)
            continue

    summary = tracker.summary()
    logger.info(
        "완료: 전체 %d건 | 성공 %d | 실패 %d | 건너뜀 %d | 소요 %.1f초",
        summary["total"], summary["success"], summary["failed"],
        summary["skipped"], summary["elapsed_seconds"],
    )
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 2-B: LLM 약효설명 Generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python generate_yakho_desc.py                            # 전체 미생성건 처리 (기본 배치 50)
  python generate_yakho_desc.py --yakho-id 123             # 단건 생성
  python generate_yakho_desc.py --batch-size 20            # 배치 크기 20
  python generate_yakho_desc.py --dry-run                  # 프롬프트만 출력
  python generate_yakho_desc.py --skip-translation         # English only
  python generate_yakho_desc.py --regenerate               # 기존 생성분 재생성
  python generate_yakho_desc.py --stats                    # 생성 통계
""",
    )

    parser.add_argument(
        "--yakho-id", type=int, metavar="ID",
        help="특정 약효설명ID만 생성",
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE, metavar="N",
        help=f"배치 크기 (기본: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="프롬프트만 출력, API 호출 및 DB 저장 없음",
    )
    parser.add_argument(
        "--skip-translation", action="store_true",
        help="English only (DeepL 번역 및 한국어 정제 건너뜀)",
    )
    parser.add_argument(
        "--regenerate", action="store_true",
        help="이미 생성된 건도 재생성",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="생성 통계 출력 후 종료",
    )

    args = parser.parse_args()

    # DB 연결
    src_conn = get_connection()
    v2_conn = get_v2_connection()

    logger.info(
        "연결: src_db=%s, v2_db=%s",
        os.getenv("DATABASE_NAME", "teoul_pharminfo"),
        os.getenv("V2_DATABASE_NAME", "teoul_pharminfo_v2"),
    )

    try:
        if args.stats:
            show_stats(src_conn, v2_conn)
            return

        run_pipeline(
            src_conn=src_conn,
            v2_conn=v2_conn,
            batch_size=args.batch_size,
            yakho_id=args.yakho_id,
            dry_run=args.dry_run,
            skip_translation=args.skip_translation,
            regenerate=args.regenerate,
        )
    except KeyboardInterrupt:
        logger.info("사용자 중단.")
    finally:
        src_conn.close()
        v2_conn.close()


if __name__ == "__main__":
    main()
