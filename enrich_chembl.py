"""
Phase 1-A: ChEMBL 성분 매핑 + MoA + ADMET 수집

3단계 파이프라인:
  Step 1 (mapping):   ChEMBL 화합물 검색 → edb_ingredient_xref 저장
  Step 2 (mechanism): MoA 데이터 수집    → edb_mechanism 저장
  Step 3 (admet):     ADMET 속성 수집    → edb_admet 저장

최적화:
  - 심평원성분코드 1-4자리(주성분 base)가 같은 코드는 약리학 데이터를 공유
  - 고유 base 10,491개에 대해 API를 1회씩만 호출하고 결과를 전체 코드에 복사

Usage:
    python enrich_chembl.py                      # 전체 미완료 성분 처리
    python enrich_chembl.py --code 101301AIJ     # 단건 처리
    python enrich_chembl.py --limit 100          # 100건만 처리
    python enrich_chembl.py --step mapping       # Step 1만 실행
    python enrich_chembl.py --step mechanism     # Step 2만 실행
    python enrich_chembl.py --step admet         # Step 3만 실행
    python enrich_chembl.py --dev                # dev DB 사용
    python enrich_chembl.py --dry-run            # API 호출만 테스트, DB 저장 안함
    python enrich_chembl.py --workers 4          # 4개 워커로 병렬 처리
"""

import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

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
# ChEMBL API 설정
# ---------------------------------------------------------------------------

CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"
REQUEST_TIMEOUT = 30  # seconds
SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json"})


# ---------------------------------------------------------------------------
# ChEMBL HTTP 래퍼
# ---------------------------------------------------------------------------

def _get(url: str, params: dict = None) -> dict:
    """ChEMBL REST API GET 요청. 4xx/5xx는 예외를 발생시킨다."""
    resp = SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def chembl_get(url: str, params: dict = None) -> dict:
    """rate-limit + retry 적용 ChEMBL GET."""
    return api_call_with_retry("chembl", _get, url, params)


# ---------------------------------------------------------------------------
# Step 1: ChEMBL 화합물 검색
# ---------------------------------------------------------------------------

def search_chembl_compound(name: str) -> Optional[dict]:
    """성분명으로 ChEMBL 화합물을 검색한다.

    전략:
      1. exact_name  — preferred_name 완전 일치
      2. synonym     — molecule_synonym 검색
      3. similarity  — 이름 유사 검색 (fallback, score >= 0.8)

    Returns:
        {"chembl_id": ..., "name": ..., "confidence": ..., "match_method": ...}
        또는 None (미발견)
    """
    if not name:
        return None

    # --- 1. exact_name ---
    try:
        data = chembl_get(
            f"{CHEMBL_BASE}/molecule",
            params={"pref_name__iexact": name, "format": "json", "limit": 1},
        )
        molecules = data.get("molecules", [])
        if molecules:
            m = molecules[0]
            return {
                "chembl_id": m["molecule_chembl_id"],
                "name": m.get("pref_name") or name,
                "confidence": 1.0,
                "match_method": "exact_name",
            }
    except requests.HTTPError as e:
        logger.debug("exact_name 검색 실패 (%s): %s", name[:40], e)

    # --- 2. synonym ---
    try:
        data = chembl_get(
            f"{CHEMBL_BASE}/molecule",
            params={"molecule_synonyms__synonym__iexact": name, "format": "json", "limit": 1},
        )
        molecules = data.get("molecules", [])
        if molecules:
            m = molecules[0]
            return {
                "chembl_id": m["molecule_chembl_id"],
                "name": m.get("pref_name") or name,
                "confidence": 0.9,
                "match_method": "synonym",
            }
    except requests.HTTPError as e:
        logger.debug("synonym 검색 실패 (%s): %s", name[:40], e)

    # --- 3. similarity (이름 부분 일치 fallback) ---
    try:
        data = chembl_get(
            f"{CHEMBL_BASE}/molecule",
            params={"pref_name__icontains": name.split()[0], "format": "json", "limit": 5},
        )
        molecules = data.get("molecules", [])
        for m in molecules:
            pref = (m.get("pref_name") or "").lower()
            if name.lower() in pref or pref in name.lower():
                return {
                    "chembl_id": m["molecule_chembl_id"],
                    "name": m.get("pref_name") or name,
                    "confidence": 0.7,
                    "match_method": "similarity",
                }
    except requests.HTTPError as e:
        logger.debug("similarity 검색 실패 (%s): %s", name[:40], e)

    return None


def _process_mapping_base(
    base: str,
    base_codes: list[dict],
    db_name: str | None,
    dry_run: bool,
) -> tuple[str, dict[str, Optional[str]], bool]:
    """워커 스레드용: 단일 base 그룹에 대한 mapping 처리.

    Returns:
        (base, {심평원성분코드: chembl_id or None}, success_bool)
    """
    thread_conn = get_thread_connection(db_name)
    try:
        representative = base_codes[0]
        raw_name = representative.get("성분명") or ""
        clean_name = preprocess_ingredient_name(raw_name)

        chembl_result = None
        if clean_name:
            try:
                chembl_result = search_chembl_compound(clean_name)
            except Exception as e:
                logger.warning("  ChEMBL 검색 오류 (base=%s, name=%s): %s", base, clean_name[:40], e)

        success = chembl_result is not None
        partial: dict[str, Optional[str]] = {}

        for row in base_codes:
            code = row["심평원성분코드"]
            partial[code] = chembl_result["chembl_id"] if chembl_result else None

            if dry_run:
                logger.info(
                    "  [DRY-RUN] %s → %s (method=%s, conf=%.2f)",
                    code,
                    chembl_result["chembl_id"] if chembl_result else "없음",
                    chembl_result.get("match_method", "-") if chembl_result else "-",
                    chembl_result.get("confidence", 0.0) if chembl_result else 0.0,
                )
                continue

            if chembl_result:
                xref_record = {
                    "심평원성분코드": code,
                    "source": "chembl",
                    "source_id": chembl_result["chembl_id"],
                    "source_name": chembl_result.get("name"),
                    "confidence": chembl_result.get("confidence", 1.0),
                    "match_method": chembl_result.get("match_method", "unknown"),
                }
                batch_insert(thread_conn, "edb_ingredient_xref", [xref_record],
                             conflict_action='("심평원성분코드", source, source_id) DO NOTHING')
                update_status(thread_conn, code, "chembl", success=True)
            else:
                update_status(thread_conn, code, "chembl", success=False,
                              error=f"ChEMBL 미발견: {clean_name[:100]}")

        return (base, partial, success)
    finally:
        thread_conn.close()


def run_step_mapping(
    conn,
    codes: list[dict],
    dry_run: bool = False,
    workers: int = 1,
    db_name: str | None = None,
) -> dict[str, Optional[str]]:
    """Step 1: 성분코드 목록에 대해 ChEMBL ID를 매핑하고 edb_ingredient_xref에 저장한다.

    같은 base(1-4자리)를 공유하는 코드는 API를 1회만 호출하고 결과를 복사한다.

    Returns:
        {심평원성분코드: chembl_id or None}
    """
    # base별로 그룹핑
    base_to_codes: dict[str, list[dict]] = {}
    for row in codes:
        base = row["심평원성분코드"][:4]
        base_to_codes.setdefault(base, []).append(row)

    logger.info("Step 1 (mapping): %d개 코드, %d개 고유 base, workers=%d",
                len(codes), len(base_to_codes), workers)

    tracker = ProgressTracker(len(base_to_codes), "chembl_mapping")
    code_to_chembl: dict[str, Optional[str]] = {}

    if workers > 1:
        # --- 병렬 처리 ---
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_process_mapping_base, base, base_codes, db_name, dry_run): base
                for base, base_codes in base_to_codes.items()
            }
            for future in as_completed(futures):
                base = futures[future]
                try:
                    _, partial, success = future.result()
                    code_to_chembl.update(partial)
                    _safe_tracker_update(tracker, success=success)
                except Exception as e:
                    logger.warning("  mapping 워커 오류 (base=%s): %s", base, e)
                    _safe_tracker_update(tracker, success=False)
    else:
        # --- 순차 처리 (기존 동작) ---
        for base, base_codes in base_to_codes.items():
            # 대표 코드 1개로 API 호출
            representative = base_codes[0]
            raw_name = representative.get("성분명") or ""
            clean_name = preprocess_ingredient_name(raw_name)

            chembl_result = None
            if clean_name:
                try:
                    chembl_result = chembl_get.__wrapped__(clean_name) if hasattr(chembl_get, "__wrapped__") else None
                    chembl_result = search_chembl_compound(clean_name)
                except Exception as e:
                    logger.warning("  ChEMBL 검색 오류 (base=%s, name=%s): %s", base, clean_name[:40], e)

            success = chembl_result is not None

            for row in base_codes:
                code = row["심평원성분코드"]
                code_to_chembl[code] = chembl_result["chembl_id"] if chembl_result else None

                if dry_run:
                    logger.info(
                        "  [DRY-RUN] %s → %s (method=%s, conf=%.2f)",
                        code,
                        chembl_result["chembl_id"] if chembl_result else "없음",
                        chembl_result.get("match_method", "-") if chembl_result else "-",
                        chembl_result.get("confidence", 0.0) if chembl_result else 0.0,
                    )
                    continue

                if chembl_result:
                    xref_record = {
                        "심평원성분코드": code,
                        "source": "chembl",
                        "source_id": chembl_result["chembl_id"],
                        "source_name": chembl_result.get("name"),
                        "confidence": chembl_result.get("confidence", 1.0),
                        "match_method": chembl_result.get("match_method", "unknown"),
                    }
                    batch_insert(conn, "edb_ingredient_xref", [xref_record],
                                 conflict_action='("심평원성분코드", source, source_id) DO NOTHING')
                    update_status(conn, code, "chembl", success=True)
                else:
                    update_status(conn, code, "chembl", success=False,
                                  error=f"ChEMBL 미발견: {clean_name[:100]}")

            tracker.update(success=success)

    summary = tracker.summary()
    logger.info("Step 1 완료: 성공 %d / 전체 base %d", summary["success"], summary["total"])
    return code_to_chembl


# ---------------------------------------------------------------------------
# Step 2: MoA (Mechanism of Action)
# ---------------------------------------------------------------------------

def fetch_mechanism(chembl_id: str) -> list[dict]:
    """ChEMBL /mechanism API로 MoA 데이터를 가져온다.

    Returns:
        mechanism 레코드 목록 (raw API 응답)
    """
    try:
        data = chembl_get(
            f"{CHEMBL_BASE}/mechanism",
            params={"molecule_chembl_id": chembl_id, "format": "json", "limit": 100},
        )
        return data.get("mechanisms", [])
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return []
        raise


def build_mechanism_records(code: str, chembl_id: str, raw_mechs: list[dict]) -> list[dict]:
    """raw mechanism API 응답을 edb_mechanism 레코드로 변환한다."""
    records = []
    for m in raw_mechs:
        target = m.get("target_chembl_id")
        records.append({
            "심평원성분코드": code,
            "chembl_id": chembl_id,
            "action_type": m.get("action_type"),
            "mechanism_description": m.get("mechanism_of_action"),
            "target_name": m.get("target_name"),
            "target_chembl_id": target,
            "target_type": m.get("target_type"),
            "target_organism": m.get("target_organism"),
            "direct_interaction": m.get("direct_interaction"),
            "disease_efficacy": m.get("disease_efficacy"),
            "binding_site_name": m.get("binding_site_name"),
            "source": "chembl",
            "source_refs": str(m.get("mechanism_refs", "")),
        })
    return records


def _process_mechanism_base(
    base: str,
    base_codes: list[dict],
    code_to_chembl: dict[str, Optional[str]],
    db_name: str | None,
    dry_run: bool,
) -> tuple[str, bool]:
    """워커 스레드용: 단일 base 그룹에 대한 mechanism 처리.

    Returns:
        (base, success_bool)
    """
    thread_conn = get_thread_connection(db_name)
    try:
        representative = base_codes[0]
        rep_code = representative["심평원성분코드"]
        chembl_id = code_to_chembl[rep_code]

        try:
            raw_mechs = fetch_mechanism(chembl_id)
        except Exception as e:
            logger.warning("  MoA 수집 오류 (chembl_id=%s): %s", chembl_id, e)
            for row in base_codes:
                update_status(thread_conn, row["심평원성분코드"], "mechanism", success=False,
                              error=str(e)[:200])
            return (base, False)

        for row in base_codes:
            code = row["심평원성분코드"]
            records = build_mechanism_records(code, chembl_id, raw_mechs)

            if dry_run:
                logger.info(
                    "  [DRY-RUN] %s → ChEMBL %s: %d건 MoA",
                    code, chembl_id, len(records),
                )
                continue

            if records:
                inserted = batch_insert(
                    thread_conn, "edb_mechanism", records,
                    conflict_action='("심평원성분코드", chembl_id, target_chembl_id) DO NOTHING',
                )
                logger.debug("  %s: edb_mechanism %d건 저장", code, inserted)
            update_status(thread_conn, code, "mechanism", success=True)

        return (base, True)
    finally:
        thread_conn.close()


def run_step_mechanism(
    conn,
    codes: list[dict],
    code_to_chembl: dict[str, Optional[str]],
    dry_run: bool = False,
    workers: int = 1,
    db_name: str | None = None,
) -> None:
    """Step 2: 매핑된 ChEMBL ID로 MoA 데이터를 수집하고 edb_mechanism에 저장한다.

    같은 base를 공유하는 코드는 API를 1회만 호출하고 결과를 전체 코드에 복사한다.
    """
    # base별로 그룹핑 (chembl_id가 있는 코드만)
    base_to_codes: dict[str, list[dict]] = {}
    for row in codes:
        code = row["심평원성분코드"]
        if code_to_chembl.get(code):
            base = code[:4]
            base_to_codes.setdefault(base, []).append(row)

    mapped_count = sum(len(v) for v in base_to_codes.values())
    logger.info("Step 2 (mechanism): %d개 코드 (매핑됨), %d개 고유 base, workers=%d",
                mapped_count, len(base_to_codes), workers)

    tracker = ProgressTracker(len(base_to_codes), "chembl_mechanism")

    if workers > 1:
        # --- 병렬 처리 ---
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _process_mechanism_base, base, base_codes, code_to_chembl, db_name, dry_run
                ): base
                for base, base_codes in base_to_codes.items()
            }
            for future in as_completed(futures):
                base = futures[future]
                try:
                    _, success = future.result()
                    _safe_tracker_update(tracker, success=success)
                except Exception as e:
                    logger.warning("  mechanism 워커 오류 (base=%s): %s", base, e)
                    _safe_tracker_update(tracker, success=False)
    else:
        # --- 순차 처리 (기존 동작) ---
        for base, base_codes in base_to_codes.items():
            representative = base_codes[0]
            rep_code = representative["심평원성분코드"]
            chembl_id = code_to_chembl[rep_code]

            try:
                raw_mechs = fetch_mechanism(chembl_id)
            except Exception as e:
                logger.warning("  MoA 수집 오류 (chembl_id=%s): %s", chembl_id, e)
                for row in base_codes:
                    update_status(conn, row["심평원성분코드"], "mechanism", success=False,
                                  error=str(e)[:200])
                tracker.update(success=False)
                continue

            success = True

            for row in base_codes:
                code = row["심평원성분코드"]
                records = build_mechanism_records(code, chembl_id, raw_mechs)

                if dry_run:
                    logger.info(
                        "  [DRY-RUN] %s → ChEMBL %s: %d건 MoA",
                        code, chembl_id, len(records),
                    )
                    continue

                if records:
                    inserted = batch_insert(
                        conn, "edb_mechanism", records,
                        conflict_action='("심평원성분코드", chembl_id, target_chembl_id) DO NOTHING',
                    )
                    logger.debug("  %s: edb_mechanism %d건 저장", code, inserted)
                update_status(conn, code, "mechanism", success=True)

            tracker.update(success=success)

    summary = tracker.summary()
    logger.info("Step 2 완료: 처리 %d / 전체 base %d", summary["processed"], summary["total"])


# ---------------------------------------------------------------------------
# Step 3: ADMET 속성
# ---------------------------------------------------------------------------

def fetch_admet(chembl_id: str) -> Optional[dict]:
    """ChEMBL /molecule/{id} API로 molecule_properties를 가져온다.

    Returns:
        molecule_properties 딕셔너리 또는 None
    """
    try:
        data = chembl_get(
            f"{CHEMBL_BASE}/molecule/{chembl_id}",
            params={"format": "json"},
        )
        return data.get("molecule_properties")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise


def _safe_float(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_admet_record(code: str, chembl_id: str, props: dict) -> dict:
    """molecule_properties를 edb_admet 레코드로 변환한다."""
    return {
        "심평원성분코드": code,
        "chembl_id": chembl_id,
        "molecular_weight": _safe_float(props.get("full_mwt") or props.get("mw_freebase")),
        "alogp": _safe_float(props.get("alogp")),
        "hba": _safe_int(props.get("hba")),
        "hbd": _safe_int(props.get("hbd")),
        "psa": _safe_float(props.get("psa")),
        "rotatable_bonds": _safe_int(props.get("rtb")),
        "aromatic_rings": _safe_int(props.get("aromatic_rings")),
        "ro5_violations": _safe_int(props.get("num_ro5_violations")),
        "qed_weighted": _safe_float(props.get("qed_weighted")),
        "source": "chembl",
    }


def _process_admet_base(
    base: str,
    base_codes: list[dict],
    code_to_chembl: dict[str, Optional[str]],
    db_name: str | None,
    dry_run: bool,
) -> tuple[str, bool]:
    """워커 스레드용: 단일 base 그룹에 대한 ADMET 처리.

    Returns:
        (base, success_bool)
    """
    thread_conn = get_thread_connection(db_name)
    try:
        representative = base_codes[0]
        rep_code = representative["심평원성분코드"]
        chembl_id = code_to_chembl[rep_code]

        try:
            props = fetch_admet(chembl_id)
        except Exception as e:
            logger.warning("  ADMET 수집 오류 (chembl_id=%s): %s", chembl_id, e)
            for row in base_codes:
                update_status(thread_conn, row["심평원성분코드"], "admet", success=False,
                              error=str(e)[:200])
            return (base, False)

        for row in base_codes:
            code = row["심평원성분코드"]

            if dry_run:
                logger.info(
                    "  [DRY-RUN] %s → ChEMBL %s: props=%s",
                    code, chembl_id,
                    "있음" if props else "없음",
                )
                continue

            if props:
                record = build_admet_record(code, chembl_id, props)
                batch_insert(
                    thread_conn, "edb_admet", [record],
                    conflict_action='("심평원성분코드", chembl_id) DO NOTHING',
                )
            update_status(thread_conn, code, "admet", success=True)

        return (base, True)
    finally:
        thread_conn.close()


def run_step_admet(
    conn,
    codes: list[dict],
    code_to_chembl: dict[str, Optional[str]],
    dry_run: bool = False,
    workers: int = 1,
    db_name: str | None = None,
) -> None:
    """Step 3: 매핑된 ChEMBL ID로 ADMET 속성을 수집하고 edb_admet에 저장한다.

    같은 base를 공유하는 코드는 API를 1회만 호출하고 결과를 전체 코드에 복사한다.
    """
    # base별로 그룹핑 (chembl_id가 있는 코드만)
    base_to_codes: dict[str, list[dict]] = {}
    for row in codes:
        code = row["심평원성분코드"]
        if code_to_chembl.get(code):
            base = code[:4]
            base_to_codes.setdefault(base, []).append(row)

    mapped_count = sum(len(v) for v in base_to_codes.values())
    logger.info("Step 3 (admet): %d개 코드 (매핑됨), %d개 고유 base, workers=%d",
                mapped_count, len(base_to_codes), workers)

    tracker = ProgressTracker(len(base_to_codes), "chembl_admet")

    if workers > 1:
        # --- 병렬 처리 ---
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _process_admet_base, base, base_codes, code_to_chembl, db_name, dry_run
                ): base
                for base, base_codes in base_to_codes.items()
            }
            for future in as_completed(futures):
                base = futures[future]
                try:
                    _, success = future.result()
                    _safe_tracker_update(tracker, success=success)
                except Exception as e:
                    logger.warning("  admet 워커 오류 (base=%s): %s", base, e)
                    _safe_tracker_update(tracker, success=False)
    else:
        # --- 순차 처리 (기존 동작) ---
        for base, base_codes in base_to_codes.items():
            representative = base_codes[0]
            rep_code = representative["심평원성분코드"]
            chembl_id = code_to_chembl[rep_code]

            try:
                props = fetch_admet(chembl_id)
            except Exception as e:
                logger.warning("  ADMET 수집 오류 (chembl_id=%s): %s", chembl_id, e)
                for row in base_codes:
                    update_status(conn, row["심평원성분코드"], "admet", success=False,
                                  error=str(e)[:200])
                tracker.update(success=False)
                continue

            for row in base_codes:
                code = row["심평원성분코드"]

                if dry_run:
                    logger.info(
                        "  [DRY-RUN] %s → ChEMBL %s: props=%s",
                        code, chembl_id,
                        "있음" if props else "없음",
                    )
                    continue

                if props:
                    record = build_admet_record(code, chembl_id, props)
                    batch_insert(
                        conn, "edb_admet", [record],
                        conflict_action='("심평원성분코드", chembl_id) DO NOTHING',
                    )
                update_status(conn, code, "admet", success=True)

            tracker.update(success=True)

    summary = tracker.summary()
    logger.info("Step 3 완료: 처리 %d / 전체 base %d", summary["processed"], summary["total"])


# ---------------------------------------------------------------------------
# 기존 xref에서 chembl_id 로드 (Step 2/3 단독 실행 시)
# ---------------------------------------------------------------------------

def load_existing_chembl_map(conn, codes: list[dict]) -> dict[str, Optional[str]]:
    """edb_ingredient_xref에서 이미 매핑된 chembl_id를 로드한다."""
    if not codes:
        return {}

    code_list = [r["심평원성분코드"] for r in codes]
    fmt = ",".join(["%s"] * len(code_list))

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT "심평원성분코드", source_id
            FROM edb_ingredient_xref
            WHERE "심평원성분코드" IN ({fmt})
              AND source = 'chembl'
            ORDER BY confidence DESC
        """, code_list)
        rows = cur.fetchall()

    # 코드당 신뢰도 높은 첫 번째 chembl_id 사용
    result: dict[str, Optional[str]] = {r["심평원성분코드"]: None for r in codes}
    for code, chembl_id in rows:
        if result.get(code) is None:
            result[code] = chembl_id

    return result


# ---------------------------------------------------------------------------
# 단건 처리
# ---------------------------------------------------------------------------

def fetch_single_code(conn, code: str) -> Optional[dict]:
    """터울주성분에서 단건 코드 정보를 가져온다."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT "심평원성분코드", "성분명", "성분명한글"
            FROM "터울주성분"
            WHERE "심평원성분코드" = %s AND "IsDeleted" = FALSE
        """, (code,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "심평원성분코드": row[0],
            "성분명": row[1],
            "성분명한글": row[2],
        }


# ---------------------------------------------------------------------------
# 메인 파이프라인
# ---------------------------------------------------------------------------

def run_pipeline(
    conn,
    codes: list[dict],
    step: Optional[str],
    dry_run: bool,
    workers: int = 1,
    db_name: str | None = None,
) -> None:
    """코드 목록에 대해 지정된 step(들)을 실행한다.

    step=None이면 전체 파이프라인(mapping → mechanism → admet)을 실행.
    """
    if not codes:
        logger.info("처리할 코드가 없습니다.")
        return

    run_mapping   = step in (None, "mapping")
    run_mechanism = step in (None, "mechanism")
    run_admet     = step in (None, "admet")

    code_to_chembl: dict[str, Optional[str]] = {}

    # Step 1
    if run_mapping:
        # mapping 단계 대상: chembl_mapped=FALSE인 코드
        mapping_codes = codes
        code_to_chembl = run_step_mapping(conn, mapping_codes, dry_run=dry_run,
                                          workers=workers, db_name=db_name)
    else:
        # Step 2/3만 실행: xref에서 기존 매핑 로드
        code_to_chembl = load_existing_chembl_map(conn, codes)

    # Step 2
    if run_mechanism:
        # mechanism 단계 대상 코드 결정
        if step == "mechanism":
            # 단독 실행: mechanism_fetched=FALSE인 코드 (매핑 완료 전제)
            mech_codes = codes
        else:
            # 전체 파이프라인: 방금 매핑된 코드 중 chembl_id가 있는 것
            mech_codes = [r for r in codes if code_to_chembl.get(r["심평원성분코드"])]
        run_step_mechanism(conn, mech_codes, code_to_chembl, dry_run=dry_run,
                           workers=workers, db_name=db_name)

    # Step 3
    if run_admet:
        if step == "admet":
            admet_codes = codes
        else:
            admet_codes = [r for r in codes if code_to_chembl.get(r["심평원성분코드"])]
        run_step_admet(conn, admet_codes, code_to_chembl, dry_run=dry_run,
                       workers=workers, db_name=db_name)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 1-A: ChEMBL 매핑 + MoA + ADMET enrichment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python enrich_chembl.py                      # 전체 미완료 처리
  python enrich_chembl.py --code 101301AIJ     # 단건 처리
  python enrich_chembl.py --limit 100          # 100건만 처리
  python enrich_chembl.py --step mapping       # 매핑만 실행
  python enrich_chembl.py --step mechanism     # MoA만 실행
  python enrich_chembl.py --step admet         # ADMET만 실행
  python enrich_chembl.py --dev                # dev DB 사용
  python enrich_chembl.py --dry-run            # API 테스트, DB 저장 안함
  python enrich_chembl.py --workers 4          # 4개 워커로 병렬 처리
""",
    )
    parser.add_argument("--code", help="단건 처리할 심평원성분코드")
    parser.add_argument("--limit", type=int, default=0,
                        help="처리 건수 제한 (0=전체)")
    parser.add_argument(
        "--step",
        choices=["mapping", "mechanism", "admet"],
        default=None,
        help="실행할 단계 (기본: 전체 파이프라인)",
    )
    parser.add_argument("--dev", action="store_true",
                        help="dev DB(teoul_201201) 사용")
    parser.add_argument("--dry-run", action="store_true",
                        help="API 호출만 테스트, DB 저장 안함")
    parser.add_argument("--workers", type=int, default=1,
                        help="병렬 워커 수 (기본 1=순차처리)")
    args = parser.parse_args()

    db_name = os.getenv("DEV_DATABASE_NAME") if args.dev else None
    conn = get_connection(db_name)

    try:
        if args.code:
            # 단건
            row = fetch_single_code(conn, args.code)
            if not row:
                logger.error("코드를 찾을 수 없음: %s", args.code)
                sys.exit(1)
            codes = [row]
            logger.info("단건 처리: %s (%s)", args.code, row.get("성분명", ""))
        else:
            # step에 따라 미완료 코드 조회
            step_for_pending = args.step or "chembl"
            if step_for_pending == "mechanism":
                codes = get_pending_codes(conn, "mechanism", limit=args.limit)
            elif step_for_pending == "admet":
                codes = get_pending_codes(conn, "admet", limit=args.limit)
            else:
                # mapping 또는 전체: chembl_mapped=FALSE 기준
                codes = get_pending_codes(conn, "chembl", limit=args.limit)

            if not codes:
                logger.info("처리할 미완료 코드가 없습니다.")
                return

            logger.info(
                "처리 대상: %d건%s%s",
                len(codes),
                f" (step={args.step})" if args.step else " (전체 파이프라인)",
                " [DRY-RUN]" if args.dry_run else "",
            )

        run_pipeline(conn, codes, step=args.step, dry_run=args.dry_run,
                     workers=args.workers, db_name=db_name)
        logger.info("완료.")

    except KeyboardInterrupt:
        logger.info("사용자 중단.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
