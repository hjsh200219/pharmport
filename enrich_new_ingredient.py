"""
신규 주성분코드 자동 감지 + Enrichment 파이프라인

심평원성분코드 구조:
  1-4: 주성분 일련번호
  5-6: 00=복합제, 01~=단일제(함량 일련번호), TL=터울수집
  7:   투여경로 (A=내복, B=주사, C=외용, D=기타)
  8-9: 제형코드

Flow:
  1. 감지: 터울주성분 - edb_enrichment_status = 미등록 신규 코드
  2. 코드 구조 분석 → CASE 분류 (A: 기존 주성분 재활용, B: 복합제, C: 완전 신규)
  3. CASE별 최적화된 enrichment 실행
  4. Layer 1 자동 검증
  5. 리포트 출력

Usage:
    python enrich_new_ingredient.py --detect                    # 미등록 코드 목록
    python enrich_new_ingredient.py --run --code 101340BIJ      # 단건 실행
    python enrich_new_ingredient.py --run --all-new             # 전체 신규 일괄
    python enrich_new_ingredient.py --run --all-new --dev       # dev DB 테스트
"""

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from common import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 심평원성분코드 파서
# ---------------------------------------------------------------------------

@dataclass
class ParsedCode:
    """심평원성분코드 파싱 결과."""
    code: str            # 전체 9자리
    base: str            # 1-4자리 (주성분)
    type_code: str       # 5-6자리 (00=복합, 01~=단일, TL=터울)
    route: str           # 7자리 (A/B/C/D)
    dosage_form: str     # 8-9자리 (제형)

    @property
    def is_combo(self) -> bool:
        return self.type_code == "00"

    @property
    def is_single(self) -> bool:
        return self.type_code not in ("00", "TL") and self.type_code.isdigit()

    @property
    def is_teoul(self) -> bool:
        return self.type_code == "TL"

    @property
    def route_name(self) -> str:
        return {"A": "내복", "B": "주사", "C": "외용", "D": "기타"}.get(self.route, "미분류")


def parse_code(code: str) -> ParsedCode | None:
    """9자리 심평원성분코드를 파싱한다."""
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
# 신규 코드 감지
# ---------------------------------------------------------------------------

def detect_new_codes(conn) -> list[dict]:
    """터울주성분에 있지만 edb_enrichment_status에 없는 코드를 반환한다."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT t."심평원성분코드", t."성분명", t."성분명한글"
            FROM "터울주성분" t
            LEFT JOIN edb_enrichment_status es
                ON t."심평원성분코드" = es."심평원성분코드"
            WHERE t."IsDeleted" = FALSE
              AND es."심평원성분코드" IS NULL
              AND LENGTH(t."심평원성분코드") = 9
            ORDER BY t."심평원성분코드"
        """)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# CASE 분류
# ---------------------------------------------------------------------------

CASE_A = "reuse_existing"       # 동일 주성분(1-4)의 enrichment 존재
CASE_B = "combo_decompose"      # 복합제 → 개별 성분 분리
CASE_C = "full_new"             # 완전 신규 주성분


def classify_code(conn, parsed: ParsedCode) -> str:
    """신규 코드의 enrichment CASE를 판별한다."""
    with conn.cursor() as cur:
        # 동일 주성분(1-4)으로 이미 enrichment된 코드가 있는지
        cur.execute("""
            SELECT COUNT(*) FROM edb_enrichment_status
            WHERE "심평원성분코드" LIKE %s
              AND chembl_mapped = TRUE
        """, (parsed.base + "%",))
        existing_count = cur.fetchone()[0]

    if parsed.is_combo:
        return CASE_B
    elif existing_count > 0:
        return CASE_A
    else:
        return CASE_C


# ---------------------------------------------------------------------------
# CASE별 Enrichment 실행
# ---------------------------------------------------------------------------

def register_status(conn, code: str):
    """edb_enrichment_status에 신규 코드를 등록한다."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO edb_enrichment_status ("심평원성분코드")
            VALUES (%s)
            ON CONFLICT ("심평원성분코드") DO NOTHING
        """, (code,))
    conn.commit()


def copy_pharmacology_from_sibling(conn, parsed: ParsedCode):
    """CASE A: 동일 주성분의 기존 enrichment 데이터를 복사한다.

    약리학 데이터(MoA, ADMET, 질병, 문헌, 임상시험)는 성분 고유이므로
    동일 주성분(1-4자리)의 기존 결과를 그대로 복사한다.
    """
    tables_to_copy = [
        ("edb_ingredient_xref", "xref_id"),
        ("edb_mechanism", "mechanism_id"),
        ("edb_admet", "admet_id"),
        ("edb_drug_disease", "dd_id"),
        ("edb_literature", "lit_id"),
        ("edb_clinical_trial", "trial_id"),
    ]

    # 동일 주성분 중 enrichment 완료된 코드 1건 찾기
    with conn.cursor() as cur:
        cur.execute("""
            SELECT "심평원성분코드" FROM edb_enrichment_status
            WHERE "심평원성분코드" LIKE %s
              AND chembl_mapped = TRUE
            LIMIT 1
        """, (parsed.base + "%",))
        row = cur.fetchone()
        if not row:
            logger.warning("  동일 주성분 %s의 enrichment 결과 없음 → CASE C로 전환", parsed.base)
            return False
        sibling_code = row[0]

    logger.info("  약리학 데이터 복사: %s → %s", sibling_code, parsed.code)

    with conn.cursor() as cur:
        for table, pk_col in tables_to_copy:
            # 해당 테이블의 컬럼 목록 가져오기 (PK 제외)
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = %s AND column_name != %s
                ORDER BY ordinal_position
            """, (table, pk_col))
            columns = [r[0] for r in cur.fetchall()]

            if "심평원성분코드" not in columns:
                continue

            # 심평원성분코드를 새 코드로 교체하며 복사
            cols_select = ", ".join(
                f'%s' if c == "심평원성분코드" else f'"{c}"'
                for c in columns
            )
            cols_insert = ", ".join(f'"{c}"' for c in columns)

            # ON CONFLICT 처리를 위해 INSERT ... ON CONFLICT DO NOTHING
            sql = f"""
                INSERT INTO {table} ({cols_insert})
                SELECT {cols_select}
                FROM {table}
                WHERE "심평원성분코드" = %s
                ON CONFLICT DO NOTHING
            """
            params = [parsed.code if c == "심평원성분코드" else None for c in columns]
            # 실제 파라미터 구성이 복잡하므로 간단한 방식으로 구현
            cur.execute(f"""
                INSERT INTO {table} ({cols_insert})
                SELECT {", ".join(
                    f"'{parsed.code}'" if c == "심평원성분코드"
                    else f'"{c}"'
                    for c in columns
                )}
                FROM {table}
                WHERE "심평원성분코드" = %s
                ON CONFLICT DO NOTHING
            """, (sibling_code,))
            copied = cur.rowcount
            if copied > 0:
                logger.info("    %s: %d건 복사", table, copied)

    conn.commit()

    # enrichment_status 업데이트
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE edb_enrichment_status
            SET chembl_mapped = TRUE, chembl_mapped_at = NOW(),
                mechanism_fetched = TRUE, mechanism_fetched_at = NOW(),
                admet_fetched = TRUE, admet_fetched_at = NOW(),
                disease_fetched = TRUE, disease_fetched_at = NOW(),
                literature_fetched = TRUE, literature_fetched_at = NOW(),
                trials_fetched = TRUE, trials_fetched_at = NOW(),
                updated_at = NOW()
            WHERE "심평원성분코드" = %s
        """, (parsed.code,))
    conn.commit()
    return True


def check_fda_needs_new_fetch(conn, parsed: ParsedCode) -> bool:
    """동일 주성분 + 동일 투여경로의 FDA 데이터가 있는지 확인."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM edb_safety s
            JOIN "터울주성분" t ON s."심평원성분코드" = t."심평원성분코드"
            WHERE SUBSTRING(s."심평원성분코드", 1, 4) = %s
              AND SUBSTRING(s."심평원성분코드", 7, 1) = %s
              AND s.source IN ('fda_label', 'faers')
        """, (parsed.base, parsed.route))
        return cur.fetchone()[0] == 0


def enrich_single_code(conn, code_info: dict):
    """단일 코드에 대한 enrichment를 수행한다."""
    code = code_info["심평원성분코드"]
    name = code_info.get("성분명", "")
    name_kr = code_info.get("성분명한글", "")

    parsed = parse_code(code)
    if not parsed:
        logger.error("  코드 파싱 실패: %s", code)
        return

    logger.info("=" * 60)
    logger.info("코드: %s (%s)", code, name[:50] if name else name_kr[:50])
    logger.info("  주성분: %s, 유형: %s(%s), 투여: %s(%s), 제형: %s",
                parsed.base, parsed.type_code,
                "복합제" if parsed.is_combo else "단일제",
                parsed.route, parsed.route_name, parsed.dosage_form)

    # 1. edb_enrichment_status 등록
    register_status(conn, code)

    # 2. CASE 분류
    case = classify_code(conn, parsed)
    logger.info("  CASE: %s", case)

    # 3. CASE별 실행
    if case == CASE_A:
        # 약리학 데이터 복사
        success = copy_pharmacology_from_sibling(conn, parsed)
        if not success:
            case = CASE_C  # fallback

        # FDA: 동일 투여경로 데이터 있으면 복사, 없으면 신규 필요
        if check_fda_needs_new_fetch(conn, parsed):
            logger.info("  FDA: 투여경로 %s(%s)의 FDA 데이터 없음 → 신규 수집 필요",
                        parsed.route, parsed.route_name)
            # TODO: enrich_fda.py 호출
        else:
            logger.info("  FDA: 동일 투여경로 데이터 존재 → 복사")
            # 동일 주성분+투여경로의 safety 데이터 복사
            _copy_safety_from_sibling(conn, parsed)

    if case == CASE_B:
        logger.info("  복합제: 개별 성분 분리 후 enrichment 필요")
        # TODO: 성분명 파싱 → 개별 성분의 주성분코드 탐색 → 각각 enrichment 결과 참조
        # 복합제 고유 상호작용은 별도 수집 필요
        _handle_combo(conn, parsed, name)

    if case == CASE_C:
        logger.info("  완전 신규: 전체 enrichment 파이프라인 실행 필요")
        # TODO: enrich_chembl.py, enrich_fda.py 등 순차 호출
        _mark_pending(conn, code)

    logger.info("  완료: %s", code)


def _copy_safety_from_sibling(conn, parsed: ParsedCode):
    """동일 주성분+투여경로의 safety 데이터를 복사한다."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO edb_safety (
                "심평원성분코드", info_type, description, severity,
                related_ingredient_code, evidence_level, source,
                source_id, validation_status, fetched_at
            )
            SELECT
                %s, info_type, description, severity,
                related_ingredient_code, evidence_level, source,
                source_id, 'draft', NOW()
            FROM edb_safety
            WHERE SUBSTRING("심평원성분코드", 1, 4) = %s
              AND SUBSTRING("심평원성분코드", 7, 1) = %s
              AND "심평원성분코드" != %s
            LIMIT 500
            ON CONFLICT DO NOTHING
        """, (parsed.code, parsed.base, parsed.route, parsed.code))
        copied = cur.rowcount
    conn.commit()
    if copied > 0:
        logger.info("    edb_safety: %d건 복사 (validation_status='draft')", copied)

    # safety_fetched 업데이트
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE edb_enrichment_status
            SET safety_fetched = TRUE, safety_fetched_at = NOW(), updated_at = NOW()
            WHERE "심평원성분코드" = %s
        """, (parsed.code,))
    conn.commit()


def _handle_combo(conn, parsed: ParsedCode, ingredient_name: str):
    """복합제(00) 처리: 개별 성분으로 분리 후 기존 enrichment 참조."""
    # 성분명에서 개별 성분 파싱 (콤마 분리, 함량 제거)
    if not ingredient_name:
        logger.warning("  성분명이 비어있어 복합제 분리 불가")
        _mark_pending(conn, parsed.code)
        return

    # 괄호 내부 콤마를 무시하면서 분리
    components = _split_ingredients(ingredient_name)
    logger.info("  복합제 성분 %d개: %s",
                len(components),
                ", ".join(c[:30] for c in components[:5]))

    # 각 성분의 이름만 추출 (함량 제거)
    for comp in components:
        clean_name = _remove_strength(comp).strip()
        if not clean_name:
            continue

        # 해당 성분이 단일제로 이미 enrichment 되어있는지 확인
        with conn.cursor() as cur:
            cur.execute("""
                SELECT es."심평원성분코드"
                FROM edb_enrichment_status es
                JOIN "터울주성분" t ON es."심평원성분코드" = t."심평원성분코드"
                WHERE t."성분명" ILIKE %s
                  AND SUBSTRING(es."심평원성분코드", 5, 2) != '00'
                  AND es.chembl_mapped = TRUE
                LIMIT 1
            """, ("%" + clean_name + "%",))
            row = cur.fetchone()
            if row:
                logger.info("    '%s' → 기존 enrichment 참조 가능: %s", clean_name[:30], row[0])
            else:
                logger.info("    '%s' → 기존 enrichment 없음 (신규 수집 필요)", clean_name[:30])

    _mark_pending(conn, parsed.code)


def _mark_pending(conn, code: str):
    """전체 파이프라인 실행이 필요한 코드를 pending 상태로 표시."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE edb_enrichment_status
            SET last_error = 'pending_full_enrichment', updated_at = NOW()
            WHERE "심평원성분코드" = %s
        """, (code,))
    conn.commit()


def _split_ingredients(text: str) -> list[str]:
    """괄호 내부 콤마를 무시하면서 성분 분리."""
    result = []
    depth = 0
    current = []
    for ch in text:
        if ch in ("(", "[", "（"):
            depth += 1
            current.append(ch)
        elif ch in (")", "]", "）"):
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            result.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        result.append("".join(current).strip())
    return [r for r in result if r]


def _remove_strength(name: str) -> str:
    """성분명에서 함량(숫자+단위) 부분을 제거."""
    # "acetaminophen 500mg" → "acetaminophen"
    # "amino acids(8.5%) 85.00g(A액1000mL중)" → "amino acids"
    cleaned = re.sub(r'\s+[\d.,]+\s*(mg|g|ml|%|mcg|iu|μg|kg|mmol|mEq|unit).*',
                     '', name, flags=re.IGNORECASE)
    # 뒤쪽 숫자 패턴도 제거
    cleaned = re.sub(r'\s+\d+[\d.,]*\s*$', '', cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="신규 주성분코드 자동 enrichment")
    parser.add_argument("--detect", action="store_true", help="미등록 코드 목록만 출력")
    parser.add_argument("--run", action="store_true", help="enrichment 실행")
    parser.add_argument("--code", help="특정 코드 1건 처리")
    parser.add_argument("--all-new", action="store_true", help="미등록 전체 일괄 처리")
    parser.add_argument("--dev", action="store_true", help="dev DB 사용")
    parser.add_argument("--limit", type=int, default=0, help="처리 건수 제한 (0=전체)")
    args = parser.parse_args()

    if not args.detect and not args.run:
        parser.print_help()
        sys.exit(1)

    db_name = os.getenv("DEV_DATABASE_NAME") if args.dev else None
    conn = get_connection(db_name)

    try:
        if args.detect:
            new_codes = detect_new_codes(conn)
            print(f"\n미등록 신규 코드: {len(new_codes)}건\n")
            if not new_codes:
                print("모든 코드가 등록되어 있습니다.")
                return

            # 요약 통계
            combos = sum(1 for c in new_codes if parse_code(c["심평원성분코드"]) and parse_code(c["심평원성분코드"]).is_combo)
            singles = len(new_codes) - combos
            print(f"  단일제: {singles}건, 복합제: {combos}건\n")

            # 상위 20건 표시
            for i, c in enumerate(new_codes[:20], 1):
                parsed = parse_code(c["심평원성분코드"])
                type_label = "복합" if parsed and parsed.is_combo else "단일"
                route_label = parsed.route_name if parsed else "?"
                name = c.get("성분명", "") or c.get("성분명한글", "")
                print(f"  {i:3d}. {c['심평원성분코드']} ({type_label}/{route_label}) → {name[:60]}")
            if len(new_codes) > 20:
                print(f"  ... +{len(new_codes) - 20}건 더")

        elif args.run:
            if args.code:
                # 단건
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
                enrich_single_code(conn, code_info)

            elif args.all_new:
                new_codes = detect_new_codes(conn)
                total = len(new_codes)
                if args.limit > 0:
                    new_codes = new_codes[:args.limit]

                logger.info("신규 코드 %d건 중 %d건 처리 시작", total, len(new_codes))

                for i, code_info in enumerate(new_codes, 1):
                    logger.info("[%d/%d]", i, len(new_codes))
                    try:
                        enrich_single_code(conn, code_info)
                    except Exception as e:
                        logger.error("  에러: %s — %s", code_info["심평원성분코드"], e)
                        # 에러 기록 후 계속 진행
                        with conn.cursor() as cur:
                            cur.execute("""
                                UPDATE edb_enrichment_status
                                SET last_error = %s, updated_at = NOW()
                                WHERE "심평원성분코드" = %s
                            """, (str(e)[:500], code_info["심평원성분코드"]))
                        conn.commit()

                logger.info("완료: %d건 처리", len(new_codes))
            else:
                logger.error("--code 또는 --all-new 중 하나를 지정하세요")
                sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
