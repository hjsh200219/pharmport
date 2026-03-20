"""
Phase 1.5: Enrichment 프로파일 해싱 + 클러스터링 (단일제 + 복합제)

Step A: 단일제 프로파일 해시 생성
  - enrichment 완료된 성분(edb_ 테이블) 대상
  - 6개 필드 추출 → 정규화 → SHA-256 해시 → profile_hash
  - 동일 해시 → 동일 클러스터 (cluster_id 자동 부여)

Step B: 복합제 constituent 해시 생성
  - 복합제(positions 5-6 == '00' or 'TL') 대상
  - edb_ingredient_xref에서 구성 성분코드 수집 → 정렬 → SHA-256

Step C: 클러스터 할당
  - 동일 profile_hash → 동일 cluster_id

결과: edb_enrichment_status 테이블에 profile_hash, compound_constituent_hash,
      cluster_id, profile_updated_at 업데이트

Usage:
    python build_profiles.py                    # 전체 처리
    python build_profiles.py --batch-size 500   # 배치 크기 지정
    python build_profiles.py --recompute        # 기존 해시 재계산
    python build_profiles.py --dry-run          # 분석만, DB 저장 안 함
    python build_profiles.py --stats            # 프로파일 통계만 출력
    python build_profiles.py --dev              # dev DB 사용
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from collections import defaultdict

from psycopg2.extras import RealDictCursor

from common import get_connection
from enrich_base import normalize_for_hash, split_ingredients, ProgressTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

# 프로파일 해시 대상 6개 필드
PROFILE_FIELDS = [
    "mechanism",
    "side_effects",
    "contraindications",
    "interactions",
    "monitoring",
    "special_pop",
]

# 특수 집단 키워드 패턴 (monitoring → special_pop 분류 기준)
SPECIAL_POP_PATTERNS = [
    r"\bpregnant\b", r"\bpregnancy\b", r"\blactation\b", r"\bnursing\b",
    r"\bpediatric\b", r"\bchild(ren)?\b", r"\bneonatal\b", r"\binfant\b",
    r"\belderly\b", r"\bgeriatric\b", r"\brenal\b", r"\bhepatic\b",
    r"\brenal impairment\b", r"\bhepatic impairment\b",
    r"\b임부\b", r"\b수유\b", r"\b소아\b", r"\b노인\b", r"\b신장\b", r"\b간장\b",
]
SPECIAL_POP_RE = re.compile("|".join(SPECIAL_POP_PATTERNS), re.IGNORECASE)


# ---------------------------------------------------------------------------
# 심평원성분코드 파서
# ---------------------------------------------------------------------------

def is_compound_code(code: str) -> bool:
    """복합제 여부 (positions 5-6 == '00' or 'TL')."""
    if not code or len(code) < 6:
        return False
    type_code = code[4:6]
    return type_code in ("00", "TL")


# ---------------------------------------------------------------------------
# DB 조회: enrichment 데이터 추출
# ---------------------------------------------------------------------------

def fetch_target_codes(conn, recompute: bool = False) -> list[dict]:
    """프로파일 생성 대상 성분코드 목록 반환.

    조건:
      - 터울주성분.IsDeleted = FALSE
      - edb_enrichment_status 존재
      - recompute=False이면 profile_hash가 NULL인 것만
    """
    where_clause = ""
    if not recompute:
        where_clause = "AND (es.profile_hash IS NULL)"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"""
            SELECT es."심평원성분코드", t."성분명", t."성분명한글"
            FROM edb_enrichment_status es
            JOIN "터울주성분" t ON es."심평원성분코드" = t."심평원성분코드"
            WHERE t."IsDeleted" = FALSE
              {where_clause}
            ORDER BY es."심평원성분코드"
        """)
        return list(cur.fetchall())


def fetch_mechanism_data(conn, code: str) -> list[dict]:
    """edb_mechanism에서 성분의 작용 메커니즘 데이터 조회.

    mechanism 필드: mechanism_type(action_type) + description(mechanism_description)
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT action_type, mechanism_description, target_name
            FROM edb_mechanism
            WHERE "심평원성분코드" = %s
              AND (target_organism IS NULL OR target_organism = 'Homo sapiens')
            ORDER BY action_type, target_name
        """, (code,))
        return list(cur.fetchall())


def fetch_safety_data(conn, code: str) -> list[dict]:
    """edb_safety에서 성분의 안전성 데이터 조회.

    info_type 값:
      - 'adverse_effect' → side_effects
      - 'contraindication' → contraindications
      - 'interaction' → interactions
      - 'monitoring' → monitoring (severity critical/severe)
      - 기타: special_pop 패턴 매칭
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT info_type, description, severity, related_ingredient_code
            FROM edb_safety
            WHERE "심평원성분코드" = %s
              AND validation_status != 'rejected'
            ORDER BY info_type, severity, description
        """, (code,))
        return list(cur.fetchall())


def fetch_interaction_data(conn, code: str) -> list[dict]:
    """edb_drug_disease에서 relationship_type='interaction' 데이터 조회."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT disease_name, therapeutic_area, association_score
            FROM edb_drug_disease
            WHERE "심평원성분코드" = %s
            ORDER BY disease_name
        """, (code,))
        return list(cur.fetchall())


def fetch_constituent_codes(conn, code: str) -> list[str]:
    """edb_ingredient_xref에서 복합제의 구성 성분코드 목록 조회."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT source_id
            FROM edb_ingredient_xref
            WHERE "심평원성분코드" = %s
            ORDER BY source_id
        """, (code,))
        rows = cur.fetchall()
    return [r[0] for r in rows if r[0]]


# ---------------------------------------------------------------------------
# Step A: 6개 필드 추출 + 정규화
# ---------------------------------------------------------------------------

def extract_mechanism_field(mechanism_rows: list[dict]) -> list[str]:
    """action_type + description 조합 → 정렬된 정규화 문자열 목록."""
    items = []
    for row in mechanism_rows:
        action = row.get("action_type") or ""
        desc = row.get("mechanism_description") or ""
        combined = f"{action}|{desc}".strip("|")
        if combined:
            items.append(normalize_for_hash(combined))
    return sorted(set(items))


def extract_side_effects(safety_rows: list[dict]) -> list[str]:
    """info_type='adverse_effect'인 description 목록 (severity → 알파벳 정렬)."""
    SEVERITY_ORDER = {"critical": 0, "severe": 1, "moderate": 2, "mild": 3, "unknown": 4}

    adverse = [
        r for r in safety_rows if r.get("info_type") == "adverse_effect"
    ]
    adverse.sort(key=lambda r: (
        SEVERITY_ORDER.get(r.get("severity", "unknown"), 4),
        r.get("description", ""),
    ))
    return [normalize_for_hash(r["description"]) for r in adverse if r.get("description")]


def extract_contraindications(safety_rows: list[dict]) -> list[str]:
    """info_type='contraindication'인 description 목록 (알파벳 정렬)."""
    items = [
        normalize_for_hash(r["description"])
        for r in safety_rows
        if r.get("info_type") == "contraindication" and r.get("description")
    ]
    return sorted(items)


def extract_interactions(safety_rows: list[dict], drug_disease_rows: list[dict]) -> list[str]:
    """상호작용 데이터 통합.

    - edb_safety에서 info_type='interaction'
    - edb_drug_disease 전체 (relationship_type은 이미 쿼리에서 필터링)
    """
    items = set()

    # edb_safety 기반
    for r in safety_rows:
        if r.get("info_type") == "interaction" and r.get("description"):
            items.add(normalize_for_hash(r["description"]))

    # edb_drug_disease 기반
    for r in drug_disease_rows:
        name = r.get("disease_name") or ""
        area = r.get("therapeutic_area") or ""
        combined = f"{name}|{area}".strip("|")
        if combined:
            items.add(normalize_for_hash(combined))

    return sorted(items)


def extract_monitoring(safety_rows: list[dict]) -> list[str]:
    """severity가 'critical' 또는 'severe'인 description (모니터링 대상)."""
    items = [
        normalize_for_hash(r["description"])
        for r in safety_rows
        if r.get("severity") in ("critical", "severe") and r.get("description")
    ]
    return sorted(set(items))


def extract_special_pop(safety_rows: list[dict]) -> list[str]:
    """특수 집단(임부, 소아, 노인 등) 관련 description."""
    items = [
        normalize_for_hash(r["description"])
        for r in safety_rows
        if r.get("description") and SPECIAL_POP_RE.search(r["description"])
    ]
    return sorted(set(items))


def build_profile_fields(
    mechanism_rows: list[dict],
    safety_rows: list[dict],
    drug_disease_rows: list[dict],
) -> dict[str, list[str]]:
    """6개 필드를 추출하여 딕셔너리로 반환."""
    return {
        "mechanism": extract_mechanism_field(mechanism_rows),
        "side_effects": extract_side_effects(safety_rows),
        "contraindications": extract_contraindications(safety_rows),
        "interactions": extract_interactions(safety_rows, drug_disease_rows),
        "monitoring": extract_monitoring(safety_rows),
        "special_pop": extract_special_pop(safety_rows),
    }


# ---------------------------------------------------------------------------
# SHA-256 해시 생성
# ---------------------------------------------------------------------------

def compute_profile_hash(fields: dict[str, list[str]]) -> str:
    """6개 필드 딕셔너리로부터 SHA-256 프로파일 해시를 생성한다.

    1. 각 필드의 값을 normalize_for_hash로 정규화
    2. 필드 내부 정렬 (알파벳순)
    3. JSON 직렬화 (키 정렬, ensure_ascii=False)
    4. SHA-256 해시

    Args:
        fields: {"mechanism": [...], "side_effects": [...], ...}

    Returns:
        64자리 hex SHA-256 문자열
    """
    canonical = {
        key: sorted([normalize_for_hash(v) for v in vals])
        for key, vals in fields.items()
    }
    serialized = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_constituent_hash(constituent_codes: list[str]) -> str:
    """복합제 구성 성분코드 목록으로부터 constituent_hash를 생성한다.

    For compound codes (positions 5-6 are '00' or 'TL'):
    1. 구성 성분코드 알파벳순 정렬
    2. "|"으로 연결
    3. SHA-256 해시

    Args:
        constituent_codes: 구성 성분 심평원성분코드 목록

    Returns:
        64자리 hex SHA-256 문자열, 또는 빈 목록이면 빈 문자열
    """
    if not constituent_codes:
        return ""
    sorted_codes = sorted(constituent_codes)
    serialized = "|".join(sorted_codes)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Step A: 프로파일 해시 계산
# ---------------------------------------------------------------------------

def compute_profile_hash_for_code(conn, code: str) -> str | None:
    """단일 성분코드에 대해 profile_hash를 계산한다.

    6개 필드를 edb_ 테이블에서 조회하여 정규화 후 SHA-256.
    데이터가 전혀 없으면 None 반환 (skip 대상).

    Args:
        conn: psycopg2 connection
        code: 심평원성분코드

    Returns:
        64자리 hex SHA-256 또는 None (데이터 없음)
    """
    mechanism_rows = fetch_mechanism_data(conn, code)
    safety_rows = fetch_safety_data(conn, code)
    drug_disease_rows = fetch_interaction_data(conn, code)

    # 데이터가 전혀 없으면 건너뜀
    if not mechanism_rows and not safety_rows and not drug_disease_rows:
        return None

    fields = build_profile_fields(mechanism_rows, safety_rows, drug_disease_rows)
    return compute_profile_hash(fields)


# ---------------------------------------------------------------------------
# Step B: 복합제 constituent 해시 계산
# ---------------------------------------------------------------------------

def compute_constituent_hash_for_code(conn, code: str) -> str:
    """복합제 성분코드에 대해 compound_constituent_hash를 계산한다.

    edb_ingredient_xref에서 구성 성분코드를 조회하여 정렬 후 SHA-256.

    Args:
        conn: psycopg2 connection
        code: 복합제 심평원성분코드

    Returns:
        64자리 hex SHA-256 또는 빈 문자열 (구성 성분 없음)
    """
    constituent_codes = fetch_constituent_codes(conn, code)
    return compute_constituent_hash(constituent_codes)


# ---------------------------------------------------------------------------
# Step C: 클러스터 할당
# ---------------------------------------------------------------------------

def assign_cluster_ids(profile_hash_map: dict[str, str | None]) -> dict[str, int | None]:
    """동일 profile_hash를 가진 성분코드에 동일 cluster_id를 부여한다.

    Args:
        profile_hash_map: {심평원성분코드: profile_hash or None}

    Returns:
        {심평원성분코드: cluster_id or None}
    """
    # profile_hash → cluster_id 매핑 (None 해시는 건너뜀)
    hash_to_cluster: dict[str, int] = {}
    next_cluster_id = 1

    for code, ph in sorted(profile_hash_map.items()):
        if ph is None:
            continue
        if ph not in hash_to_cluster:
            hash_to_cluster[ph] = next_cluster_id
            next_cluster_id += 1

    # 코드별 cluster_id 매핑
    code_to_cluster: dict[str, int | None] = {}
    for code, ph in profile_hash_map.items():
        if ph is None:
            code_to_cluster[code] = None
        else:
            code_to_cluster[code] = hash_to_cluster[ph]

    return code_to_cluster


# ---------------------------------------------------------------------------
# DB 업데이트
# ---------------------------------------------------------------------------

def ensure_profile_columns(conn) -> None:
    """edb_enrichment_status에 프로파일 관련 컬럼이 없으면 추가한다."""
    columns_to_add = [
        ("profile_hash", "VARCHAR(64)"),
        ("compound_constituent_hash", "VARCHAR(64)"),
        ("cluster_id", "INT"),
        ("profile_updated_at", "TIMESTAMPTZ"),
    ]

    with conn.cursor() as cur:
        for col_name, col_type in columns_to_add:
            cur.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'edb_enrichment_status'
                  AND column_name = %s
            """, (col_name,))
            if not cur.fetchone():
                cur.execute(
                    f'ALTER TABLE edb_enrichment_status ADD COLUMN {col_name} {col_type}'
                )
                logger.info("컬럼 추가: edb_enrichment_status.%s (%s)", col_name, col_type)
    conn.commit()


def update_profile_in_db(
    conn,
    code: str,
    profile_hash: str | None,
    constituent_hash: str | None,
    cluster_id: int | None,
) -> None:
    """edb_enrichment_status에 프로파일 결과를 업데이트한다."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE edb_enrichment_status
            SET profile_hash = %s,
                compound_constituent_hash = %s,
                cluster_id = %s,
                profile_updated_at = NOW()
            WHERE "심평원성분코드" = %s
        """, (profile_hash, constituent_hash, cluster_id, code))


def batch_update_profiles(
    conn,
    updates: list[tuple[str, str | None, str | None, int | None]],
) -> int:
    """프로파일 결과를 배치로 업데이트한다.

    Args:
        conn: psycopg2 connection
        updates: [(code, profile_hash, constituent_hash, cluster_id), ...]

    Returns:
        업데이트된 건수
    """
    if not updates:
        return 0

    updated = 0
    with conn.cursor() as cur:
        for code, ph, ch, cid in updates:
            cur.execute("""
                UPDATE edb_enrichment_status
                SET profile_hash = %s,
                    compound_constituent_hash = %s,
                    cluster_id = %s,
                    profile_updated_at = NOW()
                WHERE "심평원성분코드" = %s
            """, (ph, ch, cid, code))
            updated += cur.rowcount
    conn.commit()
    return updated


# ---------------------------------------------------------------------------
# 메인 파이프라인
# ---------------------------------------------------------------------------

def run_profile_pipeline(
    conn,
    batch_size: int = 1000,
    recompute: bool = False,
    dry_run: bool = False,
) -> dict:
    """프로파일 해시 + 클러스터링 전체 파이프라인.

    1. 대상 코드 조회
    2. Step A: 각 코드의 profile_hash 계산
    3. Step B: 복합제의 compound_constituent_hash 계산
    4. Step C: cluster_id 할당
    5. DB 업데이트 (dry_run이 아닌 경우)

    Returns:
        파이프라인 결과 통계 딕셔너리
    """
    # 0. 컬럼 존재 확인/추가
    if not dry_run:
        ensure_profile_columns(conn)

    # 1. 대상 코드 조회
    codes = fetch_target_codes(conn, recompute=recompute)
    total = len(codes)

    if total == 0:
        logger.info("처리할 대상 코드가 없습니다.")
        return {"total": 0, "processed": 0, "hashed": 0, "skipped": 0, "clusters": 0}

    logger.info(
        "프로파일 생성 대상: %d건%s",
        total,
        " (재계산 모드)" if recompute else "",
    )

    # 2. Step A + Step B: 해시 계산
    profile_hash_map: dict[str, str | None] = {}
    constituent_hash_map: dict[str, str | None] = {}

    tracker = ProgressTracker(total, "profile_hash", log_interval=100)
    hashed_count = 0
    skipped_count = 0
    compound_count = 0

    for row in codes:
        code = row["심평원성분코드"]

        # Step A: profile_hash
        ph = compute_profile_hash_for_code(conn, code)
        profile_hash_map[code] = ph

        if ph is not None:
            hashed_count += 1
        else:
            skipped_count += 1

        # Step B: 복합제 constituent_hash
        ch = None
        if is_compound_code(code):
            ch = compute_constituent_hash_for_code(conn, code)
            if ch:
                compound_count += 1
        constituent_hash_map[code] = ch if ch else None

        tracker.update(success=(ph is not None), skipped=(ph is None))

    summary = tracker.summary()
    logger.info(
        "해시 계산 완료 — 성공: %d, 건너뜀(데이터없음): %d, 복합제 해시: %d",
        hashed_count, skipped_count, compound_count,
    )

    # 3. Step C: 클러스터 할당
    logger.info("=== Step C: 클러스터 할당 ===")
    cluster_map = assign_cluster_ids(profile_hash_map)

    unique_hashes = len(set(ph for ph in profile_hash_map.values() if ph is not None))
    unique_clusters = len(set(cid for cid in cluster_map.values() if cid is not None))

    logger.info(
        "클러스터 할당 완료 — 고유 해시: %d, 클러스터 수: %d",
        unique_hashes, unique_clusters,
    )

    # 4. DB 업데이트 (배치)
    if dry_run:
        logger.info("[DRY-RUN] DB 업데이트 건너뜀")
    else:
        logger.info("=== DB 업데이트 시작 (batch_size=%d) ===", batch_size)
        total_updated = 0
        batch: list[tuple[str, str | None, str | None, int | None]] = []

        for code in profile_hash_map:
            ph = profile_hash_map[code]
            ch = constituent_hash_map.get(code)
            cid = cluster_map.get(code)

            batch.append((code, ph, ch, cid))

            if len(batch) >= batch_size:
                updated = batch_update_profiles(conn, batch)
                total_updated += updated
                batch = []

        # 잔여 배치 처리
        if batch:
            updated = batch_update_profiles(conn, batch)
            total_updated += updated

        logger.info("DB 업데이트 완료: %d건", total_updated)

    # 5. 클러스터 통계
    _print_cluster_stats(profile_hash_map, cluster_map)

    return {
        "total": total,
        "processed": hashed_count + skipped_count,
        "hashed": hashed_count,
        "skipped": skipped_count,
        "compound_hashed": compound_count,
        "unique_hashes": unique_hashes,
        "clusters": unique_clusters,
    }


def _print_cluster_stats(
    profile_hash_map: dict[str, str | None],
    cluster_map: dict[str, int | None],
) -> None:
    """클러스터 크기 분포 통계 출력."""
    # 클러스터 크기 집계
    cluster_sizes: dict[int, int] = defaultdict(int)
    for code, cid in cluster_map.items():
        if cid is not None:
            cluster_sizes[cid] += 1

    if not cluster_sizes:
        logger.info("클러스터 데이터 없음")
        return

    sizes = sorted(cluster_sizes.values(), reverse=True)
    total_profiles = len([ph for ph in profile_hash_map.values() if ph is not None])
    total_clusters = len(cluster_sizes)

    # 크기 분포
    size_dist: dict[str, int] = defaultdict(int)
    for s in sizes:
        if s == 1:
            size_dist["1 (유일)"] += 1
        elif s <= 5:
            size_dist["2-5"] += 1
        elif s <= 20:
            size_dist["6-20"] += 1
        elif s <= 100:
            size_dist["21-100"] += 1
        else:
            size_dist["100+"] += 1

    print("\n=== 클러스터 통계 ===")
    print(f"  총 프로파일:     {total_profiles:>8,}건")
    print(f"  고유 해시:       {total_clusters:>8,}건")
    print(f"  평균 클러스터 크기: {total_profiles / total_clusters:.1f}건" if total_clusters > 0 else "")
    print(f"  최대 클러스터 크기: {sizes[0]:>8,}건" if sizes else "")
    print(f"  최소 클러스터 크기: {sizes[-1]:>8,}건" if sizes else "")
    print()
    print("  클러스터 크기 분포:")
    for label in ["1 (유일)", "2-5", "6-20", "21-100", "100+"]:
        count = size_dist.get(label, 0)
        if count > 0:
            pct = 100 * count / total_clusters if total_clusters > 0 else 0
            print(f"    {label:>10}: {count:>6,}개 ({pct:5.1f}%)")
    print()


# ---------------------------------------------------------------------------
# 통계 전용
# ---------------------------------------------------------------------------

def print_stats(conn) -> None:
    """현재 프로파일 상태 통계 출력."""
    with conn.cursor() as cur:
        # 전체 성분코드
        cur.execute('SELECT COUNT(*) FROM "터울주성분" WHERE "IsDeleted" = FALSE')
        total = cur.fetchone()[0]

        # 단일제
        cur.execute("""
            SELECT COUNT(*) FROM "터울주성분"
            WHERE "IsDeleted" = FALSE
              AND SUBSTRING("심평원성분코드", 5, 2) NOT IN ('00', 'TL')
        """)
        singles = cur.fetchone()[0]

        # 복합제
        cur.execute("""
            SELECT COUNT(*) FROM "터울주성분"
            WHERE "IsDeleted" = FALSE
              AND SUBSTRING("심평원성분코드", 5, 2) IN ('00', 'TL')
        """)
        compounds = cur.fetchone()[0]

        # enrichment_status 전체
        cur.execute("SELECT COUNT(*) FROM edb_enrichment_status")
        status_total = cur.fetchone()[0]

        # mechanism 데이터 보유 성분
        cur.execute("SELECT COUNT(DISTINCT \"심평원성분코드\") FROM edb_mechanism")
        mechanism_codes = cur.fetchone()[0]

        # safety 데이터 보유 성분
        cur.execute("SELECT COUNT(DISTINCT \"심평원성분코드\") FROM edb_safety")
        safety_codes = cur.fetchone()[0]

        # drug_disease 데이터 보유 성분
        cur.execute("SELECT COUNT(DISTINCT \"심평원성분코드\") FROM edb_drug_disease")
        drug_disease_codes = cur.fetchone()[0]

        # profile_hash 완료 건수
        profile_hash_done = 0
        constituent_hash_done = 0
        cluster_done = 0
        unique_hashes = 0
        unique_clusters = 0

        # 프로파일 컬럼 존재 여부 확인
        cur.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'edb_enrichment_status'
              AND column_name = 'profile_hash'
        """)
        has_profile_cols = cur.fetchone() is not None

        if has_profile_cols:
            cur.execute("SELECT COUNT(*) FROM edb_enrichment_status WHERE profile_hash IS NOT NULL")
            profile_hash_done = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM edb_enrichment_status WHERE compound_constituent_hash IS NOT NULL")
            constituent_hash_done = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM edb_enrichment_status WHERE cluster_id IS NOT NULL")
            cluster_done = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT profile_hash) FROM edb_enrichment_status WHERE profile_hash IS NOT NULL")
            unique_hashes = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT cluster_id) FROM edb_enrichment_status WHERE cluster_id IS NOT NULL")
            unique_clusters = cur.fetchone()[0]

    print("\n=== 프로파일 생성 현황 통계 ===")
    print(f"  터울주성분 전체:              {total:>8,}건")
    print(f"    단일제:                     {singles:>8,}건")
    print(f"    복합제 (00/TL):             {compounds:>8,}건")
    print(f"  enrichment_status 등록:       {status_total:>8,}건")
    print()
    print("  --- enrichment 데이터 보유 ---")
    print(f"  mechanism 보유 성분:          {mechanism_codes:>8,}건")
    print(f"  safety 보유 성분:             {safety_codes:>8,}건")
    print(f"  drug_disease 보유 성분:       {drug_disease_codes:>8,}건")
    print()

    if has_profile_cols:
        print("  --- 프로파일 해시 현황 ---")
        print(f"  profile_hash 완료:            {profile_hash_done:>8,}건")
        print(f"  constituent_hash 완료:        {constituent_hash_done:>8,}건")
        print(f"  cluster_id 할당:              {cluster_done:>8,}건")
        print(f"  고유 profile_hash:            {unique_hashes:>8,}건")
        print(f"  고유 cluster_id:              {unique_clusters:>8,}건")
        pending = status_total - profile_hash_done
        print(f"  미처리 (profile_hash NULL):   {pending:>8,}건")
    else:
        print("  (프로파일 컬럼 미생성 — 먼저 파이프라인을 실행하세요)")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 1.5: Profile Hashing & Clustering",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python build_profiles.py                    # 전체 처리 (미완료 대상)
  python build_profiles.py --batch-size 500   # 배치 크기 500
  python build_profiles.py --recompute        # 기존 해시 재계산
  python build_profiles.py --dry-run          # 분석만, DB 저장 안 함
  python build_profiles.py --stats            # 통계만 출력
  python build_profiles.py --dev              # dev DB 사용
""",
    )
    parser.add_argument(
        "--batch-size", type=int, default=1000,
        help="DB 업데이트 배치 크기 (기본: 1000)",
    )
    parser.add_argument(
        "--recompute", action="store_true",
        help="기존 해시가 있어도 재계산",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="분석만 수행, DB 저장 안 함",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="프로파일 통계만 출력",
    )
    parser.add_argument(
        "--dev", action="store_true",
        help="dev DB (teoul_201201) 사용",
    )
    args = parser.parse_args()

    # DB 연결
    db_name = os.getenv("DEV_DATABASE_NAME") if args.dev else None
    db_label = db_name or os.getenv("DATABASE_NAME", "teoul_pharminfo")
    logger.info("대상 DB: %s", db_label)

    conn = get_connection(db_name)
    try:
        if args.stats:
            print_stats(conn)
            return

        result = run_profile_pipeline(
            conn,
            batch_size=args.batch_size,
            recompute=args.recompute,
            dry_run=args.dry_run,
        )

        # 최종 요약
        logger.info(
            "파이프라인 완료 — 총: %d, 해시 생성: %d, 건너뜀: %d, "
            "복합제 해시: %d, 고유 해시: %d, 클러스터: %d",
            result["total"], result["hashed"], result["skipped"],
            result.get("compound_hashed", 0),
            result.get("unique_hashes", 0), result["clusters"],
        )

    except KeyboardInterrupt:
        logger.info("사용자 중단.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
