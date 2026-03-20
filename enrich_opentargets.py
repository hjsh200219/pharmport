"""
Phase 1-B: Open Targets Platform 질병-타겟 enrichment

약물(ChEMBL ID) → Open Targets GraphQL API → edb_drug_disease 저장

Flow:
  1. edb_ingredient_xref에서 chembl_mapped=TRUE인 ChEMBL ID 조회
  2. Open Targets GraphQL: linkedDiseases 쿼리
  3. association_score >= 0.3 필터 (Layer 1 enforced)
  4. edb_drug_disease INSERT
  5. edb_enrichment_status.disease_fetched = TRUE 업데이트

최적화:
  - 동일 base 코드(1-4자리)는 같은 ChEMBL ID → 한 번 API 호출 후 공유
  - 배치 그룹: base 코드 단위로 묶어서 처리

Usage:
    python enrich_opentargets.py                  # 전체 미완료
    python enrich_opentargets.py --code 101301AIJ # 단건
    python enrich_opentargets.py --limit 100      # 100건
    python enrich_opentargets.py --dev            # dev DB
    python enrich_opentargets.py --dry-run        # 테스트
"""

import argparse
import logging
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from common import get_connection
from enrich_base import (
    ProgressTracker,
    _safe_tracker_update,
    api_call_with_retry,
    batch_insert,
    get_pending_codes,
    get_thread_connection,
    update_status,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPENTARGETS_GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"
SOURCE = "opentargets"
TABLE = "edb_drug_disease"
MIN_ASSOCIATION_SCORE = 0.3

# clinical_phase는 Open Targets의 maximumClinicalTrialPhase 값을 사용
# linkedDiseases 자체에 score 필드가 없으므로 phase 기반으로 score 산출
# phase 4 → 1.0, phase 3 → 0.75, phase 2 → 0.5, phase 1 → 0.35, None → 0.3
PHASE_TO_SCORE = {4: 1.0, 3: 0.75, 2: 0.5, 1: 0.35}
DEFAULT_SCORE = 0.3

LINKED_DISEASES_QUERY = """
query DrugDiseases($chemblId: String!) {
  drug(chemblId: $chemblId) {
    id
    name
    linkedDiseases {
      rows {
        disease {
          id
          name
          therapeuticAreas {
            id
            name
          }
        }
        drug {
          maximumClinicalTrialPhase
        }
      }
    }
  }
}
"""


# ---------------------------------------------------------------------------
# Open Targets API
# ---------------------------------------------------------------------------

def _graphql_post(query: str, variables: dict) -> dict:
    """GraphQL POST 요청을 수행하고 응답 JSON을 반환한다."""
    response = requests.post(
        OPENTARGETS_GRAPHQL_URL,
        json={"query": query, "variables": variables},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    # GraphQL 오류 체크
    if "errors" in data:
        err_msgs = [e.get("message", str(e)) for e in data["errors"]]
        raise ValueError(f"GraphQL 오류: {'; '.join(err_msgs)}")

    return data


def fetch_linked_diseases(chembl_id: str) -> list[dict]:
    """단일 ChEMBL ID에 대한 linkedDiseases를 조회하고 파싱된 row 목록을 반환한다.

    Returns:
        [{"disease_id": ..., "disease_name": ..., "therapeutic_area": ...,
          "clinical_phase": ..., "association_score": ...}, ...]
    """
    def _call():
        return _graphql_post(LINKED_DISEASES_QUERY, {"chemblId": chembl_id})

    data = api_call_with_retry(SOURCE, _call)

    drug_data = data.get("data", {}).get("drug")
    if not drug_data:
        logger.debug("[%s] drug 데이터 없음 (ChEMBL ID: %s)", SOURCE, chembl_id)
        return []

    linked = drug_data.get("linkedDiseases")
    if not linked:
        return []

    rows = linked.get("rows") or []
    results = []

    for row in rows:
        disease = row.get("disease") or {}
        drug_info = row.get("drug") or {}

        disease_id = disease.get("id", "")
        disease_name = disease.get("name", "")
        if not disease_id or not disease_name:
            continue

        # therapeuticAreas: 첫 번째 항목의 name 사용
        therapeutic_areas = disease.get("therapeuticAreas") or []
        therapeutic_area = therapeutic_areas[0]["name"] if therapeutic_areas else None

        clinical_phase = drug_info.get("maximumClinicalTrialPhase")
        # None이면 int 변환 불필요
        if clinical_phase is not None:
            try:
                clinical_phase = int(clinical_phase)
            except (TypeError, ValueError):
                clinical_phase = None

        association_score = PHASE_TO_SCORE.get(clinical_phase, DEFAULT_SCORE)

        results.append({
            "disease_id": disease_id,
            "disease_name": disease_name,
            "therapeutic_area": therapeutic_area,
            "clinical_phase": clinical_phase,
            "association_score": association_score,
        })

    return results


# ---------------------------------------------------------------------------
# ChEMBL ID 조회
# ---------------------------------------------------------------------------

def get_chembl_id(conn, code: str) -> str | None:
    """edb_ingredient_xref에서 심평원성분코드의 ChEMBL ID를 반환한다.

    chembl_mapped=TRUE인 코드만 대상으로 한다.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT x.source_id
            FROM edb_ingredient_xref x
            JOIN edb_enrichment_status es
                ON x."심평원성분코드" = es."심평원성분코드"
            WHERE x."심평원성분코드" = %s
              AND x.source = 'chembl'
              AND es.chembl_mapped = TRUE
            ORDER BY x.confidence DESC
            LIMIT 1
        """, (code,))
        row = cur.fetchone()
        return row[0] if row else None


def get_codes_with_chembl(conn, codes: list[dict]) -> list[dict]:
    """codes 목록 중 ChEMBL ID가 있는 것만 chembl_id 필드를 붙여 반환한다."""
    result = []
    for item in codes:
        code = item["심평원성분코드"]
        chembl_id = get_chembl_id(conn, code)
        if chembl_id:
            result.append({**item, "chembl_id": chembl_id})
        else:
            logger.debug("[skip] ChEMBL ID 없음: %s", code)
    return result


# ---------------------------------------------------------------------------
# Base 코드 기반 배치 그룹핑 (1-4자리 공유)
# ---------------------------------------------------------------------------

def group_by_base(codes_with_chembl: list[dict]) -> dict[str, list[dict]]:
    """ChEMBL ID 기준으로 코드를 그룹화한다.

    동일 ChEMBL ID를 가진 코드들은 API 호출 한 번으로 처리한다.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in codes_with_chembl:
        groups[item["chembl_id"]].append(item)
    return dict(groups)


# ---------------------------------------------------------------------------
# 저장
# ---------------------------------------------------------------------------

def build_records(code: str, chembl_id: str, disease_rows: list[dict]) -> list[dict]:
    """disease_rows를 edb_drug_disease INSERT용 딕셔너리 목록으로 변환한다.

    association_score < MIN_ASSOCIATION_SCORE인 레코드는 여기서 사전 필터링한다.
    (Layer 1 검증이 최종 보루이지만 불필요한 레코드를 미리 제거)
    """
    records = []
    for row in disease_rows:
        score = row.get("association_score", 0.0)
        if score < MIN_ASSOCIATION_SCORE:
            continue
        records.append({
            "심평원성분코드": code,
            "chembl_id": chembl_id,
            "disease_id": row["disease_id"],
            "disease_name": row["disease_name"],
            "therapeutic_area": row.get("therapeutic_area"),
            "clinical_phase": row.get("clinical_phase"),
            "association_score": score,
            "source": SOURCE,
        })
    return records


# ---------------------------------------------------------------------------
# 단건 처리
# ---------------------------------------------------------------------------

def process_one(conn, code: str, chembl_id: str, disease_rows: list[dict],
                dry_run: bool = False) -> bool:
    """한 성분코드에 대한 질병 데이터를 저장하고 상태를 업데이트한다.

    Returns:
        True: 성공 (질병 0건 포함), False: 오류
    """
    records = build_records(code, chembl_id, disease_rows)
    filtered_out = len(disease_rows) - len(records)

    if dry_run:
        logger.info(
            "[dry-run] %s (ChEMBL: %s) — 질병 %d건 저장 예정, %d건 필터 (score < %.1f)",
            code, chembl_id, len(records), filtered_out, MIN_ASSOCIATION_SCORE,
        )
        for r in records[:3]:
            logger.info(
                "  disease: %s (%s) phase=%s score=%.2f",
                r["disease_name"], r["disease_id"],
                r.get("clinical_phase"), r["association_score"],
            )
        if len(records) > 3:
            logger.info("  ... +%d건", len(records) - 3)
        return True

    try:
        inserted = batch_insert(
            conn, TABLE, records,
            conflict_action='("심평원성분코드", disease_id) DO NOTHING',
        )
        update_status(conn, code, "disease", success=True)
        logger.debug(
            "[%s] %s — 질병 %d건 INSERT, %d건 필터",
            SOURCE, code, inserted, filtered_out,
        )
        return True
    except Exception as e:
        logger.error("[%s] %s 저장 실패: %s", SOURCE, code, e)
        update_status(conn, code, "disease", success=False, error=str(e))
        return False


# ---------------------------------------------------------------------------
# 메인 처리 루프
# ---------------------------------------------------------------------------

def _process_chembl_group(chembl_id: str, code_items: list[dict],
                          db_name: str | None, dry_run: bool) -> tuple[int, int]:
    """워커 스레드에서 단일 ChEMBL ID 그룹을 처리한다.

    Returns:
        (processed_count, success_count)
    """
    conn = get_thread_connection(db_name)
    processed = 0
    success_count = 0
    try:
        # API 호출: ChEMBL ID당 1회
        try:
            disease_rows = api_call_with_retry(SOURCE, fetch_linked_diseases, chembl_id)
        except Exception as e:
            logger.error("[%s] ChEMBL %s API 호출 실패: %s", SOURCE, chembl_id, e)
            for item in code_items:
                update_status(conn, item["심평원성분코드"], "disease",
                              success=False, error=str(e))
                processed += 1
            return processed, success_count

        logger.debug(
            "[%s] ChEMBL %s → 질병 %d건 (score >= %.1f 적용 전)",
            SOURCE, chembl_id, len(disease_rows), MIN_ASSOCIATION_SCORE,
        )

        for item in code_items:
            code = item["심평원성분코드"]
            ok = process_one(conn, code, chembl_id, disease_rows, dry_run=dry_run)
            processed += 1
            if ok:
                success_count += 1
    finally:
        conn.close()

    return processed, success_count


def run(conn, pending: list[dict], dry_run: bool = False, workers: int = 1,
        db_name: str | None = None):
    """pending 목록 전체에 대한 enrichment를 실행한다."""
    if not pending:
        logger.info("처리할 항목 없음")
        return

    logger.info("ChEMBL ID 조회 중 (%d건)...", len(pending))
    codes_with_chembl = get_codes_with_chembl(conn, pending)
    no_chembl = len(pending) - len(codes_with_chembl)
    if no_chembl > 0:
        logger.info("ChEMBL ID 없어서 건너뜀: %d건", no_chembl)

    if not codes_with_chembl:
        logger.info("ChEMBL ID가 있는 항목 없음 — 종료")
        return

    # ChEMBL ID 기준 그룹화 (API 호출 최소화)
    groups = group_by_base(codes_with_chembl)
    logger.info(
        "처리 대상: %d건 (고유 ChEMBL ID: %d개, workers: %d)",
        len(codes_with_chembl), len(groups), workers,
    )

    tracker = ProgressTracker(total=len(codes_with_chembl), source=SOURCE, log_interval=20)

    if workers > 1:
        # 병렬 처리
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _process_chembl_group, chembl_id, code_items, db_name, dry_run,
                ): chembl_id
                for chembl_id, code_items in groups.items()
            }
            for future in as_completed(futures):
                chembl_id = futures[future]
                try:
                    processed, success_count = future.result()
                    for _ in range(success_count):
                        _safe_tracker_update(tracker, success=True)
                    for _ in range(processed - success_count):
                        _safe_tracker_update(tracker, success=False)
                except Exception as e:
                    logger.error("[%s] ChEMBL %s 워커 오류: %s", SOURCE, chembl_id, e)
    else:
        # 순차 처리 (기존 로직, 전달받은 conn 사용)
        for chembl_id, code_items in groups.items():
            # API 호출: ChEMBL ID당 1회
            try:
                disease_rows = api_call_with_retry(SOURCE, fetch_linked_diseases, chembl_id)
            except Exception as e:
                logger.error("[%s] ChEMBL %s API 호출 실패: %s", SOURCE, chembl_id, e)
                for item in code_items:
                    update_status(conn, item["심평원성분코드"], "disease",
                                  success=False, error=str(e))
                    tracker.update(success=False)
                continue

            logger.debug(
                "[%s] ChEMBL %s → 질병 %d건 (score >= %.1f 적용 전)",
                SOURCE, chembl_id, len(disease_rows), MIN_ASSOCIATION_SCORE,
            )

            # 같은 ChEMBL ID를 공유하는 코드들에 동일 결과 저장
            for item in code_items:
                code = item["심평원성분코드"]
                success = process_one(conn, code, chembl_id, disease_rows, dry_run=dry_run)
                tracker.update(success=success)

    summary = tracker.summary()
    logger.info(
        "완료 — 처리: %d, 성공: %d, 실패: %d, 경과: %.1f초",
        summary["processed"], summary["success"],
        summary["failed"], summary["elapsed_seconds"],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Open Targets 질병-타겟 enrichment (Phase 1-B, Step 4)"
    )
    parser.add_argument("--code", help="특정 심평원성분코드 1건 처리")
    parser.add_argument("--limit", type=int, default=0, help="처리 건수 제한 (0=전체)")
    parser.add_argument("--dev", action="store_true", help="dev DB 사용")
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 없이 테스트 출력")
    parser.add_argument("--workers", type=int, default=1,
                        help="병렬 워커 수 (기본 1=순차처리)")
    args = parser.parse_args()

    db_name = os.getenv("DEV_DATABASE_NAME") if args.dev else None
    conn = get_connection(db_name)

    try:
        if args.code:
            # 단건 처리
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT es."심평원성분코드", t."성분명", t."성분명한글"
                    FROM edb_enrichment_status es
                    JOIN "터울주성분" t ON es."심평원성분코드" = t."심평원성분코드"
                    WHERE es."심평원성분코드" = %s
                      AND t."IsDeleted" = FALSE
                """, (args.code,))
                row = cur.fetchone()

            if not row:
                logger.error("코드를 찾을 수 없거나 edb_enrichment_status 미등록: %s", args.code)
                sys.exit(1)

            pending = [{
                "심평원성분코드": row[0],
                "성분명": row[1],
                "성분명한글": row[2],
            }]
        else:
            # 전체 미완료 목록
            pending = get_pending_codes(conn, "disease", limit=args.limit)
            logger.info("미완료 disease_fetched: %d건", len(pending))

        run(conn, pending, dry_run=args.dry_run, workers=args.workers, db_name=db_name)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
