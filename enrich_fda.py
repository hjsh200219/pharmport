"""
Phase 1-B: openFDA Drug Labeling + FAERS Enrichment

openFDA Drug Labeling API를 사용해 BBW, 금기, 부작용, 상호작용을 수집하고
FAERS로 실제 보고된 부작용 빈도 상위 10건을 추가 수집한다.

API 최적화:
  - 심평원성분코드 1-4자리(주성분) + 7자리(투여경로)가 같으면 FDA 데이터를 공유함
  - (base, route) 조합당 1회만 API 호출 후 해당 조합의 모든 코드에 저장

번역:
  - DEEPL_API 환경변수가 있으면 영문 description을 한국어로 번역하여 함께 저장
  - 번역본은 description_ko 컬럼에 저장 (없으면 NULL)

Usage:
    python enrich_fda.py                      # 전체 미완료 처리
    python enrich_fda.py --code 101301AIJ     # 단건
    python enrich_fda.py --limit 100          # 100건
    python enrich_fda.py --dev                # dev DB
    python enrich_fda.py --dry-run            # 테스트 (DB 저장 안 함)
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass

import requests

from common import get_connection
from concurrent.futures import ThreadPoolExecutor, as_completed

from enrich_base import (
    ProgressTracker,
    _safe_tracker_update,
    api_call_with_retry,
    batch_insert,
    get_pending_codes,
    get_thread_connection,
    preprocess_ingredient_name,
    update_status,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

OPENFDA_BASE = "https://api.fda.gov"
DEEPL_BASE = "https://api-free.deepl.com/v2/translate"

# edb_safety.info_type 값
INFO_TYPE_BBW = "black_box_warning"
INFO_TYPE_CONTRAINDICATION = "contraindication"
INFO_TYPE_ADVERSE_EFFECT = "adverse_effect"
INFO_TYPE_INTERACTION = "interaction"
INFO_TYPE_WARNING = "warning"

# edb_safety.severity 값
SEV_CRITICAL = "critical"
SEV_SEVERE = "severe"
SEV_MODERATE = "moderate"
SEV_MILD = "mild"

# FDA label 섹션 → (info_type, severity)
LABEL_SECTIONS: list[tuple[str, str, str]] = [
    ("boxed_warning",          INFO_TYPE_BBW,              SEV_CRITICAL),
    ("contraindications",      INFO_TYPE_CONTRAINDICATION, SEV_SEVERE),
    ("warnings_and_cautions",  INFO_TYPE_WARNING,          SEV_SEVERE),
    ("adverse_reactions",      INFO_TYPE_ADVERSE_EFFECT,   SEV_MODERATE),
    ("drug_interactions",      INFO_TYPE_INTERACTION,      SEV_MODERATE),
]

# FAERS 상위 N건
FAERS_TOP_N = 10

# description 최대 길이 (DB TEXT 컬럼이지만 지나치게 긴 FDA 텍스트 트리밍)
MAX_DESC_LEN = 10_000

# DeepL 번역 최대 길이 (DeepL 무료 플랜은 128K chars/month, 단건 안전 상한)
MAX_TRANSLATE_LEN = 5_000


# ---------------------------------------------------------------------------
# 심평원성분코드 파서 (enrich_new_ingredient.py와 동일 구조)
# ---------------------------------------------------------------------------

@dataclass
class ParsedCode:
    code: str
    base: str       # 1-4자리
    type_code: str  # 5-6자리
    route: str      # 7자리 (A/B/C/D)
    dosage_form: str  # 8-9자리


def parse_code(code: str) -> ParsedCode | None:
    if not code or len(code) != 9:
        return None
    return ParsedCode(
        code=code,
        base=code[0:4],
        type_code=code[4:6],
        route=code[6],
        dosage_form=code[7:9],
    )


# ---------------------------------------------------------------------------
# openFDA Drug Label API
# ---------------------------------------------------------------------------

def _build_label_url(ingredient_name: str, api_key: str | None) -> str:
    clean = ingredient_name.replace('"', '\\"')
    url = (
        f'{OPENFDA_BASE}/drug/label.json'
        f'?search=openfda.generic_name:"{clean}"&limit=1'
    )
    if api_key:
        url += f"&api_key={api_key}"
    return url


def _build_faers_url(ingredient_name: str, api_key: str | None) -> str:
    clean = ingredient_name.replace('"', '\\"')
    url = (
        f'{OPENFDA_BASE}/drug/event.json'
        f'?search=patient.drug.openfda.generic_name:"{clean}"'
        f'&count=patient.reaction.reactionmeddrapt.exact'
        f'&limit={FAERS_TOP_N}'
    )
    if api_key:
        url += f"&api_key={api_key}"
    return url


def _get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {"User-Agent": "TeoulPharmPort/1.0 (teoul-testpg enrichment)"}
    )
    return s


_session: requests.Session | None = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _get_session()
    return _session


def fetch_label(ingredient_name: str, api_key: str | None) -> dict | None:
    """openFDA Drug Labeling API 호출. 결과 없으면 None 반환."""
    url = _build_label_url(ingredient_name, api_key)

    def _call():
        resp = get_session().get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    try:
        data = api_call_with_retry("openfda", _call)
        if data is None:
            return None
        results = data.get("results")
        if not results:
            return None
        return results[0]
    except Exception as e:
        logger.warning("FDA label 조회 실패 [%s]: %s", ingredient_name[:40], e)
        return None


def fetch_faers(ingredient_name: str, api_key: str | None) -> list[dict]:
    """FAERS 부작용 빈도 상위 N건 반환. [{"term": ..., "count": ...}, ...]"""
    url = _build_faers_url(ingredient_name, api_key)

    def _call():
        resp = get_session().get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    try:
        data = api_call_with_retry("openfda", _call)
        if data is None:
            return []
        return data.get("results", [])
    except Exception as e:
        logger.warning("FAERS 조회 실패 [%s]: %s", ingredient_name[:40], e)
        return []


# ---------------------------------------------------------------------------
# DeepL 번역
# ---------------------------------------------------------------------------

def translate_to_korean(text: str, api_key: str) -> str | None:
    """DeepL API를 사용해 영문 텍스트를 한국어로 번역한다."""
    if not text or not api_key:
        return None
    # 길이 제한
    truncated = text[:MAX_TRANSLATE_LEN]
    try:
        resp = requests.post(
            DEEPL_BASE,
            data={
                "auth_key": api_key,
                "text": truncated,
                "source_lang": "EN",
                "target_lang": "KO",
            },
            timeout=30,
        )
        resp.raise_for_status()
        translations = resp.json().get("translations", [])
        if translations:
            return translations[0].get("text")
    except Exception as e:
        logger.warning("DeepL 번역 실패: %s", e)
    return None


# ---------------------------------------------------------------------------
# 레코드 생성
# ---------------------------------------------------------------------------

def _extract_text(label_result: dict, field: str) -> str | None:
    """FDA label 결과에서 필드 텍스트를 추출한다. 리스트이면 첫 번째 값."""
    val = label_result.get(field)
    if not val:
        return None
    if isinstance(val, list):
        val = val[0]
    if isinstance(val, str) and val.strip():
        return val.strip()[:MAX_DESC_LEN]
    return None


def build_label_records(
    code: str,
    label_result: dict,
    deepl_key: str | None,
) -> list[dict]:
    """FDA label 결과에서 edb_safety 레코드 목록을 생성한다."""
    records = []
    for field_name, info_type, severity in LABEL_SECTIONS:
        text = _extract_text(label_result, field_name)
        if not text:
            continue

        ko_text = None
        if deepl_key:
            ko_text = translate_to_korean(text, deepl_key)

        rec = {
            "심평원성분코드": code,
            "info_type": info_type,
            "description": text,
            "severity": severity,
            "related_ingredient_code": None,
            "evidence_level": "regulatory",
            "source": "fda_label",
            "source_id": label_result.get("id"),
            "validation_status": "auto_validated",
        }
        if ko_text:
            rec["description_ko"] = ko_text
        records.append(rec)

    return records


def build_faers_records(
    code: str,
    faers_results: list[dict],
    deepl_key: str | None,
) -> list[dict]:
    """FAERS 결과에서 edb_safety 레코드 목록을 생성한다."""
    records = []
    for item in faers_results[:FAERS_TOP_N]:
        term = item.get("term", "").strip()
        count = item.get("count", 0)
        if not term:
            continue

        description = f"{term} (보고건수: {count}건)"
        ko_text = None
        if deepl_key:
            ko_text = translate_to_korean(term, deepl_key)
            if ko_text:
                description_ko = f"{ko_text} (보고건수: {count}건)"
            else:
                description_ko = None
        else:
            description_ko = None

        rec = {
            "심평원성분코드": code,
            "info_type": INFO_TYPE_ADVERSE_EFFECT,
            "description": description,
            "severity": SEV_MILD,
            "related_ingredient_code": None,
            "evidence_level": "observational",
            "source": "faers",
            "source_id": None,
            "validation_status": "auto_validated",
        }
        if description_ko:
            rec["description_ko"] = description_ko
        records.append(rec)

    return records


# ---------------------------------------------------------------------------
# (base, route) 중복 체크 / 캐시
# ---------------------------------------------------------------------------

def get_codes_for_base_route(conn, base: str, route: str) -> list[str]:
    """동일 (base, route) 조합의 심평원성분코드 목록 반환."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT "심평원성분코드" FROM "터울주성분"
            WHERE SUBSTRING("심평원성분코드", 1, 4) = %s
              AND SUBSTRING("심평원성분코드", 7, 1) = %s
              AND "IsDeleted" = FALSE
        """, (base, route))
        return [row[0] for row in cur.fetchall()]


def existing_fda_count(conn, code: str) -> int:
    """해당 코드에 이미 저장된 FDA 레코드 수 반환."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM edb_safety
            WHERE "심평원성분코드" = %s
              AND source IN ('fda_label', 'faers')
        """, (code,))
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# 단일 (base, route) 처리 — 핵심 로직
# ---------------------------------------------------------------------------

def process_base_route(
    conn,
    base: str,
    route: str,
    ingredient_name: str,
    api_key: str | None,
    deepl_key: str | None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """(base, route) 조합에 대해 FDA 데이터를 수집하고 저장한다.

    Returns:
        (label_records_inserted, faers_records_inserted)
    """
    # 동일 (base, route) 코드 목록
    all_codes = get_codes_for_base_route(conn, base, route)
    if not all_codes:
        logger.debug("(base=%s, route=%s) 코드 없음", base, route)
        return 0, 0

    clean_name = preprocess_ingredient_name(ingredient_name)
    if not clean_name:
        logger.warning("성분명 전처리 결과 비어있음: %s", ingredient_name[:40])
        return 0, 0

    logger.debug("FDA 조회: '%s' (base=%s, route=%s, 코드%d개)",
                 clean_name[:40], base, route, len(all_codes))

    # FDA Label 수집
    label_result = fetch_label(clean_name, api_key)
    label_count = 0

    if label_result:
        # 첫 번째 코드로 레코드 생성 후 나머지 코드에 복제
        template_records = build_label_records(
            all_codes[0], label_result, deepl_key
        )

        for code in all_codes:
            code_records = [
                {**r, "심평원성분코드": code} for r in template_records
            ]
            if not code_records:
                continue
            if dry_run:
                logger.info(
                    "    [DRY-RUN] fda_label %d건 → %s",
                    len(code_records), code,
                )
                label_count += len(code_records)
            else:
                # description_ko 컬럼 없는 경우를 고려해 존재 여부 확인 후 제거
                safe_records = _strip_missing_columns(
                    conn, "edb_safety", code_records
                )
                inserted = batch_insert(conn, "edb_safety", safe_records)
                label_count += inserted
    else:
        logger.debug("FDA label 결과 없음: %s", clean_name[:40])

    # FAERS 수집
    faers_results = fetch_faers(clean_name, api_key)
    faers_count = 0

    if faers_results:
        template_records = build_faers_records(
            all_codes[0], faers_results, deepl_key
        )

        for code in all_codes:
            code_records = [
                {**r, "심평원성분코드": code} for r in template_records
            ]
            if not code_records:
                continue
            if dry_run:
                logger.info(
                    "    [DRY-RUN] faers %d건 → %s",
                    len(code_records), code,
                )
                faers_count += len(code_records)
            else:
                safe_records = _strip_missing_columns(
                    conn, "edb_safety", code_records
                )
                inserted = batch_insert(conn, "edb_safety", safe_records)
                faers_count += inserted
    else:
        logger.debug("FAERS 결과 없음: %s", clean_name[:40])

    return label_count, faers_count


# ---------------------------------------------------------------------------
# description_ko 컬럼 존재 여부 캐시
# ---------------------------------------------------------------------------

_column_cache: dict[str, set[str]] = {}


def _get_table_columns(conn, table: str) -> set[str]:
    if table in _column_cache:
        return _column_cache[table]
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = %s AND table_schema = 'public'
        """, (table,))
        cols = {row[0] for row in cur.fetchall()}
    _column_cache[table] = cols
    return cols


def _strip_missing_columns(
    conn, table: str, records: list[dict]
) -> list[dict]:
    """테이블에 없는 컬럼(description_ko 등)을 레코드에서 제거한다."""
    if not records:
        return records
    existing_cols = _get_table_columns(conn, table)
    extra_keys = set(records[0].keys()) - existing_cols
    if not extra_keys:
        return records
    logger.debug("컬럼 없음 — 제거: %s", extra_keys)
    return [
        {k: v for k, v in r.items() if k not in extra_keys}
        for r in records
    ]


# ---------------------------------------------------------------------------
# 단건 코드 처리
# ---------------------------------------------------------------------------

def process_single_code(
    conn,
    code_info: dict,
    api_key: str | None,
    deepl_key: str | None,
    dry_run: bool = False,
) -> bool:
    """단일 심평원성분코드에 대해 FDA enrichment를 수행한다.

    Returns:
        True=성공, False=실패
    """
    code = code_info["심평원성분코드"]
    ingredient_name = code_info.get("성분명") or code_info.get("성분명한글") or ""

    parsed = parse_code(code)
    if not parsed:
        logger.error("코드 파싱 실패: %s", code)
        update_status(conn, code, "fda", success=False, error="코드 파싱 실패")
        return False

    if not ingredient_name:
        logger.warning("성분명 없음: %s", code)
        update_status(conn, code, "fda", success=False, error="성분명 없음")
        return False

    try:
        label_cnt, faers_cnt = process_base_route(
            conn,
            parsed.base,
            parsed.route,
            ingredient_name,
            api_key,
            deepl_key,
            dry_run=dry_run,
        )

        if not dry_run:
            update_status(conn, code, "fda", success=True)

        logger.info(
            "  %s → label: %d건, faers: %d건", code, label_cnt, faers_cnt
        )
        return True

    except Exception as e:
        logger.error("FDA enrichment 실패 [%s]: %s", code, e)
        if not dry_run:
            update_status(conn, code, "fda", success=False, error=str(e))
        return False


# ---------------------------------------------------------------------------
# 병렬 워커 — 스레드별 DB 커넥션 사용
# ---------------------------------------------------------------------------

def _process_base_route_worker(
    base: str,
    route: str,
    ingredient_name: str,
    sibling_codes: list[str],
    api_key: str | None,
    deepl_key: str | None,
    db_name: str | None,
    dry_run: bool = False,
) -> tuple[bool, str | None]:
    """병렬 워커용 (base, route) 처리. 자체 DB 커넥션을 사용한다.

    Returns:
        (success, error_message)
    """
    conn = None
    try:
        conn = get_thread_connection(db_name)

        label_cnt, faers_cnt = process_base_route(
            conn,
            base,
            route,
            ingredient_name,
            api_key,
            deepl_key,
            dry_run=dry_run,
        )

        if not dry_run:
            for c in sibling_codes:
                update_status(conn, c, "fda", success=True)

        logger.debug(
            "  (base=%s, route=%s) label: %d건, faers: %d건",
            base, route, label_cnt, faers_cnt,
        )
        return True, None

    except Exception as e:
        logger.error(
            "  (base=%s, route=%s) 에러: %s", base, route, e,
        )
        if not dry_run and conn:
            for c in sibling_codes:
                update_status(conn, c, "fda", success=False, error=str(e))
        return False, str(e)

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 일괄 처리 — (base, route) 단위 중복 제거
# ---------------------------------------------------------------------------

def run_batch(
    conn,
    codes: list[dict],
    api_key: str | None,
    deepl_key: str | None,
    dry_run: bool = False,
    workers: int = 1,
    db_name: str | None = None,
):
    """(base, route) 단위로 중복 제거 후 FDA enrichment를 수행한다."""
    # (base, route) → 대표 코드 + 성분명 매핑
    base_route_map: dict[tuple[str, str], dict] = {}
    for item in codes:
        code = item["심평원성분코드"]
        parsed = parse_code(code)
        if not parsed:
            continue
        key = (parsed.base, parsed.route)
        if key not in base_route_map:
            base_route_map[key] = item

    unique_pairs = list(base_route_map.values())
    total_unique = len(unique_pairs)
    total_codes = len(codes)

    logger.info(
        "처리 대상: 코드 %d건 → (base,route) 고유 조합 %d건",
        total_codes, total_unique,
    )

    tracker = ProgressTracker(
        total=total_unique, source="openfda", log_interval=20
    )

    # ------------------------------------------------------------------
    # 1단계: 사전 준비 — 실제 처리할 그룹 목록 생성 (메인 커넥션 사용)
    # ------------------------------------------------------------------
    work_items: list[tuple[str, str, str, list[str]]] = []  # (base, route, name, siblings)

    for item in unique_pairs:
        code = item["심평원성분코드"]
        ingredient_name = (
            item.get("성분명") or item.get("성분명한글") or ""
        )
        parsed = parse_code(code)
        if not parsed:
            tracker.update(success=False)
            continue

        sibling_codes = get_codes_for_base_route(
            conn, parsed.base, parsed.route
        )
        already_done = (
            all(existing_fda_count(conn, c) > 0 for c in sibling_codes)
            if not dry_run else False
        )

        if already_done:
            logger.debug(
                "  건너뜀 (이미 처리됨): base=%s route=%s",
                parsed.base, parsed.route,
            )
            if not dry_run:
                for c in sibling_codes:
                    update_status(conn, c, "fda", success=True)
            tracker.update(skipped=True)
            continue

        work_items.append((parsed.base, parsed.route, ingredient_name, sibling_codes))

    # ------------------------------------------------------------------
    # 2단계: 실행 — 순차 또는 병렬
    # ------------------------------------------------------------------
    if workers <= 1:
        # 순차 처리 (기존 동작)
        for base, route, ingredient_name, sibling_codes in work_items:
            try:
                label_cnt, faers_cnt = process_base_route(
                    conn,
                    base,
                    route,
                    ingredient_name,
                    api_key,
                    deepl_key,
                    dry_run=dry_run,
                )

                if not dry_run:
                    for c in sibling_codes:
                        update_status(conn, c, "fda", success=True)

                tracker.update(success=True)
                logger.debug(
                    "  (base=%s, route=%s) label: %d건, faers: %d건",
                    base, route, label_cnt, faers_cnt,
                )

            except Exception as e:
                logger.error(
                    "  (base=%s, route=%s) 에러: %s", base, route, e,
                )
                if not dry_run:
                    for c in sibling_codes:
                        update_status(conn, c, "fda", success=False, error=str(e))
                tracker.update(success=False)
    else:
        # 병렬 처리
        logger.info("병렬 모드: workers=%d, 작업=%d건", workers, len(work_items))
        futures = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for base, route, ingredient_name, sibling_codes in work_items:
                fut = executor.submit(
                    _process_base_route_worker,
                    base, route, ingredient_name, sibling_codes,
                    api_key, deepl_key, db_name, dry_run,
                )
                futures[fut] = (base, route)

            for fut in as_completed(futures):
                base, route = futures[fut]
                try:
                    success, err = fut.result()
                    _safe_tracker_update(tracker, success=success)
                except Exception as e:
                    logger.error(
                        "  워커 예외 (base=%s, route=%s): %s", base, route, e,
                    )
                    _safe_tracker_update(tracker, success=False)

    summary = tracker.summary()
    logger.info(
        "FDA enrichment 완료: %d건 처리"
        " (성공: %d, 실패: %d, 건너뜀: %d) — %.1f초",
        summary["processed"], summary["success"],
        summary["failed"], summary["skipped"],
        summary["elapsed_seconds"],
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 1-B: openFDA Drug Labeling + FAERS enrichment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python enrich_fda.py                      # 전체 미완료 처리
  python enrich_fda.py --code 101301AIJ     # 단건
  python enrich_fda.py --limit 100          # 100건
  python enrich_fda.py --dev                # dev DB
  python enrich_fda.py --dry-run            # 테스트 (DB 저장 안 함)
        """,
    )
    parser.add_argument("--code", help="특정 심평원성분코드 1건 처리")
    parser.add_argument("--limit", type=int, default=0, help="처리 건수 제한 (0=전체)")
    parser.add_argument("--dev", action="store_true", help="dev DB 사용")
    parser.add_argument("--dry-run", action="store_true",
                        help="API 호출 및 처리 내용 출력, DB 저장 안 함")
    parser.add_argument("--workers", type=int, default=1,
                        help="병렬 워커 수 (기본 1=순차처리)")
    args = parser.parse_args()

    api_key = os.getenv("OPENFDA_API_KEY")  # 없어도 동작 (rate limit 낮아짐)
    deepl_key = os.getenv("DEEPL_API")

    if api_key:
        logger.info("OPENFDA_API_KEY: 설정됨 (높은 rate limit)")
    else:
        logger.info("OPENFDA_API_KEY: 미설정 (기본 rate limit 적용)")

    if deepl_key:
        logger.info("DEEPL_API: 설정됨 (영→한 번역 활성화)")
    else:
        logger.info("DEEPL_API: 미설정 (번역 비활성화)")

    if args.dry_run:
        logger.info("=== DRY-RUN 모드: DB 저장 없음 ===")

    db_name = os.getenv("DEV_DATABASE_NAME") if args.dev else None
    conn = get_connection(db_name)

    try:
        if args.code:
            # 단건 처리
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT "심평원성분코드", "성분명", "성분명한글"
                    FROM "터울주성분"
                    WHERE "심평원성분코드" = %s AND "IsDeleted" = FALSE
                """, (args.code,))
                row = cur.fetchone()

            if not row:
                logger.error("코드를 찾을 수 없음: %s", args.code)
                sys.exit(1)

            code_info = {
                "심평원성분코드": row[0],
                "성분명": row[1],
                "성분명한글": row[2],
            }
            success = process_single_code(
                conn, code_info, api_key, deepl_key, dry_run=args.dry_run
            )
            sys.exit(0 if success else 1)

        else:
            # 일괄 처리
            pending = get_pending_codes(conn, step="fda", limit=args.limit)

            if not pending:
                logger.info("처리할 미완료 코드가 없습니다.")
                return

            logger.info("미완료 FDA enrichment 코드: %d건", len(pending))
            run_batch(conn, pending, api_key, deepl_key,
                      dry_run=args.dry_run, workers=args.workers,
                      db_name=db_name)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
