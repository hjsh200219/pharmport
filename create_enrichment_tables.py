"""
Phase 0: edb_ enrichment 테이블 10개 DDL 실행
- 기존 테이블 무변경
- dev DB (--dev) 또는 본 DB 선택 가능
- 이미 존재하는 테이블은 건너뜀

Usage:
    python create_enrichment_tables.py          # 본 DB (teoul_pharminfo)
    python create_enrichment_tables.py --dev    # dev DB (teoul_201201)
    python create_enrichment_tables.py --dry-run  # SQL만 출력
"""

import argparse
import logging
import sys

from common import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DDL_STATEMENTS = [
    # 1. 성분-외부ID 매핑 (canonical bridge)
    """
    CREATE TABLE IF NOT EXISTS edb_ingredient_xref (
        xref_id SERIAL PRIMARY KEY,
        "심평원성분코드" VARCHAR(450) NOT NULL REFERENCES "터울주성분"("심평원성분코드"),
        source VARCHAR(50) NOT NULL,
        source_id VARCHAR(200) NOT NULL,
        source_name TEXT,
        confidence FLOAT DEFAULT 1.0,
        match_method VARCHAR(50),
        fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE("심평원성분코드", source, source_id)
    );
    """,
    # 2. 작용 메커니즘
    """
    CREATE TABLE IF NOT EXISTS edb_mechanism (
        mechanism_id SERIAL PRIMARY KEY,
        "심평원성분코드" VARCHAR(450) NOT NULL,
        chembl_id VARCHAR(50),
        action_type VARCHAR(100),
        mechanism_description TEXT,
        target_name TEXT,
        target_chembl_id VARCHAR(50),
        target_type VARCHAR(50),
        target_organism VARCHAR(50),
        direct_interaction BOOLEAN,
        disease_efficacy BOOLEAN,
        binding_site_name TEXT,
        source VARCHAR(50) DEFAULT 'chembl',
        source_refs TEXT,
        fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE("심평원성분코드", chembl_id, target_chembl_id)
    );
    """,
    # 3. ADMET / Drug-likeness
    """
    CREATE TABLE IF NOT EXISTS edb_admet (
        admet_id SERIAL PRIMARY KEY,
        "심평원성분코드" VARCHAR(450) NOT NULL,
        chembl_id VARCHAR(50),
        molecular_weight FLOAT,
        alogp FLOAT,
        hba INT,
        hbd INT,
        psa FLOAT,
        rotatable_bonds INT,
        aromatic_rings INT,
        ro5_violations INT,
        qed_weighted FLOAT,
        source VARCHAR(50) DEFAULT 'chembl',
        fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE("심평원성분코드", chembl_id)
    );
    """,
    # 4. 약물-질병 연관관계
    """
    CREATE TABLE IF NOT EXISTS edb_drug_disease (
        dd_id SERIAL PRIMARY KEY,
        "심평원성분코드" VARCHAR(450) NOT NULL,
        chembl_id VARCHAR(50),
        disease_id VARCHAR(100),
        disease_name TEXT,
        therapeutic_area TEXT,
        clinical_phase INT,
        association_score FLOAT,
        source VARCHAR(50) DEFAULT 'opentargets',
        fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE("심평원성분코드", disease_id)
    );
    """,
    # 5. 안전성 (부작용/상호작용/금기/BBW)
    """
    CREATE TABLE IF NOT EXISTS edb_safety (
        safety_id SERIAL PRIMARY KEY,
        "심평원성분코드" VARCHAR(450) NOT NULL,
        info_type VARCHAR(50) NOT NULL,
        description TEXT NOT NULL,
        severity VARCHAR(20),
        related_ingredient_code VARCHAR(450),
        evidence_level VARCHAR(20),
        source VARCHAR(50) NOT NULL,
        source_id VARCHAR(200),
        validation_status VARCHAR(20) DEFAULT 'draft',
        fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 6. 근거 문헌
    """
    CREATE TABLE IF NOT EXISTS edb_literature (
        lit_id SERIAL PRIMARY KEY,
        "심평원성분코드" VARCHAR(450) NOT NULL,
        pmid VARCHAR(20),
        pmc_id VARCHAR(20),
        doi TEXT,
        title TEXT NOT NULL,
        authors TEXT,
        journal TEXT,
        pub_year INT,
        pub_type VARCHAR(50),
        relevance_category VARCHAR(50),
        abstract_summary TEXT,
        retraction_status VARCHAR(20) DEFAULT 'active',
        retraction_checked_at TIMESTAMPTZ,
        fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE("심평원성분코드", pmid)
    );
    """,
    # 7. 임상시험
    """
    CREATE TABLE IF NOT EXISTS edb_clinical_trial (
        trial_id SERIAL PRIMARY KEY,
        "심평원성분코드" VARCHAR(450) NOT NULL,
        nct_id VARCHAR(20) NOT NULL,
        title TEXT,
        phase VARCHAR(20),
        status VARCHAR(50),
        condition_name TEXT,
        enrollment INT,
        start_date DATE,
        completion_date DATE,
        sponsor TEXT,
        source VARCHAR(50) DEFAULT 'clinicaltrials',
        fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE("심평원성분코드", nct_id)
    );
    """,
    # 8. 소스 간 데이터 충돌
    """
    CREATE TABLE IF NOT EXISTS edb_data_conflict (
        conflict_id SERIAL PRIMARY KEY,
        "심평원성분코드" VARCHAR(450) NOT NULL,
        field_name VARCHAR(100) NOT NULL,
        source_a VARCHAR(50) NOT NULL,
        value_a TEXT NOT NULL,
        source_b VARCHAR(50) NOT NULL,
        value_b TEXT NOT NULL,
        resolution VARCHAR(20) DEFAULT 'unresolved',
        resolution_note TEXT,
        resolved_by TEXT,
        resolved_at TIMESTAMPTZ,
        detected_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 9. Enrichment 진행 상태 추적
    """
    CREATE TABLE IF NOT EXISTS edb_enrichment_status (
        status_id SERIAL PRIMARY KEY,
        "심평원성분코드" VARCHAR(450) NOT NULL UNIQUE,
        chembl_mapped BOOLEAN DEFAULT FALSE,
        chembl_mapped_at TIMESTAMPTZ,
        mechanism_fetched BOOLEAN DEFAULT FALSE,
        mechanism_fetched_at TIMESTAMPTZ,
        admet_fetched BOOLEAN DEFAULT FALSE,
        admet_fetched_at TIMESTAMPTZ,
        disease_fetched BOOLEAN DEFAULT FALSE,
        disease_fetched_at TIMESTAMPTZ,
        safety_fetched BOOLEAN DEFAULT FALSE,
        safety_fetched_at TIMESTAMPTZ,
        literature_fetched BOOLEAN DEFAULT FALSE,
        literature_fetched_at TIMESTAMPTZ,
        trials_fetched BOOLEAN DEFAULT FALSE,
        trials_fetched_at TIMESTAMPTZ,
        fda_fetched BOOLEAN DEFAULT FALSE,
        fda_fetched_at TIMESTAMPTZ,
        last_error TEXT,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 10. 출력 컨텐츠 블록 (A4/A5) — Publication Gate
    """
    CREATE TABLE IF NOT EXISTS edb_content_block (
        block_id SERIAL PRIMARY KEY,
        "심평원성분코드" VARCHAR(450) NOT NULL,
        section_key VARCHAR(50) NOT NULL,
        format_type VARCHAR(5) NOT NULL,
        content_json JSONB NOT NULL,
        sort_order INT DEFAULT 0,
        version INT DEFAULT 1,
        validation_status VARCHAR(20) DEFAULT 'draft',
        validated_by TEXT,
        validated_at TIMESTAMPTZ,
        generated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE("심평원성분코드", section_key, format_type)
    );
    """,
]

TABLE_NAMES = [
    "edb_ingredient_xref",
    "edb_mechanism",
    "edb_admet",
    "edb_drug_disease",
    "edb_safety",
    "edb_literature",
    "edb_clinical_trial",
    "edb_data_conflict",
    "edb_enrichment_status",
    "edb_content_block",
]


def check_existing_tables(conn):
    """이미 존재하는 edb_ 테이블 목록 반환."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename LIKE 'edb_%'
        """)
        return {row[0] for row in cur.fetchall()}


def init_enrichment_status(conn):
    """터울주성분 전체를 edb_enrichment_status에 초기화."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO edb_enrichment_status ("심평원성분코드")
            SELECT "심평원성분코드" FROM "터울주성분"
            WHERE "IsDeleted" = FALSE
            ON CONFLICT ("심평원성분코드") DO NOTHING
        """)
        inserted = cur.rowcount
        conn.commit()
        return inserted


def main():
    parser = argparse.ArgumentParser(description="edb_ enrichment 테이블 생성")
    parser.add_argument("--dev", action="store_true", help="dev DB 사용")
    parser.add_argument("--dry-run", action="store_true", help="SQL만 출력, 실행 안 함")
    parser.add_argument("--init-status", action="store_true",
                        help="edb_enrichment_status에 터울주성분 초기화")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN: 아래 SQL이 실행될 예정 ===\n")
        for i, (name, ddl) in enumerate(zip(TABLE_NAMES, DDL_STATEMENTS), 1):
            print(f"-- [{i}] {name}")
            print(ddl.strip())
            print()
        return

    import os
    db_name = os.getenv("DEV_DATABASE_NAME") if args.dev else None
    db_label = db_name or os.getenv("DATABASE_NAME", "teoul_pharminfo")

    logger.info("대상 DB: %s", db_label)
    conn = get_connection(db_name)

    try:
        existing = check_existing_tables(conn)
        if existing:
            logger.info("이미 존재하는 테이블: %s", ", ".join(sorted(existing)))

        created = 0
        for i, (name, ddl) in enumerate(zip(TABLE_NAMES, DDL_STATEMENTS), 1):
            if name in existing:
                logger.info("[%d/10] %s — 이미 존재, 건너뜀", i, name)
                continue
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()
            logger.info("[%d/10] %s — 생성 완료", i, name)
            created += 1

        logger.info("테이블 생성 완료: 신규 %d개, 기존 %d개", created, len(existing))

        if args.init_status:
            inserted = init_enrichment_status(conn)
            logger.info("edb_enrichment_status 초기화: %d건 추가", inserted)

        # 최종 확인
        final_existing = check_existing_tables(conn)
        logger.info("최종 edb_ 테이블 수: %d/10", len(final_existing))
        missing = set(TABLE_NAMES) - final_existing
        if missing:
            logger.error("누락 테이블: %s", ", ".join(sorted(missing)))
            sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
