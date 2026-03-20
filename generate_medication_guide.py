"""
Phase 2-B: LLM Medication Guide Generation (복약안내 생성)

프로파일 해시 단위로 enrichment 데이터를 수집하고,
Claude API로 English 복약안내를 생성 -> DeepL로 한국어 번역 -> Claude로 한국어 리파인.
결과를 teoul_pharminfo_v2 DB 터울복약안내A4 테이블에 저장한다.

파이프라인:
  1. 터울복약프로파일에서 미생성 profile_hash 목록 조회
  2. 프로파일의 대표 성분코드로 edb_* 테이블에서 enrichment 데이터 수집
  3. safety_critical 섹션은 validation_status = 'expert_reviewed' 데이터만 사용
  4. Claude API로 English 복약안내 생성 (6개 section_type)
  5. DeepL API로 한국어 번역
  6. Claude API로 한국어 리파인 (의약학 용어 교정)
  7. 터울복약안내A4에 저장 + 터울프로파일A4매핑에 매핑

Usage:
    python generate_medication_guide.py                          # 전체 미생성 프로파일
    python generate_medication_guide.py --profile-hash abc123    # 특정 프로파일
    python generate_medication_guide.py --section mechanism      # 특정 섹션만
    python generate_medication_guide.py --batch-size 10          # 10 프로파일씩
    python generate_medication_guide.py --dry-run                # 프롬프트만 출력
    python generate_medication_guide.py --skip-translation       # English만 생성
    python generate_medication_guide.py --stats                  # 생성 통계
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

import anthropic
import httpx

from common import get_connection, get_v2_connection
from enrich_base import ProgressTracker, normalize_for_hash

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
MODIFIED_BY = "pharmport_llm"
LLM_VERSION = 1

# Rate limit (분당 최대 호출 수)
CLAUDE_REQUESTS_PER_MINUTE = 10
CLAUDE_SLEEP_BETWEEN = 60.0 / CLAUDE_REQUESTS_PER_MINUTE  # 6초

DEEPL_REQUESTS_PER_MINUTE = 20
DEEPL_SLEEP_BETWEEN = 60.0 / DEEPL_REQUESTS_PER_MINUTE  # 3초

DEFAULT_BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# Section Type 정의
# ---------------------------------------------------------------------------

SECTION_TYPES = {
    "mechanism": {
        "description": "How the drug works",
        "source_tables": ["edb_mechanism"],
        "safety_critical": False,
    },
    "precaution": {
        "description": "Precautions and warnings",
        "source_tables": ["edb_safety"],
        "safety_critical": True,
    },
    "interaction": {
        "description": "Drug interactions",
        "source_tables": ["edb_drug_disease", "edb_safety"],
        "safety_critical": True,
    },
    "contraindication": {
        "description": "When NOT to use this drug",
        "source_tables": ["edb_safety"],
        "safety_critical": True,
    },
    "monitoring": {
        "description": "What to monitor during treatment",
        "source_tables": ["edb_safety"],
        "safety_critical": True,
    },
    "special_pop": {
        "description": "Special populations (pregnancy, elderly, children, renal/hepatic)",
        "source_tables": ["edb_safety"],
        "safety_critical": True,
    },
}

# section_type -> 분류 (호환성)
SECTION_TYPE_TO_분류 = {
    "mechanism": 1,
    "precaution": 2,
    "interaction": 3,
    "contraindication": 4,
    "monitoring": 5,
    "special_pop": 6,
}


# ---------------------------------------------------------------------------
# LLM 프롬프트 템플릿
# ---------------------------------------------------------------------------

GENERATION_PROMPT = """You are a pharmaceutical information specialist creating medication guides.

Drug: {ingredient_name}
Section: {section_type} - {section_description}

Available evidence:
{enrichment_context}

Generate a clear, patient-friendly medication guide section following the "Why + What + Who" principle:
- Why: Why does this matter for the patient?
- What: What specifically should the patient know?
- Who: Who is especially affected?

Requirements:
- Use evidence-based information only
- Be concise but comprehensive
- Use plain language accessible to patients
- Include specific examples where helpful
- Mark uncertainty levels where evidence is limited

Output format: Plain text, 2-4 paragraphs."""

KOREAN_REFINEMENT_PROMPT = """You are a Korean medical translation specialist. Review and refine this Korean translation of a medication guide.

Original English:
{english_text}

Machine Translation (Korean):
{korean_translation}

Refine the Korean text:
1. Ensure medical terminology is correct in Korean pharmaceutical context
2. Use standard Korean pharmaceutical terms (약학 용어)
3. Maintain patient-friendly tone
4. Fix any awkward phrasing from machine translation
5. Keep the same structure and information

Output: Refined Korean text only."""


# ---------------------------------------------------------------------------
# DB 헬퍼
# ---------------------------------------------------------------------------

def _fetch_all(conn, sql: str, params: tuple = ()) -> list[dict]:
    """SELECT 결과를 dict 리스트로 반환한다."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _fetch_one(conn, sql: str, params: tuple = ()) -> dict | None:
    """SELECT 1건을 dict로 반환한다."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# 프로파일 조회
# ---------------------------------------------------------------------------

def fetch_pending_profiles(v2_conn, limit: int = 0) -> list[dict]:
    """복약안내가 아직 생성되지 않은 프로파일 목록을 반환한다.

    터울복약프로파일에 존재하지만 터울프로파일A4매핑이 없는 프로파일.
    """
    limit_clause = f"LIMIT {limit}" if limit > 0 else ""
    return _fetch_all(v2_conn, f"""
        SELECT
            p.profile_id,
            p.profile_hash,
            p.profile_type,
            p.profile_json,
            p.ingredient_count
        FROM "터울복약프로파일" p
        WHERE NOT EXISTS (
            SELECT 1
            FROM "터울프로파일A4매핑" m
            WHERE m.profile_id = p.profile_id
        )
        ORDER BY p.profile_id
        {limit_clause}
    """)


def fetch_profile_by_hash(v2_conn, profile_hash: str) -> dict | None:
    """특정 profile_hash의 프로파일을 반환한다."""
    return _fetch_one(v2_conn, """
        SELECT
            p.profile_id,
            p.profile_hash,
            p.profile_type,
            p.profile_json,
            p.ingredient_count
        FROM "터울복약프로파일" p
        WHERE p.profile_hash = %s
    """, (profile_hash,))


def fetch_representative_code(v2_conn, profile_id: int) -> str | None:
    """프로파일에 매핑된 첫 번째 심평원성분코드를 반환한다."""
    row = _fetch_one(v2_conn, """
        SELECT "심평원성분코드"
        FROM "터울주성분프로파일매핑"
        WHERE profile_id = %s
        ORDER BY "심평원성분코드"
        LIMIT 1
    """, (profile_id,))
    return row["심평원성분코드"] if row else None


def fetch_ingredient_name(src_conn, code: str) -> tuple[str, str]:
    """성분코드의 영문명, 한글명을 반환한다."""
    row = _fetch_one(src_conn, """
        SELECT "성분명", "성분명한글"
        FROM "터울주성분"
        WHERE "심평원성분코드" = %s
    """, (code,))
    if row:
        return row.get("성분명") or "", row.get("성분명한글") or ""
    return "", ""


def _resolve_representative_code(v2_conn, profile: dict) -> str | None:
    """프로파일에서 대표 성분코드를 해석한다.

    1. 터울주성분프로파일매핑 조회
    2. 실패 시 profile_json.codes에서 추출
    """
    code = fetch_representative_code(v2_conn, profile["profile_id"])
    if code:
        return code

    pj = profile.get("profile_json")
    if isinstance(pj, str):
        try:
            pj = json.loads(pj)
        except (json.JSONDecodeError, TypeError):
            return None

    if isinstance(pj, dict):
        codes = pj.get("codes", [])
        if codes:
            return codes[0]

    return None


# ---------------------------------------------------------------------------
# Enrichment 데이터 조회
# ---------------------------------------------------------------------------

def fetch_mechanism_data(src_conn, code: str) -> list[dict]:
    """edb_mechanism에서 MoA 데이터를 반환한다."""
    return _fetch_all(src_conn, """
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
        LIMIT 10
    """, (code,))


def fetch_safety_data(
    src_conn,
    code: str,
    info_type: str | None = None,
    require_expert_reviewed: bool = False,
) -> list[dict]:
    """edb_safety에서 안전성 데이터를 반환한다.

    Args:
        src_conn: 소스 DB 커넥션
        code: 심평원성분코드
        info_type: 필터 (precaution, interaction, contraindication 등)
        require_expert_reviewed: True이면 validation_status='expert_reviewed'만 반환
    """
    conditions = ['"심평원성분코드" = %s']
    params: list[Any] = [code]

    if info_type:
        conditions.append("info_type = %s")
        params.append(info_type)

    if require_expert_reviewed:
        conditions.append("validation_status = 'expert_reviewed'")

    where_clause = " AND ".join(conditions)

    return _fetch_all(src_conn, f"""
        SELECT
            info_type,
            description,
            severity,
            related_ingredient_code,
            evidence_level,
            source,
            validation_status
        FROM edb_safety
        WHERE {where_clause}
        ORDER BY
            CASE severity
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'moderate' THEN 3
                WHEN 'low' THEN 4
                ELSE 5
            END,
            safety_id
        LIMIT 15
    """, tuple(params))


def fetch_disease_data(src_conn, code: str) -> list[dict]:
    """edb_drug_disease에서 적응증 데이터를 반환한다."""
    return _fetch_all(src_conn, """
        SELECT
            disease_name,
            therapeutic_area,
            clinical_phase,
            association_score
        FROM edb_drug_disease
        WHERE "심평원성분코드" = %s
          AND association_score >= 0.3
        ORDER BY association_score DESC
        LIMIT 10
    """, (code,))


# ---------------------------------------------------------------------------
# Enrichment 컨텍스트 포맷팅
# ---------------------------------------------------------------------------

def _format_mechanism_context(mechanisms: list[dict]) -> str:
    if not mechanisms:
        return "  (no mechanism data available)"
    lines = []
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
            lines.append("  - " + " | ".join(parts))
    return "\n".join(lines) if lines else "  (no mechanism data available)"


def _format_safety_context(safety_records: list[dict]) -> str:
    if not safety_records:
        return "  (no safety data available)"
    lines = []
    for s in safety_records:
        parts = []
        if s.get("info_type"):
            parts.append(f"[{s['info_type'].upper()}]")
        if s.get("severity"):
            parts.append(f"Severity: {s['severity']}")
        if s.get("description"):
            parts.append(s["description"])
        if s.get("evidence_level"):
            parts.append(f"(evidence: {s['evidence_level']})")
        if parts:
            lines.append("  - " + " ".join(parts))
    return "\n".join(lines) if lines else "  (no safety data available)"


def _format_disease_context(diseases: list[dict]) -> str:
    if not diseases:
        return "  (no disease/indication data available)"
    lines = []
    for d in diseases:
        parts = []
        if d.get("disease_name"):
            parts.append(d["disease_name"])
        if d.get("therapeutic_area"):
            parts.append(f"(area: {d['therapeutic_area']})")
        if d.get("clinical_phase"):
            parts.append(f"[Phase {d['clinical_phase']}]")
        if d.get("association_score") is not None:
            parts.append(f"score: {d['association_score']:.2f}")
        if parts:
            lines.append("  - " + " ".join(parts))
    return "\n".join(lines) if lines else "  (no disease/indication data available)"


def build_enrichment_context(
    src_conn,
    code: str,
    section_type: str,
    section_config: dict,
) -> str | None:
    """섹션 타입에 따라 enrichment 컨텍스트를 구성한다.

    safety_critical 섹션은 expert_reviewed 데이터만 사용한다.
    데이터가 없으면 None을 반환한다.
    """
    is_safety_critical = section_config["safety_critical"]
    source_tables = section_config["source_tables"]
    context_parts: list[str] = []

    # edb_mechanism 데이터
    if "edb_mechanism" in source_tables:
        mechanisms = fetch_mechanism_data(src_conn, code)
        if mechanisms:
            context_parts.append("Mechanism of Action:")
            context_parts.append(_format_mechanism_context(mechanisms))

    # edb_safety 데이터
    if "edb_safety" in source_tables:
        info_type_map = {
            "precaution": "precaution",
            "interaction": "interaction",
            "contraindication": "contraindication",
            "monitoring": "monitoring",
            "special_pop": "special_population",
        }
        info_type_filter = info_type_map.get(section_type)

        safety_records = fetch_safety_data(
            src_conn,
            code,
            info_type=info_type_filter,
            require_expert_reviewed=is_safety_critical,
        )

        if safety_records:
            context_parts.append(f"Safety Information ({section_type}):")
            context_parts.append(_format_safety_context(safety_records))
        elif is_safety_critical:
            # expert_reviewed 데이터 없으면 draft 데이터 확인하여 경고
            draft_records = fetch_safety_data(
                src_conn, code, info_type=info_type_filter,
                require_expert_reviewed=False,
            )
            if draft_records:
                logger.warning(
                    "  [GATE] %s/%s — %d건 draft 데이터 존재하나 "
                    "expert_reviewed 아님, 건너뜀",
                    code, section_type, len(draft_records),
                )

    # edb_drug_disease 데이터
    if "edb_drug_disease" in source_tables:
        diseases = fetch_disease_data(src_conn, code)
        if diseases:
            context_parts.append("Disease/Indication Data:")
            context_parts.append(_format_disease_context(diseases))

    if not context_parts:
        return None

    return "\n\n".join(context_parts)


# ---------------------------------------------------------------------------
# Claude API
# ---------------------------------------------------------------------------

def call_claude(
    client: anthropic.Anthropic,
    prompt: str,
    max_tokens: int = 2000,
    retries: int = 3,
) -> str | None:
    """Claude API를 호출하여 텍스트를 생성한다.

    재시도 로직 포함. 모든 시도 실패 시 None 반환.
    """
    last_err: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
        except anthropic.RateLimitError as e:
            wait = 2 ** attempt
            logger.warning(
                "Claude rate limit (시도 %d/%d) — %ds 후 재시도",
                attempt, retries, wait,
            )
            time.sleep(wait)
            last_err = e
        except anthropic.APIError as e:
            logger.error("Claude API 오류 (시도 %d/%d): %s", attempt, retries, e)
            last_err = e
            if attempt < retries:
                time.sleep(2 ** attempt)
        except Exception as e:
            logger.error("Claude 호출 실패: %s", e)
            return None

    logger.error("Claude API 최종 실패: %s", last_err)
    return None


# ---------------------------------------------------------------------------
# DeepL 번역
# ---------------------------------------------------------------------------

def translate_to_korean(text: str) -> str | None:
    """DeepL API로 영어 텍스트를 한국어로 번역한다."""
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
        data = response.json()
        translations = data.get("translations", [])
        if translations:
            return translations[0].get("text", "").strip()
        logger.error("DeepL 응답에 번역 결과 없음: %s", data)
        return None
    except httpx.HTTPStatusError as e:
        logger.error("DeepL HTTP 오류: %s", e)
        return None
    except Exception as e:
        logger.error("DeepL 번역 실패: %s", e)
        return None


# ---------------------------------------------------------------------------
# 프롬프트 해시 (재현성)
# ---------------------------------------------------------------------------

def compute_prompt_hash(prompt: str) -> str:
    """프롬프트의 SHA-256 해시 앞 16자를 반환한다."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# V2 DB 저장
# ---------------------------------------------------------------------------

def insert_a4_record(
    v2_conn,
    content_ko: str | None,
    content_en: str,
    section_type: str,
    profile_hash: str,
) -> int | None:
    """터울복약안내A4에 레코드를 삽입하고 복약안내A4ID를 반환한다."""
    분류값 = SECTION_TYPE_TO_분류.get(section_type, 99)

    with v2_conn.cursor() as cur:
        cur.execute("""
            INSERT INTO "터울복약안내A4" (
                content,
                content_en,
                section_type,
                validation_status,
                "터울버전",
                "분류",
                "IsDeleted",
                "ModifiedBy",
                "EnglishText",
                "등록일",
                "수정일"
            )
            VALUES (%s, %s, %s, 'draft', %s, %s, FALSE, %s, %s, NOW(), NOW())
            RETURNING "복약안내A4ID"
        """, (
            content_ko or content_en,
            content_en,
            section_type,
            f"llm_v{LLM_VERSION}",
            분류값,
            MODIFIED_BY,
            content_en,
        ))
        row = cur.fetchone()
    v2_conn.commit()
    return row[0] if row else None


def insert_profile_a4_mapping(
    v2_conn,
    profile_id: int,
    a4_id: int,
    sort_order: int = 0,
) -> bool:
    """터울프로파일A4매핑에 매핑을 삽입한다."""
    try:
        with v2_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO "터울프로파일A4매핑" (
                    profile_id, "복약안내A4ID", sort_order, mapped_at
                )
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT DO NOTHING
            """, (profile_id, a4_id, sort_order))
        v2_conn.commit()
        return True
    except Exception as e:
        logger.error("프로파일A4매핑 INSERT 실패: %s", e)
        v2_conn.rollback()
        return False


# ---------------------------------------------------------------------------
# 단건 섹션 생성
# ---------------------------------------------------------------------------

def generate_section(
    src_conn,
    v2_conn,
    claude_client: anthropic.Anthropic,
    code: str,
    ingredient_name: str,
    section_type: str,
    section_config: dict,
    profile_id: int,
    profile_hash: str,
    sort_order: int,
    skip_translation: bool = False,
    dry_run: bool = False,
) -> int | None:
    """단일 섹션을 생성하고 저장한다.

    Returns:
        생성된 복약안내A4ID 또는 None (실패/건너뜀)
    """
    label = f"{profile_hash[:8]}/{section_type}"

    # 1. Enrichment 컨텍스트 구성
    enrichment_context = build_enrichment_context(
        src_conn, code, section_type, section_config,
    )

    if enrichment_context is None:
        logger.info("    [SKIP] %s — enrichment 데이터 없음", label)
        return None

    # 2. 프롬프트 구성
    prompt = GENERATION_PROMPT.format(
        ingredient_name=ingredient_name,
        section_type=section_type,
        section_description=section_config["description"],
        enrichment_context=enrichment_context,
    )
    prompt_hash = compute_prompt_hash(prompt)

    if dry_run:
        print(f"\n{'=' * 60}")
        print(f"SECTION: {label} (prompt_hash={prompt_hash})")
        print(f"{'=' * 60}")
        print(prompt)
        print(f"{'=' * 60}\n")
        return None

    # 3. Claude API — English 생성
    time.sleep(CLAUDE_SLEEP_BETWEEN)
    english_text = call_claude(claude_client, prompt)

    if not english_text:
        logger.error("    [FAIL] %s — Claude 생성 실패", label)
        return None

    logger.debug("    [EN] %s: %s", label, english_text[:100])

    korean_text: str | None = None

    if not skip_translation:
        # 4. DeepL — 한국어 번역
        time.sleep(DEEPL_SLEEP_BETWEEN)
        korean_raw = translate_to_korean(english_text)

        if not korean_raw:
            logger.warning(
                "    [WARN] %s — DeepL 번역 실패, English만 저장", label,
            )
        else:
            # 5. Claude API — 한국어 리파인
            refinement_prompt = KOREAN_REFINEMENT_PROMPT.format(
                english_text=english_text,
                korean_translation=korean_raw,
            )
            time.sleep(CLAUDE_SLEEP_BETWEEN)
            korean_text = call_claude(claude_client, refinement_prompt)

            if not korean_text:
                logger.warning(
                    "    [WARN] %s — 한국어 리파인 실패, 기계번역 사용",
                    label,
                )
                korean_text = korean_raw

    # 6. V2 DB 저장
    a4_id = insert_a4_record(
        v2_conn,
        content_ko=korean_text,
        content_en=english_text,
        section_type=section_type,
        profile_hash=profile_hash,
    )

    if not a4_id:
        logger.error("    [FAIL] %s — 터울복약안내A4 INSERT 실패", label)
        return None

    # 7. 프로파일 매핑
    insert_profile_a4_mapping(v2_conn, profile_id, a4_id, sort_order)

    logger.info(
        "    [OK] %s -> A4ID=%d (prompt=%s)", label, a4_id, prompt_hash,
    )
    return a4_id


# ---------------------------------------------------------------------------
# 프로파일 단위 생성
# ---------------------------------------------------------------------------

def generate_for_profile(
    src_conn,
    v2_conn,
    claude_client: anthropic.Anthropic | None,
    profile: dict,
    target_sections: list[str] | None = None,
    skip_translation: bool = False,
    dry_run: bool = False,
) -> dict:
    """프로파일 1건에 대해 전체(또는 지정) 섹션을 생성한다.

    Returns:
        {"generated": int, "skipped": int, "failed": int}
    """
    profile_id = profile["profile_id"]
    profile_hash = profile["profile_hash"]
    label = f"{profile_hash[:12]} (id={profile_id})"

    # 대표 성분코드 조회
    code = _resolve_representative_code(v2_conn, profile)

    if not code:
        logger.warning("  [SKIP] %s — 매핑된 성분코드 없음", label)
        return {"generated": 0, "skipped": len(SECTION_TYPES), "failed": 0}

    # 성분명 조회
    name_en, name_kr = fetch_ingredient_name(src_conn, code)
    ingredient_name = name_en or name_kr or code

    logger.info(
        "  프로파일: %s — 성분: %s (%s)",
        label, code, ingredient_name[:40],
    )

    # 생성할 섹션 결정
    sections_to_generate = target_sections or list(SECTION_TYPES.keys())
    result = {"generated": 0, "skipped": 0, "failed": 0}

    for sort_order, section_type in enumerate(sections_to_generate, 1):
        if section_type not in SECTION_TYPES:
            logger.warning(
                "    [SKIP] 알 수 없는 section_type: %s", section_type,
            )
            result["skipped"] += 1
            continue

        section_config = SECTION_TYPES[section_type]

        try:
            a4_id = generate_section(
                src_conn=src_conn,
                v2_conn=v2_conn,
                claude_client=claude_client,
                code=code,
                ingredient_name=ingredient_name,
                section_type=section_type,
                section_config=section_config,
                profile_id=profile_id,
                profile_hash=profile_hash,
                sort_order=sort_order,
                skip_translation=skip_translation,
                dry_run=dry_run,
            )

            if a4_id is not None:
                result["generated"] += 1
            else:
                result["skipped"] += 1

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error("    [ERROR] %s/%s — %s", label, section_type, e)
            result["failed"] += 1

    return result


# ---------------------------------------------------------------------------
# 통계
# ---------------------------------------------------------------------------

def show_stats(v2_conn, src_conn) -> None:
    """생성 현황 통계를 출력한다."""
    print("\n=== 복약안내 생성 통계 ===\n")

    with v2_conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM "터울복약프로파일"')
        total_profiles = cur.fetchone()[0]

    with v2_conn.cursor() as cur:
        cur.execute(
            'SELECT COUNT(DISTINCT profile_id) FROM "터울프로파일A4매핑"'
        )
        mapped_profiles = cur.fetchone()[0]

    with v2_conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM "터울복약안내A4"')
        total_a4 = cur.fetchone()[0]

    with v2_conn.cursor() as cur:
        cur.execute("""
            SELECT section_type, COUNT(*)
            FROM "터울복약안내A4"
            WHERE section_type IS NOT NULL
            GROUP BY section_type
            ORDER BY section_type
        """)
        section_counts = cur.fetchall()

    with v2_conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*)
            FROM "터울복약안내A4"
            WHERE "ModifiedBy" = %s
        """, (MODIFIED_BY,))
        llm_generated = cur.fetchone()[0]

    try:
        with src_conn.cursor() as cur:
            cur.execute("""
                SELECT validation_status, COUNT(*)
                FROM edb_safety
                GROUP BY validation_status
                ORDER BY validation_status
            """)
            safety_status = cur.fetchall()
    except Exception:
        safety_status = []

    print(f"{'항목':<35} {'건수':>10}")
    print("-" * 50)
    print(f"{'전체 프로파일':.<35} {total_profiles:>10,}")
    print(f"{'A4 매핑 완료 프로파일':.<35} {mapped_profiles:>10,}")
    print(f"{'미생성 프로파일':.<35} {total_profiles - mapped_profiles:>10,}")
    print(f"{'전체 A4 레코드':.<35} {total_a4:>10,}")
    print(f"{'LLM 생성 레코드':.<35} {llm_generated:>10,}")

    if section_counts:
        print(f"\n섹션별 A4 레코드:")
        print("-" * 50)
        for section_type, count in section_counts:
            print(f"  {section_type or '(null)':<33} {count:>10,}")

    if safety_status:
        print(f"\nedb_safety 검증 상태:")
        print("-" * 50)
        for status, count in safety_status:
            print(f"  {status or '(null)':<33} {count:>10,}")

    print()


# ---------------------------------------------------------------------------
# 메인 파이프라인
# ---------------------------------------------------------------------------

def run_pipeline(
    src_conn,
    v2_conn,
    batch_size: int = DEFAULT_BATCH_SIZE,
    profile_hash: str | None = None,
    target_sections: list[str] | None = None,
    skip_translation: bool = False,
    dry_run: bool = False,
) -> dict:
    """전체 생성 파이프라인을 실행한다.

    Returns:
        {"total_profiles": int, "total_generated": int,
         "total_skipped": int, "total_failed": int,
         "elapsed_seconds": float}
    """
    empty_result = {
        "total_profiles": 0,
        "total_generated": 0,
        "total_skipped": 0,
        "total_failed": 0,
        "elapsed_seconds": 0.0,
    }

    # Claude 클라이언트 초기화
    claude_client: anthropic.Anthropic | None = None
    if not dry_run:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
            sys.exit(1)
        claude_client = anthropic.Anthropic(api_key=api_key)

    # 처리 대상 결정
    if profile_hash:
        profile = fetch_profile_by_hash(v2_conn, profile_hash)
        if not profile:
            logger.error("프로파일을 찾을 수 없습니다: %s", profile_hash)
            return empty_result
        profiles = [profile]
    else:
        profiles = fetch_pending_profiles(v2_conn, limit=batch_size)

    total_profiles = len(profiles)
    if total_profiles == 0:
        logger.info("처리할 프로파일이 없습니다.")
        return empty_result

    suffix = " [DRY-RUN]" if dry_run else ""
    sections_label = ", ".join(target_sections) if target_sections else "all"
    logger.info(
        "처리 대상: %d 프로파일, 섹션: %s%s",
        total_profiles, sections_label, suffix,
    )

    tracker = ProgressTracker(
        total=total_profiles, source="medication_guide", log_interval=10,
    )
    total_generated = 0
    total_skipped = 0
    total_failed = 0
    start_time = time.monotonic()

    for i, profile in enumerate(profiles, 1):
        ph = profile["profile_hash"][:12]
        logger.info("[%d/%d] 프로파일: %s", i, total_profiles, ph)

        try:
            result = generate_for_profile(
                src_conn=src_conn,
                v2_conn=v2_conn,
                claude_client=claude_client,
                profile=profile,
                target_sections=target_sections,
                skip_translation=skip_translation,
                dry_run=dry_run,
            )
            total_generated += result["generated"]
            total_skipped += result["skipped"]
            total_failed += result["failed"]

            has_output = result["generated"] > 0 or result["skipped"] > 0
            tracker.update(
                success=has_output, skipped=(result["generated"] == 0),
            )

        except KeyboardInterrupt:
            logger.info("사용자 중단.")
            break
        except Exception as e:
            logger.error("  [ERROR] 프로파일 %s — %s", ph, e)
            total_failed += 1
            tracker.update(success=False)

    elapsed = time.monotonic() - start_time

    logger.info(
        "완료: %d 프로파일 처리 | 생성 %d | 건너뜀 %d | 실패 %d | 소요 %.1f초",
        total_profiles, total_generated, total_skipped, total_failed, elapsed,
    )

    return {
        "total_profiles": total_profiles,
        "total_generated": total_generated,
        "total_skipped": total_skipped,
        "total_failed": total_failed,
        "elapsed_seconds": round(elapsed, 1),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 2-B: LLM Medication Guide Generation (복약안내 생성)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python generate_medication_guide.py                          # 전체 미생성 프로파일
  python generate_medication_guide.py --profile-hash abc123    # 특정 프로파일
  python generate_medication_guide.py --section mechanism      # 특정 섹션만
  python generate_medication_guide.py --batch-size 10          # 10 프로파일씩
  python generate_medication_guide.py --dry-run                # 프롬프트만 출력
  python generate_medication_guide.py --skip-translation       # English만 생성
  python generate_medication_guide.py --stats                  # 생성 통계
""",
    )

    parser.add_argument(
        "--profile-hash",
        type=str,
        default=None,
        help="특정 프로파일 해시만 처리",
    )
    parser.add_argument(
        "--section",
        type=str,
        default=None,
        choices=list(SECTION_TYPES.keys()),
        help="특정 섹션만 생성",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"프로파일 배치 크기 (기본: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="프롬프트만 출력, API 호출 및 DB 저장 없음",
    )
    parser.add_argument(
        "--skip-translation",
        action="store_true",
        help="English만 생성 (DeepL 번역 + 한국어 리파인 건너뜀)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="생성 현황 통계만 출력",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="dev DB(teoul_201201) 사용",
    )

    args = parser.parse_args()

    # DB 연결
    src_db_name = os.getenv("DEV_DATABASE_NAME") if args.dev else None
    src_conn = get_connection(src_db_name)
    v2_conn = get_v2_connection()

    logger.info(
        "연결: src_db=%s, v2_db=%s",
        src_db_name or os.getenv("DATABASE_NAME", "teoul_pharminfo"),
        os.getenv("V2_DATABASE_NAME", "teoul_pharminfo_v2"),
    )

    try:
        # --stats: 통계만 출력
        if args.stats:
            show_stats(v2_conn, src_conn)
            return

        # 섹션 필터
        target_sections = [args.section] if args.section else None

        # dry-run은 3 프로파일만
        batch_size = 3 if args.dry_run else args.batch_size

        run_pipeline(
            src_conn=src_conn,
            v2_conn=v2_conn,
            batch_size=batch_size,
            profile_hash=args.profile_hash,
            target_sections=target_sections,
            skip_translation=args.skip_translation,
            dry_run=args.dry_run,
        )

    except KeyboardInterrupt:
        logger.info("사용자 중단.")
    finally:
        src_conn.close()
        v2_conn.close()


if __name__ == "__main__":
    main()
