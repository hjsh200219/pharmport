"""
pharmport_medicine.ingredients 와 터울주성분.성분명을
알파벳순 정렬 후 임베딩하여 새 컬럼에 저장하는 스크립트.

새 컬럼:
  - pharmport_medicine.sorted_ingredients (text) — 정렬된 성분 텍스트
  - pharmport_medicine.sorted_ingredient_embedding (vector) — 정렬 텍스트 임베딩
  - 터울주성분.sorted_성분명 (text) — 정렬된 성분명 텍스트
  - 터울주성분.sorted_성분명_embedding (vector) — 정렬 텍스트 임베딩

Usage:
  python sort_and_embed.py                # 두 테이블 모두 (병렬)
  python sort_and_embed.py --medicine     # pharmport_medicine만
  python sort_and_embed.py --ingredient   # 터울주성분만
  python sort_and_embed.py --dry-run      # DB 저장 없이 정렬만 확인
  python sort_and_embed.py --workers 12   # 임베딩 동시 요청 수 조절
"""

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from psycopg2.extras import execute_batch

from common import get_connection
from embedding_service import sort_ingredients, get_embeddings_parallel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DB_BATCH_SIZE = 200


def ensure_column_exists(conn, table: str, column: str, col_type: str):
    """컬럼이 없으면 추가한다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            (table, column),
        )
        if not cur.fetchone():
            cur.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {col_type}')
            conn.commit()
            logger.info("컬럼 추가: %s.%s (%s)", table, column, col_type)


def _fetch_and_sort(conn, query: str) -> tuple[list, list[str]]:
    """DB에서 조회 후 성분 텍스트를 정렬한다. (ids, sorted_texts) 반환."""
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()

    ids = [r[0] for r in rows]
    sorted_texts = [sort_ingredients(r[1]) for r in rows]
    return ids, sorted_texts


def _bulk_update(conn, table, id_col, text_col, embed_col, ids, sorted_texts, embeddings):
    """execute_batch로 벌크 업데이트한다."""
    query = f'UPDATE "{table}" SET "{text_col}" = %s, "{embed_col}" = %s WHERE "{id_col}" = %s'
    params = [
        (text, str(emb), pk)
        for pk, text, emb in zip(ids, sorted_texts, embeddings)
    ]

    total = len(params)
    for start in range(0, total, DB_BATCH_SIZE):
        end = min(start + DB_BATCH_SIZE, total)
        with conn.cursor() as cur:
            execute_batch(cur, query, params[start:end], page_size=DB_BATCH_SIZE)
        conn.commit()
        logger.info("[%s] DB 저장: %d / %d", table, end, total)


def process_medicine(conn, workers: int, dry_run: bool = False):
    """pharmport_medicine 테이블 처리."""
    if not dry_run:
        ensure_column_exists(conn, "pharmport_medicine", "sorted_ingredients", "text")
        ensure_column_exists(conn, "pharmport_medicine", "sorted_ingredient_embedding", "vector(3072)")

    ids, sorted_texts = _fetch_and_sort(conn, """
        SELECT medicine_id, ingredients
        FROM pharmport_medicine
        WHERE ingredients IS NOT NULL AND ingredients != ''
        ORDER BY medicine_id
    """)

    logger.info("pharmport_medicine 처리 대상: %d건", len(ids))
    if not ids:
        return

    if dry_run:
        _print_dry_run_samples(ids, sorted_texts, "ingredients")
        return

    t0 = time.time()
    embeddings = get_embeddings_parallel(sorted_texts, workers=workers)
    logger.info("[pharmport_medicine] 임베딩 완료: %.1f초", time.time() - t0)

    t1 = time.time()
    _bulk_update(conn, "pharmport_medicine", "medicine_id",
                 "sorted_ingredients", "sorted_ingredient_embedding",
                 ids, sorted_texts, embeddings)
    logger.info("[pharmport_medicine] DB 저장 완료: %.1f초", time.time() - t1)


def process_ingredient(conn, workers: int, dry_run: bool = False):
    """터울주성분 테이블 처리."""
    if not dry_run:
        ensure_column_exists(conn, "터울주성분", "sorted_성분명", "text")
        ensure_column_exists(conn, "터울주성분", "sorted_성분명_embedding", "vector(3072)")

    ids, sorted_texts = _fetch_and_sort(conn, """
        SELECT "심평원성분코드", "성분명"
        FROM "터울주성분"
        WHERE "성분명" IS NOT NULL AND "성분명" != ''
          AND "sorted_성분명" IS NULL
        ORDER BY "심평원성분코드"
    """)

    logger.info("터울주성분 처리 대상: %d건", len(ids))
    if not ids:
        return

    if dry_run:
        _print_dry_run_samples(ids, sorted_texts, "성분명")
        return

    t0 = time.time()
    embeddings = get_embeddings_parallel(sorted_texts, workers=workers)
    logger.info("[터울주성분] 임베딩 완료: %.1f초", time.time() - t0)

    t1 = time.time()
    _bulk_update(conn, "터울주성분", "심평원성분코드",
                 "sorted_성분명", "sorted_성분명_embedding",
                 ids, sorted_texts, embeddings)
    logger.info("[터울주성분] DB 저장 완료: %.1f초", time.time() - t1)


def _print_dry_run_samples(ids, sorted_texts, col_name):
    logger.info("=== Dry Run 샘플 (처음 5건) ===")
    for i in range(min(5, len(ids))):
        logger.info("[%s] 정렬 %s: %s", ids[i], col_name, sorted_texts[i])


def main():
    parser = argparse.ArgumentParser(description="성분 정렬 후 임베딩 저장 (병렬)")
    parser.add_argument("--medicine", action="store_true", help="pharmport_medicine만 처리")
    parser.add_argument("--ingredient", action="store_true", help="터울주성분만 처리")
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 없이 정렬만 확인")
    parser.add_argument("--workers", type=int, default=8, help="임베딩 동시 요청 수 (기본: 8)")
    args = parser.parse_args()

    process_both = not args.medicine and not args.ingredient

    t_start = time.time()
    logger.info("시작 (workers=%d)", args.workers)

    try:
        if process_both:
            _run_both_parallel(args.workers, args.dry_run)
        elif args.medicine:
            conn = get_connection()
            try:
                process_medicine(conn, args.workers, dry_run=args.dry_run)
            finally:
                conn.close()
        elif args.ingredient:
            conn = get_connection()
            try:
                process_ingredient(conn, args.workers, dry_run=args.dry_run)
            finally:
                conn.close()

        elapsed = time.time() - t_start
        logger.info("전체 완료! (소요시간: %.1f초 = %.1f분)", elapsed, elapsed / 60)
    except Exception as e:
        logger.error("처리 중 오류 발생: %s", e)
        sys.exit(1)


def _run_both_parallel(workers: int, dry_run: bool):
    """두 테이블을 스레드로 동시 처리한다."""
    half = max(2, workers // 2)

    def run_medicine():
        conn = get_connection()
        try:
            process_medicine(conn, half, dry_run=dry_run)
        finally:
            conn.close()

    def run_ingredient():
        conn = get_connection()
        try:
            process_ingredient(conn, half, dry_run=dry_run)
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(run_medicine)
        f2 = pool.submit(run_ingredient)
        f1.result()
        f2.result()


if __name__ == "__main__":
    main()
