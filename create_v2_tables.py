"""
Phase 2-A: teoul_pharminfo_v2 DB 테이블 DDL + 데이터 마이그레이션

신규 DB(teoul_pharminfo_v2)에 소스 DB 구조를 미러링하고,
LLM 생성 콘텐츠용 신규 컬럼을 추가한다.
앱 호환성을 위해 동일한 테이블명을 사용하며, DATABASE_NAME 환경변수로 전환.

Usage:
    python create_v2_tables.py                    # DDL + migration 전체
    python create_v2_tables.py --create-only      # DDL만 실행 (마이그레이션 건너뜀)
    python create_v2_tables.py --migrate-only     # 데이터 마이그레이션만 실행
    python create_v2_tables.py --dry-run          # SQL만 출력, DB에 실행하지 않음
    python create_v2_tables.py --drop-existing    # 기존 테이블 DROP 후 재생성
    python create_v2_tables.py --verify           # v2 데이터가 소스 건수와 일치하는지 검증
"""

import argparse
import logging
import sys

from common import get_connection, get_v2_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATCH_SIZE = 5000
ENABLE_PGVECTOR = "CREATE EXTENSION IF NOT EXISTS vector;"

# ---------------------------------------------------------------------------
# DDL — FK 의존성 순서로 정의
# ---------------------------------------------------------------------------

DDL_STATEMENTS: list[tuple[str, str]] = [
    # -----------------------------------------------------------------------
    # 1. 터울약품분류 (direct copy — FK 참조 없음)
    # -----------------------------------------------------------------------
    (
        "터울약품분류",
        """
        CREATE TABLE IF NOT EXISTS "터울약품분류" (
            "약품분류ID" SERIAL PRIMARY KEY,
            "약품분류명" TEXT,
            "약품분류명한글" TEXT,
            "IsDeleted" BOOLEAN NOT NULL DEFAULT FALSE,
            "등록일" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "수정일" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "ModifiedBy" TEXT
        );
        """,
    ),
    # -----------------------------------------------------------------------
    # 2. 터울약효설명 (copy structure + LLM 신규 컬럼)
    # -----------------------------------------------------------------------
    (
        "터울약효설명",
        """
        CREATE TABLE IF NOT EXISTS "터울약효설명" (
            "약효설명ID" SERIAL PRIMARY KEY,
            "터울버전" TEXT,
            "EnglishText" TEXT,
            "ModifiedBy" TEXT,
            "IsDeleted" BOOLEAN NOT NULL DEFAULT FALSE,
            "등록일" TIMESTAMP NOT NULL DEFAULT NOW(),
            "수정일" TIMESTAMP NOT NULL DEFAULT NOW(),
            -- New columns for LLM content
            source_type VARCHAR(20) DEFAULT 'legacy',
            llm_version INT,
            generated_at TIMESTAMPTZ,
            original_text TEXT
        );
        """,
    ),
    # -----------------------------------------------------------------------
    # 3. Manufacturers (direct copy)
    # -----------------------------------------------------------------------
    (
        "Manufacturers",
        """
        CREATE TABLE IF NOT EXISTS "Manufacturers" (
            "ManufacturerID" INT PRIMARY KEY,
            "Name" VARCHAR(450),
            "ModificationDate" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "CreationDate" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "Url" TEXT,
            "Name_embedding" VECTOR
        );
        """,
    ),
    # -----------------------------------------------------------------------
    # 4. 터울픽토그램 (direct copy)
    # -----------------------------------------------------------------------
    (
        "터울픽토그램",
        """
        CREATE TABLE IF NOT EXISTS "터울픽토그램" (
            "픽토그램Code" TEXT PRIMARY KEY,
            "픽토그램설명" TEXT,
            "픽토그램설명한글" TEXT,
            "IsDeleted" BOOLEAN NOT NULL DEFAULT FALSE,
            "등록일" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "수정일" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "ModifiedBy" TEXT
        );
        """,
    ),
    # -----------------------------------------------------------------------
    # 5. 터울주성분 (copy structure + enrichment/profile 신규 컬럼)
    # -----------------------------------------------------------------------
    (
        "터울주성분",
        """
        CREATE TABLE IF NOT EXISTS "터울주성분" (
            "심평원성분코드" VARCHAR(450) PRIMARY KEY,
            "약품분류ID" INT,
            "약효설명ID" INT,
            "성분명" TEXT,
            "sorted_성분명" TEXT,
            "성분명한글" TEXT,
            "고갈영양소영문" TEXT,
            "성분명_임베딩" VECTOR,
            "sorted_성분명_embedding" VECTOR(3072),
            "ModifiedBy" TEXT,
            "IsDeleted" BOOLEAN NOT NULL DEFAULT FALSE,
            "등록일" TIMESTAMP NOT NULL DEFAULT NOW(),
            "수정일" TIMESTAMP NOT NULL DEFAULT NOW(),
            -- New columns for LLM content
            profile_hash VARCHAR(64),
            cluster_id INT,
            generation_version INT DEFAULT 1,
            llm_generated_at TIMESTAMPTZ,
            validation_status VARCHAR(20) DEFAULT 'pending'
        );
        """,
    ),
    # -----------------------------------------------------------------------
    # 6. 터울복약안내A4 (copy structure + LLM 6-section 신규 컬럼)
    # -----------------------------------------------------------------------
    (
        "터울복약안내A4",
        """
        CREATE TABLE IF NOT EXISTS "터울복약안내A4" (
            "복약안내A4ID" SERIAL PRIMARY KEY,
            "터울버전" TEXT,
            "ModifiedBy" TEXT,
            "IsDeleted" BOOLEAN NOT NULL DEFAULT FALSE,
            "등록일" TIMESTAMP NOT NULL DEFAULT NOW(),
            "수정일" TIMESTAMP NOT NULL DEFAULT NOW(),
            "분류" INT,
            "EnglishText" TEXT,
            "픽토그램Code" TEXT,
            -- New columns for 6 section types
            section_type VARCHAR(30),
            source_type VARCHAR(20) DEFAULT 'legacy',
            llm_version INT,
            generated_at TIMESTAMPTZ,
            profile_hash VARCHAR(64),
            original_text TEXT
        );
        """,
    ),
    # -----------------------------------------------------------------------
    # 7. 터울복약안내A5 (same pattern as A4)
    # -----------------------------------------------------------------------
    (
        "터울복약안내A5",
        """
        CREATE TABLE IF NOT EXISTS "터울복약안내A5" (
            "복약안내A5ID" SERIAL PRIMARY KEY,
            "터울버전" TEXT,
            "ModifiedBy" TEXT,
            "IsDeleted" BOOLEAN NOT NULL DEFAULT FALSE,
            "등록일" TIMESTAMP NOT NULL DEFAULT NOW(),
            "수정일" TIMESTAMP NOT NULL DEFAULT NOW(),
            "분류" INT,
            "EnglishText" TEXT,
            -- New columns
            section_type VARCHAR(30),
            source_type VARCHAR(20) DEFAULT 'legacy',
            llm_version INT,
            generated_at TIMESTAMPTZ,
            profile_hash VARCHAR(64),
            original_text TEXT
        );
        """,
    ),
    # -----------------------------------------------------------------------
    # 8. 터울주성분픽토그램매핑 (direct copy)
    # -----------------------------------------------------------------------
    (
        "터울주성분픽토그램매핑",
        """
        CREATE TABLE IF NOT EXISTS "터울주성분픽토그램매핑" (
            "매핑ID" SERIAL PRIMARY KEY,
            "심평원성분코드" VARCHAR(450) NOT NULL,
            "픽토그램Code" TEXT NOT NULL,
            "IsDeleted" BOOLEAN NOT NULL DEFAULT FALSE,
            "등록일" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "수정일" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "ModifiedBy" TEXT,
            UNIQUE("심평원성분코드", "픽토그램Code")
        );
        """,
    ),
    # -----------------------------------------------------------------------
    # 9. ProductInfos (direct copy)
    # -----------------------------------------------------------------------
    (
        "ProductInfos",
        """
        CREATE TABLE IF NOT EXISTS "ProductInfos" (
            "ProductCode" VARCHAR(450) UNIQUE NOT NULL,
            "EdiCode" VARCHAR(450),
            "ItemStandardCode" VARCHAR(450),
            "ManufacturerId" INT NOT NULL,
            "AtcCode" VARCHAR(450),
            "Name" VARCHAR(450),
            "BrandId" INT,
            "MasterIngredientCode" TEXT,
            "IngredientCode" TEXT,
            "IngredientCodeWithoutStrength" TEXT,
            "MfdsCode" TEXT,
            "DosageForm" TEXT,
            "DosageFormName" TEXT,
            "Unit" TEXT,
            "Standard" TEXT,
            "Type" TEXT,
            "CoverType" TEXT,
            "색상앞" TEXT,
            "색상뒤" TEXT,
            "표시앞" TEXT,
            "표시뒤" TEXT,
            "식별표시코드앞" TEXT,
            "식별표시코드뒤" TEXT,
            "약품장축길이" TEXT,
            "약품단축길이" TEXT,
            "Name_embedding" VECTOR,
            "CreationDateTime" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "ModificationDate" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "ModifiedBy" TEXT
        );
        """,
    ),
    # -----------------------------------------------------------------------
    # 10. v2 ID 시퀀스 관리 테이블
    # -----------------------------------------------------------------------
    (
        "v2_sequence_registry",
        """
        CREATE TABLE IF NOT EXISTS v2_sequence_registry (
            table_name TEXT PRIMARY KEY,
            sequence_name TEXT NOT NULL,
            last_legacy_id INT,
            v2_start_id INT,
            description TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        """,
    ),
]

TABLE_NAMES = [name for name, _ in DDL_STATEMENTS]

# ---------------------------------------------------------------------------
# 호환성 뷰 — 기존 매핑 테이블을 뷰로 대체
# ---------------------------------------------------------------------------

COMPATIBILITY_VIEWS_SQL: list[tuple[str, str]] = [
    (
        "터울주성분A4복약안내매핑",
        """
        CREATE OR REPLACE VIEW "터울주성분A4복약안내매핑" AS
        SELECT DISTINCT
            i."심평원성분코드",
            a4."복약안내A4ID",
            COALESCE(a4."등록일", NOW()) AS "등록일"
        FROM "터울주성분" i
        JOIN "터울복약안내A4" a4 ON a4.profile_hash = i.profile_hash
        WHERE i."IsDeleted" = FALSE;
        """,
    ),
    (
        "터울주성분A5복약안내매핑",
        """
        CREATE OR REPLACE VIEW "터울주성분A5복약안내매핑" AS
        SELECT DISTINCT
            i."심평원성분코드",
            a5."복약안내A5ID",
            COALESCE(a5."등록일", NOW()) AS "등록일"
        FROM "터울주성분" i
        JOIN "터울복약안내A5" a5 ON a5.profile_hash = i.profile_hash
        WHERE i."IsDeleted" = FALSE;
        """,
    ),
]

VIEW_NAMES = [name for name, _ in COMPATIBILITY_VIEWS_SQL]

# ---------------------------------------------------------------------------
# 마이그레이션 정의
# ---------------------------------------------------------------------------

# columns=None → 런타임에 소스 테이블 컬럼 조회
MIGRATION_TASKS: list[dict] = [
    {
        "source_table": "터울약품분류",
        "dest_table": "터울약품분류",
        "description": "터울약품분류 (1:1 copy)",
        "columns": None,
        "expected_count": 612,
    },
    {
        "source_table": "터울약효설명",
        "dest_table": "터울약효설명",
        "description": "터울약효설명 (legacy 컬럼만 복사, source_type='legacy')",
        "columns": [
            '"약효설명ID"',
            '"터울버전"',
            '"EnglishText"',
            '"ModifiedBy"',
            '"IsDeleted"',
            '"등록일"',
            '"수정일"',
        ],
        "expected_count": 2670,
    },
    {
        "source_table": "Manufacturers",
        "dest_table": "Manufacturers",
        "description": "Manufacturers (1:1 copy)",
        "columns": [
            '"ManufacturerID"',
            '"Name"',
            '"ModificationDate"',
            '"CreationDate"',
            '"Url"',
            '"Name_embedding"',
        ],
        "expected_count": 659,
    },
    {
        "source_table": "터울픽토그램",
        "dest_table": "터울픽토그램",
        "description": "터울픽토그램 (1:1 copy)",
        "columns": None,
        "expected_count": None,  # 건수 미확인 — 런타임 비교
    },
    {
        "source_table": "터울주성분",
        "dest_table": "터울주성분",
        "description": "터울주성분 (기존 컬럼만 복사, 신규 컬럼은 NULL)",
        "columns": [
            '"심평원성분코드"',
            '"약품분류ID"',
            '"약효설명ID"',
            '"성분명"',
            '"sorted_성분명"',
            '"성분명한글"',
            '"고갈영양소영문"',
            '"성분명_임베딩"',
            '"sorted_성분명_embedding"',
            '"ModifiedBy"',
            '"IsDeleted"',
            '"등록일"',
            '"수정일"',
        ],
        "expected_count": 20235,
    },
    {
        "source_table": "터울복약안내A4",
        "dest_table": "터울복약안내A4",
        "description": "터울복약안내A4 (legacy 컬럼만 복사, source_type='legacy')",
        "columns": [
            '"복약안내A4ID"',
            '"터울버전"',
            '"ModifiedBy"',
            '"IsDeleted"',
            '"등록일"',
            '"수정일"',
            '"분류"',
            '"EnglishText"',
            '"픽토그램Code"',
        ],
        "expected_count": None,  # 건수 미확인 — 런타임 비교
    },
    {
        "source_table": "터울복약안내A5",
        "dest_table": "터울복약안내A5",
        "description": "터울복약안내A5 (legacy 컬럼만 복사, source_type='legacy')",
        "columns": [
            '"복약안내A5ID"',
            '"터울버전"',
            '"ModifiedBy"',
            '"IsDeleted"',
            '"등록일"',
            '"수정일"',
            '"분류"',
            '"EnglishText"',
        ],
        "expected_count": None,
    },
    {
        "source_table": "터울주성분픽토그램매핑",
        "dest_table": "터울주성분픽토그램매핑",
        "description": "터울주성분픽토그램매핑 (1:1 copy)",
        "columns": None,
        "expected_count": 17130,
    },
    {
        "source_table": "ProductInfos",
        "dest_table": "ProductInfos",
        "description": "ProductInfos (1:1 copy)",
        "columns": [
            '"ProductCode"',
            '"EdiCode"',
            '"ItemStandardCode"',
            '"ManufacturerId"',
            '"AtcCode"',
            '"Name"',
            '"BrandId"',
            '"MasterIngredientCode"',
            '"IngredientCode"',
            '"IngredientCodeWithoutStrength"',
            '"MfdsCode"',
            '"DosageForm"',
            '"DosageFormName"',
            '"Unit"',
            '"Standard"',
            '"Type"',
            '"CoverType"',
            '"색상앞"',
            '"색상뒤"',
            '"표시앞"',
            '"표시뒤"',
            '"식별표시코드앞"',
            '"식별표시코드뒤"',
            '"약품장축길이"',
            '"약품단축길이"',
            '"Name_embedding"',
            '"CreationDateTime"',
            '"ModificationDate"',
            '"ModifiedBy"',
        ],
        "expected_count": 48027,
    },
]

# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def get_table_columns(conn, table_name: str) -> list[str]:
    """테이블의 실제 컬럼 목록을 DB에서 조회한다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_name,),
        )
        return [f'"{row[0]}"' for row in cur.fetchall()]


def get_existing_tables(conn) -> set[str]:
    """현재 DB의 public 스키마 테이블 목록을 반환한다."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        return {row[0] for row in cur.fetchall()}


def get_existing_views(conn) -> set[str]:
    """현재 DB의 public 스키마 뷰 목록을 반환한다."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT viewname FROM pg_views WHERE schemaname = 'public'"
        )
        return {row[0] for row in cur.fetchall()}


def get_row_count(conn, table_name: str) -> int:
    """테이블(또는 뷰)의 행 수를 반환한다."""
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# DDL 실행
# ---------------------------------------------------------------------------


def drop_existing_objects(v2_conn) -> None:
    """기존 뷰 → 테이블을 역순으로 DROP한다 (FK 의존성 고려)."""
    # 뷰 먼저 DROP
    for view_name in reversed(VIEW_NAMES):
        with v2_conn.cursor() as cur:
            cur.execute(f'DROP VIEW IF EXISTS "{view_name}" CASCADE')
        v2_conn.commit()
        logger.info("DROP VIEW: %s", view_name)

    # 테이블 역순 DROP (FK 참조 순서의 역)
    for table_name in reversed(TABLE_NAMES):
        with v2_conn.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')
        v2_conn.commit()
        logger.info("DROP TABLE: %s", table_name)


def run_ddl(v2_conn, dry_run: bool = False, drop_existing: bool = False) -> int:
    """pgvector extension 활성화 + 테이블 DDL + 호환성 뷰 실행.

    Returns:
        생성된 테이블 수
    """
    if dry_run:
        print("=== DRY RUN: DDL ===\n")
        print("-- pgvector extension")
        print(ENABLE_PGVECTOR.strip())
        print()

        if drop_existing:
            print("-- DROP existing views (reverse order)")
            for view_name in reversed(VIEW_NAMES):
                print(f'DROP VIEW IF EXISTS "{view_name}" CASCADE;')
            print()
            print("-- DROP existing tables (reverse order)")
            for table_name in reversed(TABLE_NAMES):
                print(f'DROP TABLE IF EXISTS "{table_name}" CASCADE;')
            print()

        for i, (name, ddl) in enumerate(DDL_STATEMENTS, 1):
            print(f"-- [{i:02d}] {name}")
            print(ddl.strip())
            print()

        for view_name, view_sql in COMPATIBILITY_VIEWS_SQL:
            print(f"-- VIEW: {view_name}")
            print(view_sql.strip())
            print()
        return 0

    # pgvector extension
    with v2_conn.cursor() as cur:
        cur.execute(ENABLE_PGVECTOR)
    v2_conn.commit()
    logger.info("pgvector extension 활성화 완료")

    # DROP 기존 객체
    if drop_existing:
        logger.info("--drop-existing: 기존 테이블/뷰 삭제 시작")
        drop_existing_objects(v2_conn)

    existing = get_existing_tables(v2_conn)
    created = 0

    for i, (name, ddl) in enumerate(DDL_STATEMENTS, 1):
        if name in existing and not drop_existing:
            logger.info(
                "[%02d/%d] %s — 이미 존재, 건너뜀",
                i,
                len(DDL_STATEMENTS),
                name,
            )
            continue
        with v2_conn.cursor() as cur:
            cur.execute(ddl)
        v2_conn.commit()
        logger.info("[%02d/%d] %s — 생성 완료", i, len(DDL_STATEMENTS), name)
        created += 1

    # 호환성 뷰
    for view_name, view_sql in COMPATIBILITY_VIEWS_SQL:
        with v2_conn.cursor() as cur:
            cur.execute(view_sql)
        v2_conn.commit()
        logger.info("VIEW %s 생성 완료", view_name)

    logger.info(
        "DDL 완료: 신규 %d개, 기존 %d개 (건너뜀)",
        created,
        len(TABLE_NAMES) - created,
    )
    return created


# ---------------------------------------------------------------------------
# 시퀀스 초기화 (새 ID가 레거시와 충돌하지 않도록)
# ---------------------------------------------------------------------------


def sync_sequences(v2_conn) -> None:
    """SERIAL 컬럼의 시퀀스를 현재 MAX(id) + 1 이상으로 설정한다."""
    serial_tables = [
        ("터울약품분류", "약품분류ID"),
        ("터울약효설명", "약효설명ID"),
        ("터울복약안내A4", "복약안내A4ID"),
        ("터울복약안내A5", "복약안내A5ID"),
        ("터울주성분픽토그램매핑", "매핑ID"),
    ]
    for table_name, pk_col in serial_tables:
        try:
            with v2_conn.cursor() as cur:
                cur.execute(
                    f'SELECT MAX("{pk_col}") FROM "{table_name}"'
                )
                max_id = cur.fetchone()[0]
                if max_id is not None:
                    # pg_get_serial_sequence 로 시퀀스명 찾기
                    cur.execute(
                        "SELECT pg_get_serial_sequence(%s, %s)",
                        (table_name, pk_col),
                    )
                    seq_name = cur.fetchone()[0]
                    if seq_name:
                        cur.execute(
                            f"SELECT setval('{seq_name}', %s, true)",
                            (max_id,),
                        )
                        logger.info(
                            "시퀀스 동기화: %s.%s → %d",
                            table_name,
                            pk_col,
                            max_id,
                        )
                        # v2_sequence_registry에 기록
                        cur.execute(
                            """
                            INSERT INTO v2_sequence_registry
                                (table_name, sequence_name, last_legacy_id, v2_start_id, description)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (table_name) DO UPDATE SET
                                last_legacy_id = EXCLUDED.last_legacy_id,
                                v2_start_id = EXCLUDED.v2_start_id
                            """,
                            (
                                table_name,
                                seq_name,
                                max_id,
                                max_id + 1,
                                f"Legacy max {pk_col} = {max_id}",
                            ),
                        )
            v2_conn.commit()
        except Exception as e:
            logger.warning("시퀀스 동기화 실패 (%s): %s", table_name, e)
            v2_conn.rollback()


# ---------------------------------------------------------------------------
# 데이터 마이그레이션
# ---------------------------------------------------------------------------


def migrate_table(
    src_conn,
    dst_conn,
    task: dict,
    dry_run: bool = False,
) -> int:
    """단일 테이블을 src → dst로 복사한다 (배치 5000건).

    source_type='legacy' 기본값은 DDL DEFAULT로 자동 적용됨.

    Returns:
        복사된 행 수
    """
    src_table = task["source_table"]
    dst_table = task["dest_table"]
    desc = task["description"]
    columns = task["columns"]

    if dry_run:
        col_display = (
            ", ".join(columns) if columns else "<런타임 조회>"
        )
        print(f"-- MIGRATE: {desc}")
        print(f'INSERT INTO "{dst_table}" ({col_display})')
        print(f'SELECT {col_display} FROM "{src_table}"')
        print("ON CONFLICT DO NOTHING;")
        print()
        return 0

    # columns=None이면 소스 테이블 컬럼을 런타임 조회
    if columns is None:
        columns = get_table_columns(src_conn, src_table)

    col_list = ", ".join(columns)

    # 목적 테이블에 이미 데이터가 있으면 건너뜀
    dst_count = get_row_count(dst_conn, dst_table)
    if dst_count > 0:
        logger.info(
            "SKIP %s — 목적 테이블에 이미 %d건 존재",
            dst_table,
            dst_count,
        )
        return 0

    src_count = get_row_count(src_conn, src_table)
    logger.info("마이그레이션 시작: %s (%d건)", desc, src_count)

    if src_count == 0:
        logger.info("소스 테이블 %s 비어 있음, 건너뜀", src_table)
        return 0

    # INSERT 준비
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = (
        f'INSERT INTO "{dst_table}" ({col_list}) VALUES ({placeholders}) '
        f"ON CONFLICT DO NOTHING"
    )

    offset = 0
    total_inserted = 0

    with src_conn.cursor() as src_cur:
        while True:
            src_cur.execute(
                f"SELECT {col_list} FROM \"{src_table}\" "
                f"ORDER BY 1 LIMIT %s OFFSET %s",
                (BATCH_SIZE, offset),
            )
            rows = src_cur.fetchall()
            if not rows:
                break

            with dst_conn.cursor() as dst_cur:
                dst_cur.executemany(insert_sql, rows)
            dst_conn.commit()

            total_inserted += len(rows)
            offset += BATCH_SIZE
            logger.info(
                "  %s: %d / %d 건 복사",
                src_table,
                total_inserted,
                src_count,
            )

    logger.info("마이그레이션 완료: %s → %d건", dst_table, total_inserted)
    return total_inserted


def post_migrate_set_source_type(dst_conn) -> None:
    """마이그레이션 후 source_type='legacy' 일괄 설정.

    DDL DEFAULT가 이미 'legacy'이지만, 명시적으로 UPDATE하여 확실하게 한다.
    """
    tables_with_source_type = ["터울약효설명", "터울복약안내A4", "터울복약안내A5"]
    for table_name in tables_with_source_type:
        try:
            with dst_conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE "{table_name}"
                    SET source_type = 'legacy'
                    WHERE source_type IS NULL OR source_type = 'legacy'
                    """
                )
                updated = cur.rowcount
            dst_conn.commit()
            logger.info(
                "source_type='legacy' 설정: %s → %d건",
                table_name,
                updated,
            )
        except Exception as e:
            logger.warning("source_type 설정 실패 (%s): %s", table_name, e)
            dst_conn.rollback()


def run_migration(src_conn, dst_conn, dry_run: bool = False) -> dict[str, int]:
    """모든 마이그레이션 태스크를 순서대로 실행한다.

    Returns:
        {table_name: row_count} 결과 맵
    """
    if dry_run:
        print("=== DRY RUN: MIGRATION ===\n")

    results: dict[str, int] = {}
    for task in MIGRATION_TASKS:
        count = migrate_table(src_conn, dst_conn, task, dry_run=dry_run)
        results[task["dest_table"]] = count

    if not dry_run:
        # 마이그레이션 후처리
        post_migrate_set_source_type(dst_conn)
        # 시퀀스 동기화
        sync_sequences(dst_conn)

    return results


# ---------------------------------------------------------------------------
# 검증
# ---------------------------------------------------------------------------


def run_verify(src_conn, dst_conn) -> bool:
    """소스 DB와 v2 DB의 행 수를 비교한다.

    Returns:
        모든 마이그레이션 테이블이 일치하면 True
    """
    print("\n=== 마이그레이션 검증 ===\n")
    print(f"{'테이블':<35} {'소스':>10} {'v2':>10} {'예상':>10} {'상태':>6}")
    print("-" * 75)

    all_ok = True
    for task in MIGRATION_TASKS:
        src_table = task["source_table"]
        dst_table = task["dest_table"]
        expected = task["expected_count"]

        try:
            src_count = get_row_count(src_conn, src_table)
        except Exception:
            src_count = -1

        try:
            dst_count = get_row_count(dst_conn, dst_table)
        except Exception:
            dst_count = -1

        ok = src_count == dst_count and dst_count > 0
        mark = "OK" if ok else "NG"
        if not ok:
            all_ok = False

        expected_str = f"{expected:>10,}" if expected else f"{'N/A':>10}"
        print(
            f"{dst_table:<35} {src_count:>10,} {dst_count:>10,} {expected_str} {mark:>6}"
        )

        if expected and src_count != expected:
            print(
                f"  [WARN] 소스 행 수 {src_count:,} != 예상 {expected:,}"
            )

    # 뷰 존재 확인
    print()
    print("--- 호환성 뷰 ---")
    existing_views = get_existing_views(dst_conn)
    for view_name in VIEW_NAMES:
        exists = view_name in existing_views
        mark = "OK" if exists else "NG"
        if not exists:
            all_ok = False
        print(f"  {view_name:<40} {mark}")

    # v2 전용 테이블 확인
    print()
    print("--- v2 전체 테이블 ---")
    existing_tables = get_existing_tables(dst_conn)
    for table_name in TABLE_NAMES:
        exists = table_name in existing_tables
        mark = "OK" if exists else "NG"
        if not exists:
            all_ok = False
        row_count = get_row_count(dst_conn, table_name) if exists else 0
        print(f"  {table_name:<40} {row_count:>10,} {mark}")

    print()
    if all_ok:
        logger.info("검증 통과: 모든 테이블/뷰 확인 완료")
    else:
        logger.error("검증 실패: 일부 테이블/뷰 불일치 또는 누락")

    return all_ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Phase 2-A: teoul_pharminfo_v2 DDL + 데이터 마이그레이션",
    )
    parser.add_argument(
        "--create-only",
        action="store_true",
        help="DDL만 실행 (마이그레이션 건너뜀)",
    )
    parser.add_argument(
        "--migrate-only",
        action="store_true",
        help="데이터 마이그레이션만 실행 (DDL 건너뜀)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="SQL만 출력, DB에 실행하지 않음",
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="기존 테이블/뷰 DROP 후 재생성",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="v2 데이터가 소스 건수와 일치하는지 검증",
    )
    args = parser.parse_args()

    # 상호 배타 검증
    if args.create_only and args.migrate_only:
        parser.error("--create-only 와 --migrate-only 는 동시에 사용할 수 없습니다")

    # --dry-run: DB 연결 없이 SQL 출력
    if args.dry_run:
        run_ddl(None, dry_run=True, drop_existing=args.drop_existing)
        run_migration(None, None, dry_run=True)
        return

    src_conn = get_connection()
    v2_conn = get_v2_connection()

    try:
        # --verify: 검증만 실행 후 종료
        if args.verify:
            ok = run_verify(src_conn, v2_conn)
            sys.exit(0 if ok else 1)

        do_ddl = not args.migrate_only
        do_migrate = not args.create_only

        # DDL
        if do_ddl:
            created = run_ddl(
                v2_conn,
                drop_existing=args.drop_existing,
            )
            logger.info("DDL 단계 완료: %d개 테이블 생성", created)

        # Migration
        if do_migrate:
            results = run_migration(src_conn, v2_conn)
            total = sum(results.values())
            logger.info(
                "마이그레이션 완료: %d개 테이블, 총 %d건 복사",
                len(results),
                total,
            )

        # 최종 요약
        existing_tables = get_existing_tables(v2_conn)
        present = [t for t in TABLE_NAMES if t in existing_tables]
        missing = [t for t in TABLE_NAMES if t not in existing_tables]
        logger.info(
            "v2 DB 테이블 현황: %d / %d",
            len(present),
            len(TABLE_NAMES),
        )
        if missing:
            logger.error("누락 테이블: %s", ", ".join(missing))
            sys.exit(1)

        existing_views = get_existing_views(v2_conn)
        view_present = [v for v in VIEW_NAMES if v in existing_views]
        logger.info(
            "v2 DB 뷰 현황: %d / %d",
            len(view_present),
            len(VIEW_NAMES),
        )

        logger.info("Phase 2-A 완료")

    finally:
        src_conn.close()
        v2_conn.close()


if __name__ == "__main__":
    main()
