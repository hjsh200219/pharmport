"""
Method 2: GT-독립 매칭 (코드 체인 불필요)

3가지 필터 동시 적용:
  1. 텍스트 완전 일치로 임계값 캘리브레이션 (코드 체인 대체)
  2. 상호 최적 매칭: A→B Top-1 AND B→A Top-1
  3. 다중 채널 합의: 약품명 + 성분 + 제조사

Usage:
  python match_ingredient_v2.py                # 전체 실행
  python match_ingredient_v2.py --dry-run      # DB 미수정
  python match_ingredient_v2.py --calibrate    # 캘리브레이션만
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
BATCH_SIZE = 1000


def parse_vector(s: str | None) -> np.ndarray | None:
    if s is None:
        return None
    try:
        t = s.strip()
        if t.startswith(("[", "(")):
            t = t[1:-1]
        return np.fromstring(t, sep=",", dtype=np.float32)
    except Exception:
        return None


def normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / np.where(norms == 0, 1.0, norms)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _load(load_fn):
    conn = get_connection()
    try:
        return load_fn(conn)
    finally:
        conn.close()


def load_medicine(conn) -> list[dict]:
    logger.info("pharmport_medicine 로드 중...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT medicine_id,
                   medicine_name_embedding::text,
                   sorted_ingredient_embedding::text,
                   manufacturer_embedding::text
            FROM pharmport_medicine
            ORDER BY medicine_id
        """)
        rows = cur.fetchall()

    data = []
    for mid, ne, ie, me in rows:
        data.append({
            "id": mid,
            "name_emb": parse_vector(ne),
            "ingr_emb": parse_vector(ie),
            "mfr_emb": parse_vector(me),
        })

    logger.info("  총 %d건", len(data))
    return data


def load_productinfos(conn) -> list[dict]:
    logger.info("ProductInfos 로드 중...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT "ProductCode", "Name_embedding"::text,
                   "MasterIngredientCode", "ManufacturerId"
            FROM "ProductInfos"
            WHERE "Name_embedding" IS NOT NULL
            ORDER BY "ProductCode"
        """)
        rows = cur.fetchall()

    data = []
    for pc, emb_str, mic, mfr_id in rows:
        emb = parse_vector(emb_str)
        if emb is not None:
            data.append({"pc": pc, "emb": emb, "mic": mic, "mfr_id": mfr_id})

    logger.info("  유효 %d건", len(data))
    return data


def load_ingredient_map(conn) -> dict[str, np.ndarray]:
    logger.info("터울주성분 임베딩 로드 중...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT "심평원성분코드", "sorted_성분명_embedding"::text
            FROM "터울주성분" WHERE "sorted_성분명_embedding" IS NOT NULL
        """)
        rows = cur.fetchall()

    m = {}
    for code, emb_str in rows:
        emb = parse_vector(emb_str)
        if emb is not None:
            m[code] = emb

    logger.info("  유효 %d건", len(m))
    return m


def load_manufacturer_map(conn) -> dict[int, np.ndarray]:
    logger.info("Manufacturers 임베딩 로드 중...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT "ManufacturerID", "Name_embedding"::text
            FROM "Manufacturers" WHERE "Name_embedding" IS NOT NULL
        """)
        rows = cur.fetchall()

    m = {}
    for mid, emb_str in rows:
        emb = parse_vector(emb_str)
        if emb is not None:
            m[mid] = emb

    logger.info("  유효 %d건", len(m))
    return m


def build_text_gt(conn) -> dict[int, str]:
    """텍스트 완전 일치 GT (코드 체인 독립)."""
    logger.info("텍스트 완전 일치 GT 구축 중...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT m.medicine_id,
                   p."MasterIngredientCode"
            FROM pharmport_medicine m
            JOIN "ProductInfos" p ON m.medicine_name = p."Name"
            WHERE p."MasterIngredientCode" IS NOT NULL
            GROUP BY m.medicine_id, p."MasterIngredientCode"
        """)
        rows = cur.fetchall()

    counts: dict[int, set[str]] = {}
    for mid, mic in rows:
        counts.setdefault(mid, set()).add(mic)

    gt = {mid: next(iter(mics)) for mid, mics in counts.items() if len(mics) == 1}
    logger.info("  비모호 GT: %d건", len(gt))
    return gt


def _build_matrix(data: list[dict], key: str = "emb"):
    embs = np.array([d[key] for d in data], dtype=np.float32)
    return normalize_rows(embs)


def find_reciprocal_matches(
    med_data: list[dict], pi_data: list[dict]
) -> dict[int, tuple[int, float]]:
    """상호 최적 매칭. {med_idx: (pi_idx, name_sim)}"""
    logger.info("=== 상호 최적 매칭 시작 ===")

    med_mat = _build_matrix(
        [{"emb": d["name_emb"]} for d in med_data if d["name_emb"] is not None]
    )
    pi_mat = _build_matrix([{"emb": d["emb"]} for d in pi_data])

    valid_med_indices = [i for i, d in enumerate(med_data) if d["name_emb"] is not None]

    logger.info("  Forward pass: medicine(%d) → PI(%d)", len(valid_med_indices), len(pi_data))
    fwd: dict[int, tuple[int, float]] = {}
    for s in range(0, med_mat.shape[0], BATCH_SIZE):
        e = min(s + BATCH_SIZE, med_mat.shape[0])
        sims = med_mat[s:e] @ pi_mat.T
        for i in range(e - s):
            pi_idx = int(np.argmax(sims[i]))
            fwd[valid_med_indices[s + i]] = (pi_idx, float(sims[i, pi_idx]))
        if e % 5000 < BATCH_SIZE or e == med_mat.shape[0]:
            logger.info("    진행: %d / %d", e, med_mat.shape[0])

    logger.info("  Reverse pass: PI(%d) → medicine(%d)", len(pi_data), len(valid_med_indices))
    rev: dict[int, int] = {}
    for s in range(0, pi_mat.shape[0], BATCH_SIZE):
        e = min(s + BATCH_SIZE, pi_mat.shape[0])
        sims = pi_mat[s:e] @ med_mat.T
        for j in range(e - s):
            rev[s + j] = int(np.argmax(sims[j]))
        if e % 5000 < BATCH_SIZE or e == pi_mat.shape[0]:
            logger.info("    진행: %d / %d", e, pi_mat.shape[0])

    reciprocal: dict[int, tuple[int, float]] = {}
    for med_idx, (pi_idx, sim) in fwd.items():
        rev_med_local = rev.get(pi_idx)
        if rev_med_local is not None:
            real_med_idx = valid_med_indices[rev_med_local]
            if real_med_idx == med_idx:
                reciprocal[med_idx] = (pi_idx, sim)

    logger.info("  상호 매칭: %d건 / forward %d건", len(reciprocal), len(fwd))
    return reciprocal


def calibrate_channels(
    med_data: list[dict],
    pi_data: list[dict],
    text_gt: dict[int, str],
    mic_map: dict[str, np.ndarray],
    mfr_map: dict[int, np.ndarray],
) -> tuple[float, float]:
    """텍스트 GT로 성분·제조사 채널 임계값 캘리브레이션."""
    logger.info("=== 다중 채널 캘리브레이션 ===")

    ingr_sims: list[float] = []
    mfr_sims: list[float] = []

    for med_idx, d in enumerate(med_data):
        mid = d["id"]
        if mid not in text_gt:
            continue

        mic = text_gt[mid]
        ingr_emb = d["ingr_emb"]
        mfr_emb = d["mfr_emb"]

        if ingr_emb is not None and mic in mic_map:
            ingr_sims.append(cosine_sim(ingr_emb, mic_map[mic]))

        if mfr_emb is not None:
            for pi in pi_data:
                if pi["mic"] == mic and pi["mfr_id"] in mfr_map:
                    mfr_sims.append(cosine_sim(mfr_emb, mfr_map[pi["mfr_id"]]))
                    break

    ingr_thresh = float(np.percentile(ingr_sims, 1)) if ingr_sims else 0.3
    mfr_thresh = float(np.percentile(mfr_sims, 1)) if mfr_sims else 0.3

    logger.info("  성분 채널: %d건, min=%.4f, p1=%.4f, mean=%.4f",
                len(ingr_sims), min(ingr_sims) if ingr_sims else 0,
                ingr_thresh, np.mean(ingr_sims) if ingr_sims else 0)
    logger.info("  제조사 채널: %d건, min=%.4f, p1=%.4f, mean=%.4f",
                len(mfr_sims), min(mfr_sims) if mfr_sims else 0,
                mfr_thresh, np.mean(mfr_sims) if mfr_sims else 0)

    return ingr_thresh, mfr_thresh


def apply_multichannel(
    reciprocal: dict[int, tuple[int, float]],
    med_data: list[dict],
    pi_data: list[dict],
    mic_map: dict[str, np.ndarray],
    mfr_map: dict[int, np.ndarray],
    ingr_thresh: float,
    mfr_thresh: float,
) -> dict[int, dict]:
    """다중 채널 합의 필터."""
    logger.info("=== 다중 채널 합의 필터 ===")

    results: dict[int, dict] = {}
    skip_no_mic = 0
    skip_ingr = 0
    skip_mfr = 0

    for med_idx, (pi_idx, name_sim) in reciprocal.items():
        d = med_data[med_idx]
        pi = pi_data[pi_idx]
        mic = pi["mic"]

        if not mic:
            skip_no_mic += 1
            continue

        ingr_emb = d["ingr_emb"]
        ingr_sim = 0.0
        if ingr_emb is not None and mic in mic_map:
            ingr_sim = cosine_sim(ingr_emb, mic_map[mic])

        if ingr_sim < ingr_thresh:
            skip_ingr += 1
            continue

        mfr_emb = d["mfr_emb"]
        mfr_sim = 0.0
        if mfr_emb is not None and pi["mfr_id"] in mfr_map:
            mfr_sim = cosine_sim(mfr_emb, mfr_map[pi["mfr_id"]])

        if mfr_sim < mfr_thresh:
            skip_mfr += 1
            continue

        results[d["id"]] = {
            "pc": pi["pc"],
            "mic": mic,
            "name_sim": name_sim,
            "ingr_sim": ingr_sim,
            "mfr_sim": mfr_sim,
        }

    logger.info("  통과: %d건", len(results))
    logger.info("  스킵 - MIC없음: %d, 성분미달: %d, 제조사미달: %d",
                skip_no_mic, skip_ingr, skip_mfr)
    return results


def validate_with_text_gt(results: dict[int, dict], text_gt: dict[int, str]):
    """텍스트 GT로 최종 검증."""
    logger.info("=== 텍스트 GT 검증 ===")
    correct = 0
    wrong = 0
    no_gt = 0

    for mid, r in results.items():
        if mid not in text_gt:
            no_gt += 1
            continue
        if r["mic"] == text_gt[mid]:
            correct += 1
        else:
            wrong += 1

    verifiable = correct + wrong
    logger.info("  GT 대비 검증: %d건 (정답 %d, 오답 %d)", verifiable, correct, wrong)
    if verifiable > 0:
        logger.info("  정확도: %.2f%% (%d / %d)", 100 * correct / verifiable, correct, verifiable)
    logger.info("  GT 없는 매칭: %d건", no_gt)


def report(results: dict[int, dict], total_med: int, total_ingr: int):
    matched = len(results)
    unique_mics = {r["mic"] for r in results.values()}
    name_sims = [r["name_sim"] for r in results.values()]
    ingr_sims = [r["ingr_sim"] for r in results.values()]
    mfr_sims = [r["mfr_sim"] for r in results.values()]

    logger.info("=" * 60)
    logger.info("매칭 결과 리포트")
    logger.info("=" * 60)
    logger.info("pharmport_medicine: %d건 중 %d건 (%.1f%%)",
                total_med, matched, 100 * matched / total_med)
    logger.info("심평원성분코드: %d건 중 %d건 (%.1f%%)",
                total_ingr, len(unique_mics), 100 * len(unique_mics) / total_ingr)
    if name_sims:
        logger.info("약품명 유사도: min=%.4f, mean=%.4f, median=%.4f",
                    min(name_sims), np.mean(name_sims), np.median(name_sims))
    if ingr_sims:
        logger.info("성분 유사도: min=%.4f, mean=%.4f, median=%.4f",
                    min(ingr_sims), np.mean(ingr_sims), np.median(ingr_sims))
    if mfr_sims:
        logger.info("제조사 유사도: min=%.4f, mean=%.4f, median=%.4f",
                    min(mfr_sims), np.mean(mfr_sims), np.median(mfr_sims))


def update_db(conn, results: dict[int, dict], total: int):
    logger.info("=== DB 업데이트 시작 ===")
    logger.info("Step 1: 전체 초기화...")
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


def main():
    parser = argparse.ArgumentParser(description="Method 2: GT-독립 매칭")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--calibrate", action="store_true")
    args = parser.parse_args()

    t0 = time.time()

    med_data = _load(load_medicine)
    pi_data = _load(load_productinfos)
    mic_map = _load(load_ingredient_map)
    mfr_map = _load(load_manufacturer_map)
    text_gt = _load(build_text_gt)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "터울주성분"')
            total_ingr = cur.fetchone()[0]
    finally:
        conn.close()

    ingr_thresh, mfr_thresh = calibrate_channels(
        med_data, pi_data, text_gt, mic_map, mfr_map,
    )

    if args.calibrate:
        logger.info("캘리브레이션 완료 (%.1f초)", time.time() - t0)
        return

    reciprocal = find_reciprocal_matches(med_data, pi_data)

    results = apply_multichannel(
        reciprocal, med_data, pi_data, mic_map, mfr_map,
        ingr_thresh, mfr_thresh,
    )

    validate_with_text_gt(results, text_gt)
    report(results, len(med_data), total_ingr)

    if not args.dry_run:
        conn = get_connection()
        try:
            update_db(conn, results, len(med_data))
        finally:
            conn.close()
    else:
        logger.info("(dry-run: DB 수정 건너뜀)")

    logger.info("전체 완료! (%.1f초 = %.1f분)", time.time() - t0, (time.time() - t0) / 60)


if __name__ == "__main__":
    main()
