"""
Enrichment 공통 모듈 — rate limit, 상태 관리, Layer 1 자동 검증

모든 enrich_*.py 스크립트가 이 모듈을 import하여 사용한다.

기능:
  - API rate limit 관리 (per-source 설정)
  - edb_enrichment_status 상태 업데이트
  - Layer 1 자동 무결성 검증
  - 공통 유틸리티 (성분명 전처리, 배치 처리 등)
"""

import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import psycopg2

from common import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

@dataclass
class RateLimitConfig:
    """API별 rate limit 설정."""
    requests_per_second: float = 1.0
    burst_size: int = 1
    retry_max: int = 3
    retry_backoff: float = 2.0  # 지수 백오프 배수


# 소스별 기본 rate limit 설정
DEFAULT_RATE_LIMITS: dict[str, RateLimitConfig] = {
    "chembl": RateLimitConfig(requests_per_second=3.0, burst_size=3, retry_max=3),
    "opentargets": RateLimitConfig(requests_per_second=5.0, burst_size=5, retry_max=3),
    "openfda": RateLimitConfig(requests_per_second=4.0, burst_size=4, retry_max=3),
    "pubmed": RateLimitConfig(requests_per_second=3.0, burst_size=3, retry_max=3),
    "clinicaltrials": RateLimitConfig(requests_per_second=3.0, burst_size=3, retry_max=3),
    "biorxiv": RateLimitConfig(requests_per_second=2.0, burst_size=2, retry_max=3),
}


class RateLimiter:
    """토큰 버킷 기반 rate limiter."""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._tokens = config.burst_size
        self._last_refill = time.monotonic()

    def wait(self):
        """다음 요청이 가능할 때까지 대기한다."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self.config.burst_size,
            self._tokens + elapsed * self.config.requests_per_second,
        )
        self._last_refill = now

        if self._tokens < 1.0:
            sleep_time = (1.0 - self._tokens) / self.config.requests_per_second
            time.sleep(sleep_time)
            self._tokens = 0.0
            self._last_refill = time.monotonic()
        else:
            self._tokens -= 1.0


_limiters: dict[str, RateLimiter] = {}


def get_rate_limiter(source: str) -> RateLimiter:
    """소스별 RateLimiter 싱글턴을 반환한다."""
    if source not in _limiters:
        config = DEFAULT_RATE_LIMITS.get(source, RateLimitConfig())
        _limiters[source] = RateLimiter(config)
    return _limiters[source]


def api_call_with_retry(source: str, fn, *args, **kwargs):
    """rate limit + 지수 백오프 재시도로 API를 호출한다.

    Args:
        source: API 소스 이름 (rate limit 키)
        fn: 호출할 함수
        *args, **kwargs: 함수 인자

    Returns:
        fn의 반환값

    Raises:
        마지막 시도에서 발생한 예외
    """
    limiter = get_rate_limiter(source)
    config = DEFAULT_RATE_LIMITS.get(source, RateLimitConfig())
    last_err = None

    for attempt in range(1, config.retry_max + 1):
        limiter.wait()
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < config.retry_max:
                wait = config.retry_backoff ** attempt
                logger.warning(
                    "[%s] 시도 %d/%d 실패: %s — %.1f초 후 재시도",
                    source, attempt, config.retry_max, e, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "[%s] 시도 %d/%d 최종 실패: %s",
                    source, attempt, config.retry_max, e,
                )

    raise last_err


# ---------------------------------------------------------------------------
# Enrichment Status 관리
# ---------------------------------------------------------------------------

STATUS_FIELDS = {
    "chembl": ("chembl_mapped", "chembl_mapped_at"),
    "mechanism": ("mechanism_fetched", "mechanism_fetched_at"),
    "admet": ("admet_fetched", "admet_fetched_at"),
    "disease": ("disease_fetched", "disease_fetched_at"),
    "safety": ("safety_fetched", "safety_fetched_at"),
    "literature": ("literature_fetched", "literature_fetched_at"),
    "trials": ("trials_fetched", "trials_fetched_at"),
    "fda": ("fda_fetched", "fda_fetched_at"),
}


def update_status(conn, code: str, step: str, success: bool = True, error: str | None = None):
    """edb_enrichment_status의 특정 단계를 업데이트한다.

    Args:
        conn: psycopg2 connection
        code: 심평원성분코드
        step: STATUS_FIELDS 키 (chembl, mechanism, admet, ...)
        success: 성공 여부
        error: 에러 메시지 (실패 시)
    """
    if step not in STATUS_FIELDS:
        raise ValueError(f"알 수 없는 step: {step}. 가능한 값: {list(STATUS_FIELDS.keys())}")

    bool_col, ts_col = STATUS_FIELDS[step]

    with conn.cursor() as cur:
        if success:
            cur.execute(f"""
                UPDATE edb_enrichment_status
                SET "{bool_col}" = TRUE,
                    "{ts_col}" = NOW(),
                    last_error = NULL,
                    updated_at = NOW()
                WHERE "심평원성분코드" = %s
            """, (code,))
        else:
            cur.execute("""
                UPDATE edb_enrichment_status
                SET last_error = %s,
                    updated_at = NOW()
                WHERE "심평원성분코드" = %s
            """, (error[:500] if error else "unknown error", code))
    conn.commit()


def get_pending_codes(conn, step: str, limit: int = 0) -> list[dict]:
    """특정 enrichment 단계가 미완료인 성분코드 목록을 반환한다.

    Args:
        conn: psycopg2 connection
        step: STATUS_FIELDS 키
        limit: 결과 수 제한 (0=전체)

    Returns:
        [{"심평원성분코드": ..., "성분명": ..., "성분명한글": ...}, ...]
    """
    bool_col, _ = STATUS_FIELDS[step]
    limit_clause = f"LIMIT {limit}" if limit > 0 else ""

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT es."심평원성분코드", t."성분명", t."성분명한글"
            FROM edb_enrichment_status es
            JOIN "터울주성분" t ON es."심평원성분코드" = t."심평원성분코드"
            WHERE es."{bool_col}" = FALSE
              AND t."IsDeleted" = FALSE
            ORDER BY es."심평원성분코드"
            {limit_clause}
        """)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# 성분명 전처리
# ---------------------------------------------------------------------------

def preprocess_ingredient_name(name: str) -> str:
    """ChEMBL 검색을 위한 성분명 전처리.

    - 함량/단위 제거 (500mg, 10ml 등)
    - 괄호 내 보충 정보 정리
    - 염(salt) 표기 처리
    - 양끝 공백 정리
    """
    if not name:
        return ""

    # 1. 함량+단위 패턴 제거
    cleaned = re.sub(
        r'\s+[\d.,]+\s*(mg|g|ml|%|mcg|iu|μg|kg|mmol|mEq|units?)\b.*',
        '', name, flags=re.IGNORECASE,
    )

    # 2. 뒤쪽 숫자 패턴 제거
    cleaned = re.sub(r'\s+\d+[\d.,]*\s*$', '', cleaned)

    # 3. "(as ...)" 표기 제거 (ex: "iron (as ferrous sulfate)")
    cleaned = re.sub(r'\s*\(as\s+[^)]+\)', '', cleaned, flags=re.IGNORECASE)

    # 4. 양끝 정리
    cleaned = cleaned.strip().rstrip(',').strip()

    return cleaned


def normalize_for_hash(text: str) -> str:
    """프로파일 해시 생성용 텍스트 정규화.

    - 소문자 변환
    - 공백 정리 (연속 공백 → 단일 공백)
    - 양끝 공백 제거
    """
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text.lower().strip())


def split_ingredients(text: str) -> list[str]:
    """괄호 내부 콤마를 무시하면서 성분을 분리한다."""
    result = []
    depth = 0
    current: list[str] = []

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


# ---------------------------------------------------------------------------
# Layer 1: 자동 무결성 검증
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Layer 1 검증 결과."""
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_enrichment_record(record: dict, table: str) -> ValidationResult:
    """단일 enrichment 레코드에 대한 Layer 1 검증을 수행한다.

    검증 항목:
    - 심평원성분코드 존재 여부
    - source/fetched_at 존재 여부 (출처 추적)
    - 핵심 필드 NULL 체크

    Args:
        record: INSERT 대상 딕셔너리
        table: 테이블명

    Returns:
        ValidationResult
    """
    result = ValidationResult()

    # 1. 심평원성분코드 필수
    code = record.get("심평원성분코드")
    if not code:
        result.passed = False
        result.errors.append(f"[{table}] 심평원성분코드 누락")

    # 2. 출처 추적 (source, fetched_at)
    if "source" in record and not record.get("source"):
        result.passed = False
        result.errors.append(f"[{table}] source 누락 (코드: {code})")

    # 3. 테이블별 필수 필드 체크
    required_fields = {
        "edb_mechanism": ["action_type"],
        "edb_drug_disease": ["disease_name"],
        "edb_literature": ["title"],
        "edb_clinical_trial": ["nct_id"],
        "edb_safety": ["info_type", "description"],
    }

    for field_name in required_fields.get(table, []):
        if not record.get(field_name):
            result.warnings.append(f"[{table}] {field_name} 비어있음 (코드: {code})")

    # 4. edb_drug_disease: association_score >= 0.3 필터
    if table == "edb_drug_disease":
        score = record.get("association_score")
        if score is not None and score < 0.3:
            result.passed = False
            result.errors.append(
                f"[{table}] association_score {score} < 0.3 — 저장 차단 (코드: {code})"
            )

    # 5. edb_mechanism: target_organism 체크 (출력 필터용 경고)
    if table == "edb_mechanism":
        org = record.get("target_organism", "")
        if org and org != "Homo sapiens":
            result.warnings.append(
                f"[{table}] target_organism='{org}' (non-human) — 출력 시 필터 대상 (코드: {code})"
            )

    return result


def validate_batch(records: list[dict], table: str) -> ValidationResult:
    """배치 레코드에 대한 Layer 1 검증을 수행한다."""
    batch_result = ValidationResult()

    for record in records:
        r = validate_enrichment_record(record, table)
        if not r.passed:
            batch_result.passed = False
        batch_result.errors.extend(r.errors)
        batch_result.warnings.extend(r.warnings)

    if batch_result.errors:
        logger.error("Layer 1 검증 실패: %d건 에러", len(batch_result.errors))
        for e in batch_result.errors[:10]:
            logger.error("  %s", e)

    if batch_result.warnings:
        logger.warning("Layer 1 경고: %d건", len(batch_result.warnings))
        for w in batch_result.warnings[:10]:
            logger.warning("  %s", w)

    return batch_result


# ---------------------------------------------------------------------------
# 배치 INSERT 유틸리티
# ---------------------------------------------------------------------------

def batch_insert(conn, table: str, records: list[dict],
                 conflict_action: str = "DO NOTHING",
                 validate: bool = True) -> int:
    """Layer 1 검증 후 배치 INSERT를 수행한다.

    Args:
        conn: psycopg2 connection
        table: 테이블명
        records: INSERT할 딕셔너리 목록
        conflict_action: ON CONFLICT 처리 (기본: DO NOTHING)
        validate: Layer 1 검증 수행 여부

    Returns:
        실제 INSERT된 건수
    """
    if not records:
        return 0

    # Layer 1 검증
    if validate:
        vr = validate_batch(records, table)
        if not vr.passed:
            # 검증 통과 레코드만 필터
            valid_records = []
            for record in records:
                r = validate_enrichment_record(record, table)
                if r.passed:
                    valid_records.append(record)
            records = valid_records
            if not records:
                logger.error("Layer 1 검증 후 INSERT 가능 레코드 0건")
                return 0

    # 컬럼 목록 (첫 번째 레코드 기준)
    columns = list(records[0].keys())
    col_names = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))

    inserted = 0
    with conn.cursor() as cur:
        for record in records:
            values = [record.get(c) for c in columns]
            try:
                cur.execute(
                    f'INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT {conflict_action}',
                    values,
                )
                inserted += cur.rowcount
            except psycopg2.Error as e:
                logger.error("INSERT 실패 [%s]: %s — %s", table, record.get("심평원성분코드", "?"), e)
                conn.rollback()
                continue

    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# 진행 상황 로깅
# ---------------------------------------------------------------------------

class ProgressTracker:
    """enrichment 진행 상황을 추적하고 로깅한다."""

    def __init__(self, total: int, source: str, log_interval: int = 50):
        self.total = total
        self.source = source
        self.log_interval = log_interval
        self.processed = 0
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.start_time = time.monotonic()

    def update(self, success: bool = True, skipped: bool = False):
        self.processed += 1
        if skipped:
            self.skipped += 1
        elif success:
            self.success += 1
        else:
            self.failed += 1

        if self.processed % self.log_interval == 0 or self.processed == self.total:
            elapsed = time.monotonic() - self.start_time
            rate = self.processed / elapsed if elapsed > 0 else 0
            remaining = (self.total - self.processed) / rate if rate > 0 else 0
            logger.info(
                "[%s] %d/%d (%.1f%%) — 성공: %d, 실패: %d, 건너뜀: %d — %.1f건/초, 남은시간: %.0f초",
                self.source, self.processed, self.total,
                100 * self.processed / self.total if self.total > 0 else 0,
                self.success, self.failed, self.skipped,
                rate, remaining,
            )

    def summary(self) -> dict:
        elapsed = time.monotonic() - self.start_time
        return {
            "source": self.source,
            "total": self.total,
            "processed": self.processed,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "elapsed_seconds": round(elapsed, 1),
            "rate_per_second": round(self.processed / elapsed, 2) if elapsed > 0 else 0,
        }


# ---------------------------------------------------------------------------
# 병렬 처리 유틸리티
# ---------------------------------------------------------------------------

# ProgressTracker를 thread-safe로 사용하기 위한 lock
_tracker_lock = threading.Lock()


def _safe_tracker_update(tracker: ProgressTracker, success: bool = True, skipped: bool = False):
    """Thread-safe ProgressTracker 업데이트."""
    with _tracker_lock:
        tracker.update(success=success, skipped=skipped)


def group_by_base(codes: list[dict], base_len: int = 4) -> dict[str, list[dict]]:
    """심평원성분코드를 base(앞 N자리)별로 그룹핑한다.

    Args:
        codes: [{"심평원성분코드": ..., ...}, ...]
        base_len: base 길이 (기본 4자리)

    Returns:
        {base: [코드 딕셔너리, ...]}
    """
    groups: dict[str, list[dict]] = {}
    for row in codes:
        base = row["심평원성분코드"][:base_len]
        groups.setdefault(base, []).append(row)
    return groups


def parallel_process(
    items: list,
    process_fn: Callable,
    workers: int = 4,
    source: str = "parallel",
    tracker: ProgressTracker | None = None,
) -> list:
    """ThreadPoolExecutor로 항목을 병렬 처리한다.

    각 스크립트의 base 그룹 단위 작업을 병렬로 실행한다.
    DB 커넥션은 워커별로 새로 생성해야 하므로 process_fn 내부에서 관리한다.

    Args:
        items: 처리할 항목 목록 (base 키 목록 등)
        process_fn: 각 항목을 처리하는 함수. (item) -> result 형태.
            성공 시 결과를 반환, 실패 시 예외 raise.
        workers: 병렬 워커 수 (기본 4)
        source: 로그용 소스 이름
        tracker: ProgressTracker (제공 시 thread-safe 업데이트)

    Returns:
        성공한 결과 목록
    """
    if workers <= 1:
        # 단일 스레드 — 기존 동작과 동일
        results = []
        for item in items:
            try:
                result = process_fn(item)
                results.append(result)
                if tracker:
                    _safe_tracker_update(tracker, success=True)
            except Exception as e:
                logger.warning("[%s] 처리 실패: %s — %s", source, item, e)
                if tracker:
                    _safe_tracker_update(tracker, success=False)
        return results

    logger.info("[%s] 병렬 처리 시작: %d개 항목, %d 워커", source, len(items), workers)
    results = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_item = {executor.submit(process_fn, item): item for item in items}

        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                result = future.result()
                results.append(result)
                if tracker:
                    _safe_tracker_update(tracker, success=True)
            except Exception as e:
                logger.warning("[%s] 처리 실패: %s — %s", source, item, e)
                if tracker:
                    _safe_tracker_update(tracker, success=False)

    logger.info("[%s] 병렬 처리 완료: %d/%d 성공", source, len(results), len(items))
    return results


def get_thread_connection(db_name: str | None = None):
    """워커 스레드용 DB 커넥션을 반환한다.

    thread-local이 아닌 새 커넥션을 매번 생성한다.
    호출자가 반드시 close()해야 한다.
    """
    return get_connection(db_name)
