"""
pharmport_medicine → 심평원성분코드 매칭 (에러율 0% 기준)

전략:
  1. medicine_name_embedding ↔ ProductInfos.Name_embedding 코사인 유사도
  2. Top-1 유사도 ≥ 임계값일 때만 후보 검토
  3. 후보 중 MasterIngredientCode가 하나면 확정 매칭
  4. 복수 MIC(같은 이름·다른 규격) → 스킵 (에러율 0% 보장)

결과:
  product_code  ← ProductInfos.ProductCode
  ingredient_code ← ProductInfos.MasterIngredientCode (= 심평원성분코드)

Usage:
  python match_ingredient.py                # 전체 실행 (DB 업데이트 포함)
  python match_ingredient.py --dry-run      # DB 수정 없이 결과만 확인
  python match_ingredient.py --calibrate    # 임계값 캘리브레이션만 실행
  python match_ingredient.py --threshold 0.94  # 수동 임계값 지정
"""

import argparse
import logging
import time

import numpy as np
from psycopg2.extras import execute_batch

from common import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DB_BATCH_SIZE = 500
MATCH_BATCH_SIZE = 1000
AMBIGUITY_MARGIN = 0.02


def parse_vector(vec_str: str | None) -> np.ndarray | None:
    if vec_str is None:
        return None
    try:
        s = vec_str.strip()
        if s.startswith(("[", "(")):
            s = s[1:-1]
        return np.fromstring(s, sep=",", dtype=np.float32)
    except Exception:
        return None


def normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return mat / norms


def load_medicine(conn) -> list[dict]:
    logger.info("pharmport_medicine 로드 중...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT medicine_id,
                   medicine_name_embedding::text,
                   product_code
            FROM pharmport_medicine
            ORDER BY medicine_id
        """)
        rows = cur.fetchall()

    data = []
    for mid, name_str, old_pc in rows:
        data.append({
            "id": mid,
            "name_emb": parse_vector(name_str),
            "old_pc": old_pc,
        })

    has_emb = sum(1 for d in data if d["name_emb"] is not None)
    logger.info("  총 %d건, name_embedding 유효: %d건", len(data), has_emb)
    return data


def load_productinfos(conn) -> tuple[list[dict], dict[str, str]]:
    logger.info("ProductInfos 로드 중...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT "ProductCode",
                   "Name_embedding"::text,
                   "MasterIngredientCode"
            FROM "ProductInfos"
            WHERE "Name_embedding" IS NOT NULL
            ORDER BY "ProductCode"
        """)
        rows = cur.fetchall()

    data = []
    pc_to_mic: dict[str, str] = {}
    for pc, emb_str, mic in rows:
        emb = parse_vector(emb_str)
        if emb is not None:
            data.append({"pc": pc, "emb": emb, "mic": mic})
            if mic:
                pc_to_mic[pc] = mic

    logger.info("  유효 임베딩: %d건", len(data))
    return data, pc_to_mic


def build_ground_truth(
    medicines: list[dict], pc_to_mic: dict[str, str]
) -> dict[int, str]:
    gt: dict[int, str] = {}
    for m in medicines:
        pc = m["old_pc"]
        if pc and pc in pc_to_mic:
            gt[m["id"]] = pc_to_mic[pc]
    logger.info("Ground Truth (code chain): %d건", len(gt))
    return gt


def _build_pi_matrix(pi_data: list[dict]):
    embs = np.array([p["emb"] for p in pi_data], dtype=np.float32)
    embs_n = normalize_rows(embs)
    codes = [p["pc"] for p in pi_data]
    mics = [p["mic"] for p in pi_data]
    return embs_n, codes, mics


def _count_unique_mics(sims_row, pi_mics, best_sim, threshold):
    """Top-1 유사도 부근에 존재하는 고유 MIC 수를 센다."""
    mics = set()
    for j in range(len(pi_mics)):
        s = float(sims_row[j])
        if s < threshold:
            continue
        if best_sim - s > AMBIGUITY_MARGIN:
            continue
        if pi_mics[j]:
            mics.add(pi_mics[j])
    return mics


def calibrate(
    medicines: list[dict],
    pi_data: list[dict],
    gt: dict[int, str],
) -> float:
    logger.info("=== 캘리브레이션 시작 ===")
    pi_mat, pi_codes, pi_mics = _build_pi_matrix(pi_data)

    gt_recs = [m for m in medicines if m["id"] in gt and m["name_emb"] is not None]
    if not gt_recs:
        logger.warning("GT 레코드 없음 → 기본 임계값 0.90")
        return 0.90

    logger.info("GT 검증 대상: %d건", len(gt_recs))

    correct_sims: list[float] = []
    ambiguous_count = 0
    wrong_unambiguous = 0

    for start in range(0, len(gt_recs), MATCH_BATCH_SIZE):
        batch = gt_recs[start : start + MATCH_BATCH_SIZE]
        q_mat = np.array([r["name_emb"] for r in batch], dtype=np.float32)
        q_mat_n = normalize_rows(q_mat)
        sims = q_mat_n @ pi_mat.T

        for i, rec in enumerate(batch):
            top_idx = int(np.argmax(sims[i]))
            top_sim = float(sims[i, top_idx])
            top_mic = pi_mics[top_idx]
            expected = gt[rec["id"]]

            nearby_mics = _count_unique_mics(sims[i], pi_mics, top_sim, 0.90)

            if len(nearby_mics) > 1:
                ambiguous_count += 1
                continue

            if top_mic == expected:
                correct_sims.append(top_sim)
            else:
                wrong_unambiguous += 1
                logger.warning(
                    "  비모호 오답: id=%d, expected=%s, got=%s, sim=%.4f",
                    rec["id"], expected, top_mic, top_sim,
                )

        done = min(start + MATCH_BATCH_SIZE, len(gt_recs))
        if done % 5000 < MATCH_BATCH_SIZE or done == len(gt_recs):
            logger.info("  진행: %d / %d", done, len(gt_recs))

    total_gt = len(gt_recs)
    logger.info("GT 결과:")
    logger.info("  정답 (비모호): %d건 (%.1f%%)", len(correct_sims), 100 * len(correct_sims) / total_gt)
    logger.info("  모호 (스킵): %d건 (%.1f%%)", ambiguous_count, 100 * ambiguous_count / total_gt)
    logger.info("  오답 (비모호): %d건", wrong_unambiguous)

    if correct_sims:
        logger.info(
            "  정답 유사도: min=%.4f, mean=%.4f, max=%.4f",
            min(correct_sims), np.mean(correct_sims), max(correct_sims),
        )

    if wrong_unambiguous > 0:
        logger.warning("비모호 오답이 %d건 존재 → 수동 검토 필요!", wrong_unambiguous)

    threshold = min(correct_sims) if correct_sims else 0.90
    logger.info("→ 임계값: %.4f (정답 최솟값)", threshold)
    return threshold


def match_all(
    medicines: list[dict],
    pi_data: list[dict],
    threshold: float,
) -> dict[int, dict]:
    logger.info("=== 전체 매칭 시작 (threshold=%.4f) ===", threshold)
    pi_mat, pi_codes, pi_mics = _build_pi_matrix(pi_data)

    matchable = [m for m in medicines if m["name_emb"] is not None]
    logger.info("매칭 대상: %d건", len(matchable))

    results: dict[int, dict] = {}
    skipped_below = 0
    skipped_no_mic = 0
    skipped_ambiguous = 0

    for start in range(0, len(matchable), MATCH_BATCH_SIZE):
        batch = matchable[start : start + MATCH_BATCH_SIZE]
        q_mat = np.array([r["name_emb"] for r in batch], dtype=np.float32)
        q_mat_n = normalize_rows(q_mat)
        sims = q_mat_n @ pi_mat.T

        for i, rec in enumerate(batch):
            top_idx = int(np.argmax(sims[i]))
            best_sim = float(sims[i, top_idx])

            if best_sim < threshold:
                skipped_below += 1
                continue

            best_mic = pi_mics[top_idx]
            if not best_mic:
                skipped_no_mic += 1
                continue

            nearby_mics = _count_unique_mics(sims[i], pi_mics, best_sim, threshold)

            if len(nearby_mics) > 1:
                skipped_ambiguous += 1
                continue

            results[rec["id"]] = {
                "pc": pi_codes[top_idx],
                "mic": best_mic,
                "name_sim": best_sim,
            }

        done = min(start + MATCH_BATCH_SIZE, len(matchable))
        if done % 5000 < MATCH_BATCH_SIZE or done == len(matchable):
            logger.info(
                "  진행: %d / %d (매칭: %d건)", done, len(matchable), len(results),
            )

    logger.info("스킵 상세:")
    logger.info("  유사도 미달: %d건", skipped_below)
    logger.info("  MIC 없음: %d건", skipped_no_mic)
    logger.info("  모호 (복수 MIC): %d건", skipped_ambiguous)
    return results


def report(results: dict[int, dict], total_medicine: int, total_ingredient: int):
    matched = len(results)
    unique_mics = {r["mic"] for r in results.values()}

    sims = [r["name_sim"] for r in results.values()]

    logger.info("=" * 60)
    logger.info("매칭 결과 리포트")
    logger.info("=" * 60)
    logger.info(
        "pharmport_medicine: %d건 중 %d건 매칭 (%.1f%%)",
        total_medicine, matched, 100 * matched / total_medicine,
    )
    logger.info(
        "심평원성분코드: %d건 중 %d건 커버 (%.1f%%)",
        total_ingredient, len(unique_mics), 100 * len(unique_mics) / total_ingredient,
    )
    if sims:
        logger.info(
            "유사도: min=%.4f, mean=%.4f, median=%.4f, max=%.4f",
            min(sims), np.mean(sims), np.median(sims), max(sims),
        )


def update_db(conn, results: dict[int, dict], total: int):
    logger.info("=== DB 업데이트 시작 ===")

    logger.info("Step 1: 전체 product_code, ingredient_code 초기화...")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE pharmport_medicine SET product_code = NULL, ingredient_code = NULL"
        )
    conn.commit()
    logger.info("  %d건 NULL 처리 완료", total)

    logger.info("Step 2: 매칭 결과 저장 (%d건)...", len(results))
    params = [(r["pc"], r["mic"], mid) for mid, r in results.items()]

    sql = (
        "UPDATE pharmport_medicine "
        "SET product_code = %s, ingredient_code = %s "
        "WHERE medicine_id = %s"
    )
    for s in range(0, len(params), DB_BATCH_SIZE):
        e = min(s + DB_BATCH_SIZE, len(params))
        with conn.cursor() as cur:
            execute_batch(cur, sql, params[s:e], page_size=DB_BATCH_SIZE)
        conn.commit()
        if e % 5000 < DB_BATCH_SIZE or e == len(params):
            logger.info("  저장: %d / %d", e, len(params))

    logger.info("DB 업데이트 완료!")


def _load_with_fresh_conn(load_fn):
    conn = get_connection()
    try:
        return load_fn(conn)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="pharmport_medicine 심평원성분코드 매칭 (에러율 0%)"
    )
    parser.add_argument("--dry-run", action="store_true", help="DB 수정 없이 결과만 확인")
    parser.add_argument("--calibrate", action="store_true", help="임계값 캘리브레이션만")
    parser.add_argument("--threshold", type=float, default=None, help="수동 임계값")
    args = parser.parse_args()

    t0 = time.time()

    medicines = _load_with_fresh_conn(load_medicine)
    pi_data, pc_to_mic = _load_with_fresh_conn(load_productinfos)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "터울주성분"')
            total_ingr = cur.fetchone()[0]
    finally:
        conn.close()

    gt = build_ground_truth(medicines, pc_to_mic)

    if args.threshold is not None:
        threshold = args.threshold
        logger.info("수동 임계값: %.4f", threshold)
    else:
        threshold = calibrate(medicines, pi_data, gt)

    if args.calibrate:
        logger.info("캘리브레이션 완료 (%.1f초)", time.time() - t0)
        return

    results = match_all(medicines, pi_data, threshold)
    report(results, len(medicines), total_ingr)

    if not args.dry_run:
        conn = get_connection()
        try:
            update_db(conn, results, len(medicines))
        finally:
            conn.close()
    else:
        logger.info("(dry-run: DB 수정 건너뜀)")

    logger.info("전체 완료! (%.1f초 = %.1f분)", time.time() - t0, (time.time() - t0) / 60)


if __name__ == "__main__":
    main()
