"""
Phase 1-B: ClinicalTrials.gov 임상시험 데이터 수집 (Step 7)

Flow:
  1. edb_enrichment_status에서 trials_fetched=FALSE인 코드 조회
  2. 터울주성분 성분명으로 ClinicalTrials.gov API v2 검색
  3. 상위 5건 임상시험 데이터를 edb_clinical_trial에 저장
  4. edb_enrichment_status.trials_fetched = TRUE 업데이트

최적화:
  - 동일 주성분(1-4자리)은 임상시험 데이터를 공유하므로
    첫 번째 코드 처리 후 나머지는 DB에서 복사

Usage:
    python enrich_trials.py                    # 전체 미완료
    python enrich_trials.py --code 101301AIJ   # 단건
    python enrich_trials.py --limit 100        # 100건
    python enrich_trials.py --dev              # dev DB
    python enrich_trials.py --dry-run          # 테스트 (DB 쓰기 없음)
"""

import argparse
import logging
import os
import sys

import requests

from concurrent.futures import ThreadPoolExecutor, as_completed

from common import get_connection
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
# 상수
# ---------------------------------------------------------------------------

SOURCE = "clinicaltrials"
TABLE = "edb_clinical_trial"
STEP = "trials"

CLINICALTRIALS_API_URL = "https://clinicaltrials.gov/api/v2/studies"
PAGE_SIZE = 5


# ---------------------------------------------------------------------------
# ClinicalTrials.gov API 호출
# ---------------------------------------------------------------------------

def _fetch_studies(ingredient_name: str) -> list[dict]:
    """ClinicalTrials.gov API v2에서 성분명으로 임상시험을 검색한다.

    Args:
        ingredient_name: 검색할 성분명 (영문)

    Returns:
        studies 목록 (raw API 응답의 studies 배열)
    """
    params = {
        "query.intr": ingredient_name,
        "pageSize": PAGE_SIZE,
        "sort": "LastUpdatePostDate:desc",
        "format": "json",
    }

    def _do_request():
        resp = requests.get(CLINICALTRIALS_API_URL, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    data = api_call_with_retry(SOURCE, _do_request)
    return data.get("studies", [])


def _extract_trial_record(code: str, study: dict) -> dict | None:
    """단일 study 응답에서 edb_clinical_trial INSERT용 딕셔너리를 추출한다.

    Args:
        code: 심평원성분코드
        study: ClinicalTrials.gov API v2의 단일 study 객체

    Returns:
        레코드 딕셔너리, 또는 nct_id 없으면 None
    """
    protocol = study.get("protocolSection", {})

    # identificationModule
    id_mod = protocol.get("identificationModule", {})
    nct_id = id_mod.get("nctId", "").strip()
    if not nct_id:
        return None

    title = (
        id_mod.get("officialTitle")
        or id_mod.get("briefTitle")
        or ""
    ).strip() or None

    # designModule
    design_mod = protocol.get("designModule", {})
    phases_raw = design_mod.get("phases", [])
    phase = ", ".join(phases_raw) if phases_raw else None

    enrollment_info = design_mod.get("enrollmentInfo", {})
    enrollment = enrollment_info.get("count")
    if enrollment is not None:
        try:
            enrollment = int(enrollment)
        except (ValueError, TypeError):
            enrollment = None

    # statusModule
    status_mod = protocol.get("statusModule", {})
    status = status_mod.get("overallStatus") or None

    start_date_struct = status_mod.get("startDateStruct", {})
    start_date = start_date_struct.get("date") or None

    completion_mod = protocol.get("completionDateStruct", {})
    # completionModule 하위에 completionDateStruct가 있는 경우
    completion_module = protocol.get("completionModule", {})
    completion_date_struct = completion_module.get("completionDateStruct", {})
    completion_date = completion_date_struct.get("date") or None

    # conditionsModule
    conditions_mod = protocol.get("conditionsModule", {})
    conditions_list = conditions_mod.get("conditions", [])
    condition_name = ", ".join(conditions_list) if conditions_list else None

    # sponsorCollaboratorsModule
    sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
    lead_sponsor = sponsor_mod.get("leadSponsor", {})
    sponsor = lead_sponsor.get("name") or None

    return {
        "심평원성분코드": code,
        "nct_id": nct_id,
        "title": title,
        "phase": phase,
        "status": status,
        "condition_name": condition_name,
        "enrollment": enrollment,
        "start_date": start_date,
        "completion_date": completion_date,
        "sponsor": sponsor,
        "source": SOURCE,
    }


# ---------------------------------------------------------------------------
# 성분 기반 수집 (최적화: 동일 주성분 공유)
# ---------------------------------------------------------------------------

def _get_base_code(code: str) -> str:
    """심평원성분코드의 주성분 1-4자리를 반환한다."""
    return code[:4] if len(code) >= 4 else code


def _copy_trials_from_sibling(conn, code: str, base: str, dry_run: bool = False) -> int:
    """동일 주성분(1-4자리)의 기존 임상시험 데이터를 현재 코드로 복사한다.

    Args:
        conn: psycopg2 connection
        code: 복사 대상 심평원성분코드
        base: 주성분 1-4자리
        dry_run: True면 DB 쓰기 생략

    Returns:
        복사된 건수
    """
    if dry_run:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) FROM {TABLE}
                WHERE "심평원성분코드" LIKE %s
                  AND "심평원성분코드" != %s
                """,
                (base + "%", code),
            )
            count = cur.fetchone()[0]
        logger.info("  [dry-run] 복사 예정: %d건 (from base=%s)", count, base)
        return count

    with conn.cursor() as cur:
        # 컬럼 목록 조회 (trial_id PK 제외)
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = %s AND column_name != 'trial_id'
            ORDER BY ordinal_position
            """,
            (TABLE,),
        )
        columns = [row[0] for row in cur.fetchall()]

        if "심평원성분코드" not in columns:
            logger.warning("  %s에 심평원성분코드 컬럼 없음", TABLE)
            return 0

        cols_insert = ", ".join(f'"{c}"' for c in columns)
        cols_select = ", ".join(
            f"'{code}'" if c == "심평원성분코드" else f'"{c}"'
            for c in columns
        )

        cur.execute(
            f"""
            INSERT INTO {TABLE} ({cols_insert})
            SELECT {cols_select}
            FROM {TABLE}
            WHERE "심평원성분코드" LIKE %s
              AND "심평원성분코드" != %s
            ON CONFLICT DO NOTHING
            """,
            (base + "%", code),
        )
        copied = cur.rowcount

    conn.commit()
    logger.info("  임상시험 %d건 복사 완료 (base=%s → %s)", copied, base, code)
    return copied


def _has_trials_for_base(conn, base: str, current_code: str) -> bool:
    """동일 주성분(1-4자리)에 이미 수집된 임상시험이 있는지 확인한다."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT 1 FROM {TABLE}
            WHERE "심평원성분코드" LIKE %s
              AND "심평원성분코드" != %s
            LIMIT 1
            """,
            (base + "%", current_code),
        )
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# 단일 코드 enrichment
# ---------------------------------------------------------------------------

def enrich_single(conn, code_info: dict, dry_run: bool = False) -> bool:
    """단일 성분코드에 대한 임상시험 enrichment를 수행한다.

    Args:
        conn: psycopg2 connection
        code_info: {"심평원성분코드": ..., "성분명": ..., "성분명한글": ...}
        dry_run: True면 DB 쓰기 생략

    Returns:
        성공 여부
    """
    code = code_info["심평원성분코드"]
    name_en = code_info.get("성분명", "") or ""
    name_kr = code_info.get("성분명한글", "") or ""
    base = _get_base_code(code)

    display_name = name_en[:50] if name_en else name_kr[:50]
    logger.info("처리: %s (%s)", code, display_name)

    # 1. 동일 주성분에 이미 수집된 데이터가 있으면 복사
    if _has_trials_for_base(conn, base, code):
        logger.info("  동일 주성분(%s) 데이터 존재 → 복사", base)
        copied = _copy_trials_from_sibling(conn, code, base, dry_run=dry_run)
        if not dry_run:
            update_status(conn, code, STEP, success=True)
        logger.info("  완료 (복사): %s — %d건", code, copied)
        return True

    # 2. 성분명 전처리
    search_name = preprocess_ingredient_name(name_en) if name_en else ""
    if not search_name:
        logger.warning("  검색 가능한 성분명 없음 (코드: %s, 한글: %s)", code, name_kr[:30])
        if not dry_run:
            update_status(conn, code, STEP, success=False, error="검색 가능한 성분명 없음")
        return False

    # 3. ClinicalTrials.gov API 호출
    try:
        studies = _fetch_studies(search_name)
    except Exception as e:
        logger.error("  API 호출 실패 [%s]: %s", code, e)
        if not dry_run:
            update_status(conn, code, STEP, success=False, error=str(e)[:500])
        return False

    if not studies:
        logger.info("  검색 결과 없음: %s", search_name)
        if not dry_run:
            update_status(conn, code, STEP, success=True)
        return True

    # 4. 레코드 추출
    records = []
    for study in studies:
        record = _extract_trial_record(code, study)
        if record:
            records.append(record)

    logger.info("  %d건 추출 (검색어: %s)", len(records), search_name)

    if dry_run:
        for r in records:
            logger.info(
                "  [dry-run] nct_id=%s, phase=%s, status=%s",
                r.get("nct_id"), r.get("phase"), r.get("status"),
            )
        return True

    # 5. DB 저장
    if records:
        inserted = batch_insert(
            conn, TABLE, records,
            conflict_action="(nct_id, \"심평원성분코드\") DO NOTHING",
        )
        logger.info("  저장: %d건 INSERT", inserted)

    # 6. 상태 업데이트
    update_status(conn, code, STEP, success=True)
    logger.info("  완료: %s", code)
    return True


# ---------------------------------------------------------------------------
# 단건 조회
# ---------------------------------------------------------------------------

def fetch_single_code_info(conn, code: str) -> dict | None:
    """심평원성분코드로 터울주성분 정보를 조회한다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT "심평원성분코드", "성분명", "성분명한글"
            FROM "터울주성분"
            WHERE "심평원성분코드" = %s AND "IsDeleted" = FALSE
            """,
            (code,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "심평원성분코드": row[0],
        "성분명": row[1],
        "성분명한글": row[2],
    }


# ---------------------------------------------------------------------------
# 병렬 처리 워커
# ---------------------------------------------------------------------------

def _enrich_single_worker(code_info: dict, db_name: str | None, dry_run: bool) -> tuple[str, bool]:
    """워커 스레드에서 단일 코드를 처리한다.

    각 워커가 독립 DB 커넥션을 생성/해제한다.

    Args:
        code_info: {"심평원성분코드": ..., "성분명": ..., "성분명한글": ...}
        db_name: DB 이름 (None이면 기본 DB)
        dry_run: True면 DB 쓰기 생략

    Returns:
        (심평원성분코드, 성공 여부)
    """
    code = code_info.get("심평원성분코드", "?")
    conn = get_thread_connection(db_name)
    try:
        success = enrich_single(conn, code_info, dry_run=dry_run)
        return (code, success)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ClinicalTrials.gov 임상시험 데이터 수집 (Phase 1-B, Step 7)"
    )
    parser.add_argument("--code", help="특정 심평원성분코드 1건 처리")
    parser.add_argument("--limit", type=int, default=0, help="처리 건수 제한 (0=전체)")
    parser.add_argument("--dev", action="store_true", help="dev DB 사용")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="DB 쓰기 없이 테스트 실행")
    parser.add_argument("--workers", type=int, default=1,
                        help="병렬 워커 수 (기본 1=순차처리)")
    args = parser.parse_args()

    db_name = os.getenv("DEV_DATABASE_NAME") if args.dev else None
    conn = get_connection(db_name)

    try:
        if args.code:
            # 단건 처리
            code_info = fetch_single_code_info(conn, args.code)
            if not code_info:
                logger.error("코드를 찾을 수 없음: %s", args.code)
                sys.exit(1)
            success = enrich_single(conn, code_info, dry_run=args.dry_run)
            sys.exit(0 if success else 1)

        # 전체 미완료 처리
        pending = get_pending_codes(conn, STEP, limit=args.limit)
        total = len(pending)

        if total == 0:
            logger.info("처리할 코드 없음 (trials_fetched=FALSE인 코드 0건)")
            return

        logger.info(
            "임상시험 수집 시작: %d건%s%s",
            total,
            f" (limit={args.limit})" if args.limit > 0 else "",
            " [dry-run]" if args.dry_run else "",
        )

        tracker = ProgressTracker(total=total, source=SOURCE)

        if args.workers > 1:
            # 병렬 처리
            logger.info("병렬 모드: %d 워커", args.workers)
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(_enrich_single_worker, ci, db_name, args.dry_run): ci
                    for ci in pending
                }
                for future in as_completed(futures):
                    ci = futures[future]
                    code = ci.get("심평원성분코드", "?")
                    try:
                        _, success = future.result()
                        _safe_tracker_update(tracker, success=success)
                    except Exception as e:
                        logger.error("처리 중 예외 [%s]: %s", code, e)
                        _safe_tracker_update(tracker, success=False)
        else:
            # 순차 처리 (기존 동작)
            for code_info in pending:
                try:
                    success = enrich_single(conn, code_info, dry_run=args.dry_run)
                    tracker.update(success=success)
                except Exception as e:
                    code = code_info.get("심평원성분코드", "?")
                    logger.error("처리 중 예외 [%s]: %s", code, e)
                    if not args.dry_run:
                        try:
                            update_status(conn, code, STEP, success=False, error=str(e)[:500])
                        except Exception:
                            pass
                    tracker.update(success=False)

        summary = tracker.summary()
        logger.info(
            "완료 — 총 %d건, 성공: %d, 실패: %d, 건너뜀: %d, 소요: %.1f초",
            summary["processed"],
            summary["success"],
            summary["failed"],
            summary["skipped"],
            summary["elapsed_seconds"],
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
