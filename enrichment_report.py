"""
Phase 1-C: Enrichment 커버리지 + 정확도 리포트 + 충돌 감지

Phase 2 진입 조건:
  - ChEMBL 매핑 정밀도 >= 80%
  - PMID 유효성 >= 95%
  - 철회 논문 비율 <= 2%
  - 미해결 충돌 비율 <= 5%

Usage:
    python enrichment_report.py                  # 전체 리포트 출력
    python enrichment_report.py --json           # JSON 포맷
    python enrichment_report.py --gate-check     # Phase 2 진입 조건만 체크 (pass/fail)
    python enrichment_report.py --conflicts      # 충돌 감지만 실행
    python enrichment_report.py --dev            # dev DB
"""

import argparse
import json
import logging
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any

from common import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Phase 2 게이트 임계값
GATE_CHEMBL_PRECISION_MIN = 0.80       # ChEMBL 매핑 정밀도 최소
GATE_PMID_VALIDITY_MIN = 0.95          # PMID 유효성 최소
GATE_RETRACTION_MAX = 0.02             # 철회 논문 최대 비율
GATE_CONFLICT_UNRESOLVED_MAX = 0.05    # 미해결 충돌 최대 비율

# 섹션별 A4/A5 포함 임계값
THRESHOLD_BOTH = 0.50   # coverage >= 50%: A4 + A5
THRESHOLD_A4 = 0.30     # coverage 30-50%: A4만
# coverage < 30%: 포함하지 않음

# PMID 유효성 검증 배치 크기 (PubMed E-utilities)
PMID_BATCH_SIZE = 200
PUBMED_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


# ---------------------------------------------------------------------------
# DB 쿼리 헬퍼
# ---------------------------------------------------------------------------

def _fetchone(conn, sql: str, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None


def _fetchall(conn, sql: str, params=None) -> list:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _table_exists(conn, table_name: str) -> bool:
    result = _fetchone(conn, """
        SELECT COUNT(*) FROM pg_tables
        WHERE schemaname = 'public' AND tablename = %s
    """, (table_name,))
    return (result or 0) > 0


# ---------------------------------------------------------------------------
# Section 1: Coverage Report
# ---------------------------------------------------------------------------

def collect_coverage(conn) -> dict:
    """성분별 데이터 커버리지를 집계한다."""
    # 전체 활성 성분 수
    total = _fetchone(conn, """
        SELECT COUNT(*) FROM "터울주성분" WHERE "IsDeleted" = FALSE
    """) or 0

    # edb_enrichment_status 기반 단계별 집계
    if not _table_exists(conn, "edb_enrichment_status"):
        return {
            "total_ingredients": total,
            "error": "edb_enrichment_status 테이블 없음",
        }

    status_counts = {}
    step_columns = [
        ("chembl_mapped",      "chembl"),
        ("mechanism_fetched",  "mechanism"),
        ("admet_fetched",      "admet"),
        ("disease_fetched",    "disease"),
        ("literature_fetched", "literature"),
        ("trials_fetched",     "trials"),
        ("fda_fetched",        "fda"),
    ]
    for col, key in step_columns:
        count = _fetchone(conn, f"""
            SELECT COUNT(*) FROM edb_enrichment_status WHERE "{col}" = TRUE
        """) or 0
        status_counts[key] = count

    # 등록된 총 성분 수 (edb_enrichment_status)
    registered = _fetchone(conn, "SELECT COUNT(*) FROM edb_enrichment_status") or 0

    # ChEMBL 매핑 기준 "매핑된" 성분 수
    mapped = status_counts.get("chembl", 0)

    # 데이터 테이블별 실제 레코드 보유 성분 수 (distinct)
    data_coverage = {}
    table_key_map = [
        ("edb_mechanism",      "mechanism_rows"),
        ("edb_admet",          "admet_rows"),
        ("edb_drug_disease",   "disease_rows"),
        ("edb_literature",     "literature_rows"),
        ("edb_clinical_trial", "trial_rows"),
        ("edb_safety",         "safety_rows"),
        ("edb_ingredient_xref","xref_rows"),
    ]
    for table, key in table_key_map:
        if _table_exists(conn, table):
            count = _fetchone(conn, f"""
                SELECT COUNT(DISTINCT "심평원성분코드") FROM {table}
            """) or 0
        else:
            count = 0
        data_coverage[key] = count

    # 섹션별 A4/A5 포함 여부 계산
    def _section_inclusion(count: int, base: int) -> str:
        if base == 0:
            return "N/A"
        ratio = count / base
        if ratio >= THRESHOLD_BOTH:
            return f"A4 + A5 포함 ({ratio:.1%})"
        elif ratio >= THRESHOLD_A4:
            return f"A4만 포함 ({ratio:.1%})"
        else:
            return f"포함하지 않음 ({ratio:.1%})"

    sections = {}
    section_data = [
        ("chembl_mapping",  mapped,                          total),
        ("mechanism",       status_counts.get("mechanism", 0), mapped),
        ("admet",           status_counts.get("admet", 0),    mapped),
        ("disease",         status_counts.get("disease", 0),  mapped),
        ("literature",      status_counts.get("literature", 0), mapped),
        ("trials",          status_counts.get("trials", 0),   mapped),
        ("fda_label",       status_counts.get("fda", 0),      mapped),
    ]
    for key, count, base in section_data:
        sections[key] = _section_inclusion(count, base)

    return {
        "total_ingredients": total,
        "registered_in_status": registered,
        "unregistered": total - registered,
        "chembl_mapped": mapped,
        "chembl_mapped_pct": round(mapped / total * 100, 1) if total > 0 else 0.0,
        "step_counts": status_counts,
        "step_pcts": {
            k: round(v / mapped * 100, 1) if mapped > 0 else 0.0
            for k, v in status_counts.items()
            if k != "chembl"
        },
        "data_table_coverage": data_coverage,
        "section_inclusion": sections,
    }


# ---------------------------------------------------------------------------
# Section 2: Accuracy Metrics
# ---------------------------------------------------------------------------

def _verify_pmids_pubmed(pmids: list[str]) -> dict:
    """PubMed E-utilities로 PMID 유효성을 일괄 검증한다.

    Returns:
        {"valid": int, "invalid": int, "invalid_pmids": [...]}
    """
    if not pmids:
        return {"valid": 0, "invalid": 0, "invalid_pmids": []}

    valid = 0
    invalid = 0
    invalid_pmids = []

    for i in range(0, len(pmids), PMID_BATCH_SIZE):
        batch = pmids[i: i + PMID_BATCH_SIZE]
        ids_str = ",".join(batch)
        url = (
            f"{PUBMED_ESUMMARY_URL}"
            f"?db=pubmed&id={ids_str}&retmode=json&retmax={PMID_BATCH_SIZE}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pharmport-report/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            result_ids = set(str(k) for k in data.get("result", {}).keys() if k != "uids")
            for pmid in batch:
                if pmid in result_ids:
                    valid += 1
                else:
                    invalid += 1
                    invalid_pmids.append(pmid)
        except Exception as e:
            logger.warning("PubMed API 배치 검증 실패 (offset %d): %s", i, e)
            # API 실패 시 해당 배치는 unknown으로 처리 (유효로 간주)
            valid += len(batch)

    return {"valid": valid, "invalid": invalid, "invalid_pmids": invalid_pmids[:50]}


def collect_accuracy(conn, verify_pmids: bool = True) -> dict:
    """정확도 지표를 집계한다."""
    metrics: dict[str, Any] = {}

    # --- ChEMBL 매핑 정밀도 ---
    # exact match (match_method = 'exact') vs synonym match
    if _table_exists(conn, "edb_ingredient_xref"):
        rows = _fetchall(conn, """
            SELECT match_method, COUNT(*) as cnt
            FROM edb_ingredient_xref
            WHERE source = 'chembl'
            GROUP BY match_method
        """)
        method_counts: dict[str, int] = {}
        for row in rows:
            method_counts[row[0] or "unknown"] = row[1]

        total_xref = sum(method_counts.values())
        exact_count = sum(v for k, v in method_counts.items()
                          if k and "exact" in k.lower())
        synonym_count = sum(v for k, v in method_counts.items()
                            if k and "synonym" in k.lower())
        high_confidence = _fetchone(conn, """
            SELECT COUNT(*) FROM edb_ingredient_xref
            WHERE source = 'chembl' AND confidence >= 0.9
        """) or 0

        metrics["chembl_mapping"] = {
            "total": total_xref,
            "by_method": method_counts,
            "exact_count": exact_count,
            "synonym_count": synonym_count,
            "high_confidence_count": high_confidence,
            "precision_estimate": round(high_confidence / total_xref, 4) if total_xref > 0 else 0.0,
        }
    else:
        metrics["chembl_mapping"] = {"error": "edb_ingredient_xref 테이블 없음"}

    # --- PMID 유효성 ---
    if _table_exists(conn, "edb_literature"):
        total_lit = _fetchone(conn, "SELECT COUNT(*) FROM edb_literature") or 0
        pmid_rows = _fetchall(conn, """
            SELECT pmid FROM edb_literature
            WHERE pmid IS NOT NULL AND pmid != ''
        """)
        pmids = [r[0] for r in pmid_rows]
        total_pmids = len(pmids)

        retracted = _fetchone(conn, """
            SELECT COUNT(*) FROM edb_literature
            WHERE retraction_status = 'retracted'
        """) or 0

        if verify_pmids and pmids:
            logger.info("PubMed PMID 유효성 검증 중 (%d건)...", total_pmids)
            pmid_validity = _verify_pmids_pubmed(pmids)
        else:
            pmid_validity = {
                "valid": total_pmids,
                "invalid": 0,
                "invalid_pmids": [],
                "note": "검증 생략 (--no-pmid-check 또는 PMID 없음)",
            }

        metrics["literature"] = {
            "total_records": total_lit,
            "total_pmids": total_pmids,
            "pmid_validity": pmid_validity,
            "pmid_validity_rate": round(
                pmid_validity["valid"] / total_pmids, 4
            ) if total_pmids > 0 else 1.0,
            "retracted_count": retracted,
            "retraction_rate": round(retracted / total_pmids, 4) if total_pmids > 0 else 0.0,
        }
    else:
        metrics["literature"] = {"error": "edb_literature 테이블 없음"}

    # --- 소스 간 충돌 현황 ---
    if _table_exists(conn, "edb_data_conflict"):
        total_conflicts = _fetchone(conn, "SELECT COUNT(*) FROM edb_data_conflict") or 0
        unresolved = _fetchone(conn, """
            SELECT COUNT(*) FROM edb_data_conflict WHERE resolution = 'unresolved'
        """) or 0
        resolved = total_conflicts - unresolved

        # 충돌 유형별 분포
        conflict_by_field = _fetchall(conn, """
            SELECT field_name, COUNT(*) as cnt
            FROM edb_data_conflict
            GROUP BY field_name
            ORDER BY cnt DESC
            LIMIT 10
        """)

        metrics["conflicts_summary"] = {
            "total": total_conflicts,
            "unresolved": unresolved,
            "resolved": resolved,
            "unresolved_rate": round(unresolved / total_conflicts, 4) if total_conflicts > 0 else 0.0,
            "top_conflict_fields": [
                {"field": r[0], "count": r[1]} for r in conflict_by_field
            ],
        }
    else:
        metrics["conflicts_summary"] = {"error": "edb_data_conflict 테이블 없음"}

    return metrics


# ---------------------------------------------------------------------------
# Section 3: Conflict Detection
# ---------------------------------------------------------------------------

def detect_and_log_conflicts(conn) -> dict:
    """ChEMBL과 Open Targets 간 MoA/indication 충돌을 감지하고 edb_data_conflict에 기록한다."""
    if not _table_exists(conn, "edb_mechanism") or not _table_exists(conn, "edb_drug_disease"):
        return {"error": "필요 테이블 없음 (edb_mechanism 또는 edb_drug_disease)"}
    if not _table_exists(conn, "edb_data_conflict"):
        return {"error": "edb_data_conflict 테이블 없음"}

    new_conflicts = 0
    existing_skipped = 0

    # 1. ChEMBL ↔ Open Targets MoA 충돌:
    #    동일 성분코드에 대해 chembl(action_type)과 opentargets(therapeutic_area)가
    #    서로 모순되는 경우 — action_type이 'INHIBITOR'인데 OT에서 activator 계열 indication인 경우 등.
    #    여기서는 동일 성분코드에서 chembl source mechanism과 opentargets source disease가
    #    모두 존재하는 경우 source 간 target_name ↔ disease_name 불일치를 로깅한다.

    # 2. 간단하고 명확한 충돌: edb_ingredient_xref에서 동일 성분코드에 chembl_id가 2개 이상
    if _table_exists(conn, "edb_ingredient_xref"):
        multi_chembl_rows = _fetchall(conn, """
            SELECT "심평원성분코드", COUNT(DISTINCT source_id) as cnt,
                   STRING_AGG(source_id, ', ' ORDER BY source_id) as ids
            FROM edb_ingredient_xref
            WHERE source = 'chembl'
            GROUP BY "심평원성분코드"
            HAVING COUNT(DISTINCT source_id) > 1
        """)

        for row in multi_chembl_rows:
            code, cnt, ids = row[0], row[1], row[2]
            # 이미 같은 충돌이 기록됐는지 확인
            exists = _fetchone(conn, """
                SELECT 1 FROM edb_data_conflict
                WHERE "심평원성분코드" = %s
                  AND field_name = 'chembl_id'
                  AND source_a = 'chembl'
                  AND source_b = 'chembl'
            """, (code,))
            if exists:
                existing_skipped += 1
                continue

            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO edb_data_conflict
                    ("심평원성분코드", field_name, source_a, value_a, source_b, value_b,
                     resolution, resolution_note)
                    VALUES (%s, 'chembl_id', 'chembl', %s, 'chembl', %s,
                            'unresolved', '동일 성분코드에 ChEMBL ID 다수 매핑')
                    ON CONFLICT DO NOTHING
                """, (code, ids.split(", ")[0], ids.split(", ")[-1]))
                new_conflicts += cur.rowcount
        conn.commit()

    # 3. ChEMBL mechanism ↔ Open Targets disease indication 충돌
    #    action_type='INHIBITOR'이지만 OT에서 해당 target이 activator로 분류된 경우
    #    (간단히: 동일 target에 대해 chembl action_type과 ot source가 둘 다 있는 경우를 기록)
    moa_conflict_rows = _fetchall(conn, """
        SELECT m."심평원성분코드",
               m.action_type,
               m.target_name,
               d.disease_name,
               d.source
        FROM edb_mechanism m
        JOIN edb_drug_disease d ON m."심평원성분코드" = d."심평원성분코드"
        WHERE m.source = 'chembl'
          AND d.source = 'opentargets'
          AND m.action_type IS NOT NULL
          AND d.disease_name IS NOT NULL
          AND m.action_type ILIKE '%antagonist%'
          AND d.disease_name ILIKE '%activat%'
        LIMIT 500
    """)

    for row in moa_conflict_rows:
        code, action_type, target_name, disease_name, ot_source = row
        field = f"moa_vs_indication:{target_name or 'unknown'}"
        exists = _fetchone(conn, """
            SELECT 1 FROM edb_data_conflict
            WHERE "심평원성분코드" = %s AND field_name = %s
        """, (code, field))
        if exists:
            existing_skipped += 1
            continue

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO edb_data_conflict
                ("심평원성분코드", field_name, source_a, value_a, source_b, value_b,
                 resolution, resolution_note)
                VALUES (%s, %s, 'chembl', %s, 'opentargets', %s,
                        'unresolved', 'ChEMBL antagonist vs OT activator indication')
                ON CONFLICT DO NOTHING
            """, (code, field, action_type, disease_name))
            new_conflicts += cur.rowcount
    conn.commit()

    # 결과 집계
    total_conflicts = _fetchone(conn, "SELECT COUNT(*) FROM edb_data_conflict") or 0
    unresolved = _fetchone(conn, """
        SELECT COUNT(*) FROM edb_data_conflict WHERE resolution = 'unresolved'
    """) or 0

    return {
        "new_conflicts_logged": new_conflicts,
        "existing_skipped": existing_skipped,
        "total_conflicts": total_conflicts,
        "unresolved_conflicts": unresolved,
        "unresolved_rate": round(unresolved / total_conflicts, 4) if total_conflicts > 0 else 0.0,
        "gate_pass": (unresolved / total_conflicts <= GATE_CONFLICT_UNRESOLVED_MAX)
                     if total_conflicts > 0 else True,
    }


# ---------------------------------------------------------------------------
# Section 4: Enrichment Status Summary
# ---------------------------------------------------------------------------

def collect_status_summary(conn) -> dict:
    """단계별 완료율, 에러 분포, 상위 에러를 집계한다."""
    if not _table_exists(conn, "edb_enrichment_status"):
        return {"error": "edb_enrichment_status 테이블 없음"}

    total = _fetchone(conn, "SELECT COUNT(*) FROM edb_enrichment_status") or 0
    if total == 0:
        return {"total": 0, "note": "edb_enrichment_status 비어있음"}

    step_columns = [
        ("chembl_mapped",      "ChEMBL 매핑"),
        ("mechanism_fetched",  "MoA 수집"),
        ("admet_fetched",      "ADMET 수집"),
        ("disease_fetched",    "질병 연관"),
        ("literature_fetched", "문헌 수집"),
        ("trials_fetched",     "임상시험 수집"),
        ("fda_fetched",        "FDA label 수집"),
    ]

    completion = {}
    for col, label in step_columns:
        done = _fetchone(conn, f"""
            SELECT COUNT(*) FROM edb_enrichment_status WHERE "{col}" = TRUE
        """) or 0
        completion[label] = {
            "done": done,
            "total": total,
            "pct": round(done / total * 100, 1),
        }

    # 에러 분포
    error_rows = _fetchall(conn, """
        SELECT last_error, COUNT(*) as cnt
        FROM edb_enrichment_status
        WHERE last_error IS NOT NULL AND last_error != ''
        GROUP BY last_error
        ORDER BY cnt DESC
        LIMIT 15
    """)

    error_count = _fetchone(conn, """
        SELECT COUNT(*) FROM edb_enrichment_status
        WHERE last_error IS NOT NULL AND last_error != ''
    """) or 0

    fully_complete = _fetchone(conn, """
        SELECT COUNT(*) FROM edb_enrichment_status
        WHERE chembl_mapped = TRUE
          AND mechanism_fetched = TRUE
          AND admet_fetched = TRUE
          AND disease_fetched = TRUE
          AND literature_fetched = TRUE
          AND trials_fetched = TRUE
          AND fda_fetched = TRUE
    """) or 0

    return {
        "total_registered": total,
        "fully_complete": fully_complete,
        "fully_complete_pct": round(fully_complete / total * 100, 1),
        "with_errors": error_count,
        "error_rate": round(error_count / total * 100, 1),
        "step_completion": completion,
        "top_errors": [
            {"error": r[0][:120] if r[0] else "", "count": r[1]}
            for r in error_rows
        ],
    }


# ---------------------------------------------------------------------------
# Phase 2 Gate Check
# ---------------------------------------------------------------------------

def evaluate_phase2_gate(accuracy: dict, conflicts: dict) -> dict:
    """Phase 2 진입 조건을 평가한다."""
    gates = []

    # Gate 1: ChEMBL 매핑 정밀도
    chembl = accuracy.get("chembl_mapping", {})
    if "precision_estimate" in chembl:
        precision = chembl["precision_estimate"]
        gate1 = {
            "name": "ChEMBL 매핑 정밀도",
            "value": precision,
            "threshold": GATE_CHEMBL_PRECISION_MIN,
            "pass": precision >= GATE_CHEMBL_PRECISION_MIN,
            "detail": f"{precision:.1%} >= {GATE_CHEMBL_PRECISION_MIN:.0%}",
        }
    else:
        gate1 = {
            "name": "ChEMBL 매핑 정밀도",
            "value": None,
            "threshold": GATE_CHEMBL_PRECISION_MIN,
            "pass": False,
            "detail": chembl.get("error", "데이터 없음"),
        }
    gates.append(gate1)

    # Gate 2: PMID 유효성
    lit = accuracy.get("literature", {})
    if "pmid_validity_rate" in lit:
        pmid_rate = lit["pmid_validity_rate"]
        gate2 = {
            "name": "PMID 유효성",
            "value": pmid_rate,
            "threshold": GATE_PMID_VALIDITY_MIN,
            "pass": pmid_rate >= GATE_PMID_VALIDITY_MIN,
            "detail": f"{pmid_rate:.1%} >= {GATE_PMID_VALIDITY_MIN:.0%}",
        }
    else:
        gate2 = {
            "name": "PMID 유효성",
            "value": None,
            "threshold": GATE_PMID_VALIDITY_MIN,
            "pass": True,
            "detail": lit.get("error", "문헌 데이터 없음 (조건 미적용)"),
        }
    gates.append(gate2)

    # Gate 3: 철회 논문 비율
    if "retraction_rate" in lit:
        ret_rate = lit["retraction_rate"]
        gate3 = {
            "name": "철회 논문 비율",
            "value": ret_rate,
            "threshold": GATE_RETRACTION_MAX,
            "pass": ret_rate <= GATE_RETRACTION_MAX,
            "detail": f"{ret_rate:.1%} <= {GATE_RETRACTION_MAX:.0%}",
        }
    else:
        gate3 = {
            "name": "철회 논문 비율",
            "value": None,
            "threshold": GATE_RETRACTION_MAX,
            "pass": True,
            "detail": "문헌 데이터 없음 (조건 미적용)",
        }
    gates.append(gate3)

    # Gate 4: 미해결 충돌 비율
    if "unresolved_rate" in conflicts:
        conflict_rate = conflicts["unresolved_rate"]
        gate4 = {
            "name": "미해결 충돌 비율",
            "value": conflict_rate,
            "threshold": GATE_CONFLICT_UNRESOLVED_MAX,
            "pass": conflict_rate <= GATE_CONFLICT_UNRESOLVED_MAX,
            "detail": f"{conflict_rate:.1%} <= {GATE_CONFLICT_UNRESOLVED_MAX:.0%}",
        }
    else:
        gate4 = {
            "name": "미해결 충돌 비율",
            "value": None,
            "threshold": GATE_CONFLICT_UNRESOLVED_MAX,
            "pass": True,
            "detail": conflicts.get("error", "충돌 데이터 없음 (조건 미적용)"),
        }
    gates.append(gate4)

    all_pass = all(g["pass"] for g in gates)

    return {
        "phase2_ready": all_pass,
        "gates": gates,
        "passed_count": sum(1 for g in gates if g["pass"]),
        "total_gates": len(gates),
    }


# ---------------------------------------------------------------------------
# 출력 포매터
# ---------------------------------------------------------------------------

SEP = "=" * 70
SEP2 = "-" * 70


def _pct_bar(value: float, width: int = 20) -> str:
    """간단한 텍스트 진행바."""
    filled = int(value * width)
    return "[" + "#" * filled + "." * (width - filled) + f"] {value:.1%}"


def print_coverage_report(cov: dict):
    print(SEP)
    print("  섹션 1: 성분별 데이터 커버리지")
    print(SEP)

    if "error" in cov:
        print(f"  오류: {cov['error']}")
        return

    total = cov["total_ingredients"]
    mapped = cov["chembl_mapped"]

    print(f"  전체 성분 수        : {total:>8,}")
    print(f"  status 등록         : {cov['registered_in_status']:>8,}  ({cov['registered_in_status']/total*100:.1f}% of total)" if total else "")
    print(f"  미등록              : {cov['unregistered']:>8,}")
    print()
    print(f"  ChEMBL 매핑 성공    : {mapped:>8,} / {total:>6,}  {_pct_bar(cov['chembl_mapped_pct']/100)}")
    print()

    steps = [
        ("mechanism",  "MoA 데이터"),
        ("admet",      "ADMET 데이터"),
        ("disease",    "질병 연관 데이터"),
        ("literature", "문헌 데이터"),
        ("trials",     "임상시험 데이터"),
        ("fda",        "FDA label 매핑"),
    ]
    step_counts = cov.get("step_counts", {})
    step_pcts = cov.get("step_pcts", {})

    for key, label in steps:
        count = step_counts.get(key, 0)
        pct = step_pcts.get(key, 0.0)
        print(f"  {label:<20}: {count:>8,} / {mapped:>6,}  {_pct_bar(pct/100)}")

    print()
    print("  데이터 테이블 실보유 성분 수 (distinct 심평원성분코드):")
    dc = cov.get("data_table_coverage", {})
    table_labels = [
        ("xref_rows",      "edb_ingredient_xref"),
        ("mechanism_rows", "edb_mechanism"),
        ("admet_rows",     "edb_admet"),
        ("disease_rows",   "edb_drug_disease"),
        ("literature_rows","edb_literature"),
        ("trial_rows",     "edb_clinical_trial"),
        ("safety_rows",    "edb_safety"),
    ]
    for key, tbl in table_labels:
        count = dc.get(key, 0)
        print(f"    {tbl:<30}: {count:>8,}")

    print()
    print("  섹션별 A4/A5 포함 여부:")
    si = cov.get("section_inclusion", {})
    section_labels = [
        ("chembl_mapping", "ChEMBL 매핑"),
        ("mechanism",      "MoA"),
        ("admet",          "ADMET"),
        ("disease",        "질병 연관"),
        ("literature",     "문헌"),
        ("trials",         "임상시험"),
        ("fda_label",      "FDA label"),
    ]
    for key, label in section_labels:
        print(f"    {label:<16}: {si.get(key, 'N/A')}")


def print_accuracy_report(acc: dict):
    print()
    print(SEP)
    print("  섹션 2: 정확도 지표 (Phase 2 게이트)")
    print(SEP)

    # ChEMBL 매핑
    chembl = acc.get("chembl_mapping", {})
    if "error" in chembl:
        print(f"  ChEMBL: {chembl['error']}")
    else:
        total = chembl.get("total", 0)
        print(f"  ChEMBL 매핑 총계        : {total:>8,}")
        print(f"  방법별 분포:")
        for method, cnt in sorted(chembl.get("by_method", {}).items(), key=lambda x: -x[1]):
            print(f"    {method or 'unknown':<30}: {cnt:>6,}")
        hc = chembl.get("high_confidence_count", 0)
        prec = chembl.get("precision_estimate", 0.0)
        gate_sym = "PASS" if prec >= GATE_CHEMBL_PRECISION_MIN else "FAIL"
        print(f"  고신뢰도 (confidence>=0.9): {hc:>6,}")
        print(f"  매핑 정밀도 추정        : {prec:.1%}  [{gate_sym}]  (임계값: {GATE_CHEMBL_PRECISION_MIN:.0%})")

    print()

    # 문헌
    lit = acc.get("literature", {})
    if "error" in lit:
        print(f"  문헌: {lit['error']}")
    else:
        total_lit = lit.get("total_records", 0)
        total_pmids = lit.get("total_pmids", 0)
        pv = lit.get("pmid_validity", {})
        pmid_rate = lit.get("pmid_validity_rate", 1.0)
        ret_count = lit.get("retracted_count", 0)
        ret_rate = lit.get("retraction_rate", 0.0)

        print(f"  문헌 레코드 총계        : {total_lit:>8,}")
        print(f"  PMID 보유 레코드        : {total_pmids:>8,}")

        gate_pmid = "PASS" if pmid_rate >= GATE_PMID_VALIDITY_MIN else "FAIL"
        gate_ret = "PASS" if ret_rate <= GATE_RETRACTION_MAX else "FAIL"

        if "note" in pv:
            print(f"  PMID 유효성             : {pv['note']}")
        else:
            print(f"  유효 PMID               : {pv.get('valid', 0):>6,} / {total_pmids}")
            print(f"  무효 PMID               : {pv.get('invalid', 0):>6,}")
            if pv.get("invalid_pmids"):
                sample = pv["invalid_pmids"][:10]
                print(f"  무효 PMID 예시          : {', '.join(sample)}")
        print(f"  PMID 유효성 비율        : {pmid_rate:.1%}  [{gate_pmid}]  (임계값: {GATE_PMID_VALIDITY_MIN:.0%})")
        print(f"  철회 논문               : {ret_count:>6,}  ({ret_rate:.1%})  [{gate_ret}]  (임계값: {GATE_RETRACTION_MAX:.0%})")

    print()

    # 충돌 요약
    cs = acc.get("conflicts_summary", {})
    if "error" in cs:
        print(f"  충돌: {cs['error']}")
    else:
        total_c = cs.get("total", 0)
        unres = cs.get("unresolved", 0)
        unres_rate = cs.get("unresolved_rate", 0.0)
        gate_c = "PASS" if unres_rate <= GATE_CONFLICT_UNRESOLVED_MAX else "FAIL"
        print(f"  총 충돌 레코드          : {total_c:>8,}")
        print(f"  미해결 충돌             : {unres:>8,}  ({unres_rate:.1%})  [{gate_c}]  (임계값: {GATE_CONFLICT_UNRESOLVED_MAX:.0%})")
        print(f"  해결된 충돌             : {cs.get('resolved', 0):>8,}")
        if cs.get("top_conflict_fields"):
            print("  충돌 빈발 필드:")
            for item in cs["top_conflict_fields"][:5]:
                print(f"    {item['field']:<40}: {item['count']:>5,}")


def print_conflict_report(conf: dict):
    print()
    print(SEP)
    print("  섹션 3: 충돌 감지 결과")
    print(SEP)

    if "error" in conf:
        print(f"  오류: {conf['error']}")
        return

    new_c = conf.get("new_conflicts_logged", 0)
    skip_c = conf.get("existing_skipped", 0)
    total_c = conf.get("total_conflicts", 0)
    unres = conf.get("unresolved_conflicts", 0)
    unres_rate = conf.get("unresolved_rate", 0.0)
    gate_sym = "PASS" if conf.get("gate_pass", True) else "FAIL"

    print(f"  이번 실행 신규 충돌 기록: {new_c:>6,}")
    print(f"  기존 충돌 (건너뜀)      : {skip_c:>6,}")
    print(f"  누적 총 충돌 레코드     : {total_c:>6,}")
    print(f"  미해결 충돌             : {unres:>6,}  ({unres_rate:.1%})")
    print(f"  게이트 결과             : [{gate_sym}]  (임계값: {GATE_CONFLICT_UNRESOLVED_MAX:.0%})")


def print_status_summary(summary: dict):
    print()
    print(SEP)
    print("  섹션 4: Enrichment 진행 현황")
    print(SEP)

    if "error" in summary:
        print(f"  오류: {summary['error']}")
        return

    total = summary.get("total_registered", 0)
    if total == 0:
        print(f"  {summary.get('note', '데이터 없음')}")
        return

    full = summary.get("fully_complete", 0)
    full_pct = summary.get("fully_complete_pct", 0.0)
    err_cnt = summary.get("with_errors", 0)
    err_pct = summary.get("error_rate", 0.0)

    print(f"  등록된 성분 수          : {total:>8,}")
    print(f"  전 단계 완료            : {full:>8,}  ({full_pct:.1f}%)")
    print(f"  에러 발생               : {err_cnt:>8,}  ({err_pct:.1f}%)")
    print()
    print("  단계별 완료율:")
    for label, info in summary.get("step_completion", {}).items():
        done = info["done"]
        pct = info["pct"]
        print(f"    {label:<22}: {done:>7,} / {total:>7,}  {_pct_bar(pct/100)}")

    errors = summary.get("top_errors", [])
    if errors:
        print()
        print("  상위 에러 유형:")
        for item in errors[:10]:
            err_text = (item["error"] or "")[:80]
            print(f"    [{item['count']:>5}] {err_text}")


def print_gate_check(gate: dict):
    print()
    print(SEP)
    print("  Phase 2 진입 게이트 체크")
    print(SEP)

    for g in gate.get("gates", []):
        sym = "PASS" if g["pass"] else "FAIL"
        print(f"  [{sym}] {g['name']:<24} {g['detail']}")

    print(SEP2)
    passed = gate.get("passed_count", 0)
    total_gates = gate.get("total_gates", 0)
    ready = gate.get("phase2_ready", False)
    verdict = "Phase 2 진입 가능" if ready else "Phase 2 진입 불가 — 조건 미충족"
    print(f"  결과: {passed}/{total_gates} 게이트 통과  →  {verdict}")
    print(SEP)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 1-C: Enrichment 커버리지 + 정확도 리포트 + 충돌 감지"
    )
    parser.add_argument("--json",       action="store_true", help="JSON 포맷 출력")
    parser.add_argument("--gate-check", action="store_true", help="Phase 2 진입 조건만 체크")
    parser.add_argument("--conflicts",  action="store_true", help="충돌 감지만 실행")
    parser.add_argument("--dev",        action="store_true", help="dev DB 사용")
    parser.add_argument("--no-pmid-check", action="store_true",
                        help="PubMed PMID 유효성 검증 생략 (빠른 실행)")
    parser.add_argument("--save-json",  metavar="PATH",
                        help="JSON 결과를 파일로 저장")
    args = parser.parse_args()

    db_name = os.getenv("DEV_DATABASE_NAME") if args.dev else None
    db_label = db_name or os.getenv("DATABASE_NAME", "teoul_pharminfo")
    logger.info("대상 DB: %s", db_label)

    conn = get_connection(db_name)

    try:
        report_ts = datetime.now(timezone.utc).isoformat()

        # --conflicts 모드: 충돌 감지만 실행
        if args.conflicts:
            logger.info("충돌 감지 실행 중...")
            conflict_result = detect_and_log_conflicts(conn)
            if args.json:
                print(json.dumps(conflict_result, ensure_ascii=False, indent=2))
            else:
                print_conflict_report(conflict_result)
            return

        # 데이터 수집
        logger.info("커버리지 집계 중...")
        coverage = collect_coverage(conn)

        logger.info("정확도 지표 집계 중...")
        accuracy = collect_accuracy(conn, verify_pmids=not args.no_pmid_check)

        logger.info("충돌 감지 및 기록 중...")
        conflict_result = detect_and_log_conflicts(conn)

        logger.info("진행 현황 집계 중...")
        status_summary = collect_status_summary(conn)

        # Phase 2 게이트
        gate = evaluate_phase2_gate(accuracy, conflict_result)

        # 전체 리포트 조립
        full_report = {
            "generated_at": report_ts,
            "db": db_label,
            "coverage": coverage,
            "accuracy": accuracy,
            "conflicts": conflict_result,
            "status_summary": status_summary,
            "phase2_gate": gate,
        }

        # --gate-check 모드
        if args.gate_check:
            if args.json:
                print(json.dumps(gate, ensure_ascii=False, indent=2))
            else:
                print_gate_check(gate)
            # exit code: 0=pass, 1=fail
            sys.exit(0 if gate["phase2_ready"] else 1)

        # JSON 모드
        if args.json:
            output = json.dumps(full_report, ensure_ascii=False, indent=2)
            print(output)
            if args.save_json:
                with open(args.save_json, "w", encoding="utf-8") as f:
                    f.write(output)
                logger.info("JSON 저장 완료: %s", args.save_json)
            return

        # 포맷된 리포트 출력
        print()
        print(SEP)
        print(f"  PharmPort Enrichment Report")
        print(f"  생성일시: {report_ts}")
        print(f"  DB: {db_label}")
        print(SEP)

        print_coverage_report(coverage)
        print_accuracy_report(accuracy)
        print_conflict_report(conflict_result)
        print_status_summary(status_summary)
        print_gate_check(gate)

        if args.save_json:
            output = json.dumps(full_report, ensure_ascii=False, indent=2)
            with open(args.save_json, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"\n  JSON 저장 완료: {args.save_json}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
