"""
PharmPort Enrichment Pipeline 오케스트레이터

Phase 1~2 전체 파이프라인을 의존성 순서에 맞춰 실행한다.
독립 단계는 subprocess로 동시 실행하고, 의존 단계는 순차 실행한다.

의존성 그래프:
  Phase 0: create_enrichment_tables.py  (이미 완료 전제)
  Phase 1-A: enrich_chembl.py           (mapping → mechanism → admet)
  Phase 1-B: enrich_fda.py             ─┐
             enrich_opentargets.py      ├─ 독립, 동시 실행 가능
             enrich_pubmed.py           │  (단, opentargets는 chembl mapping 필요)
             enrich_trials.py          ─┘
  Phase 1-C: enrichment_report.py       (Phase 1 전체 완료 후)
  Phase 1.5: build_profiles.py          (Phase 1 완료 후)
  Phase 2-A: create_v2_tables.py        (Phase 1.5 완료 후)
  Phase 2-B: generate_medication_guide.py ─┐ 독립
             generate_yakho_desc.py       ─┘ 독립

Usage:
    python run_pipeline.py                          # 전체 파이프라인
    python run_pipeline.py --phase 1                # Phase 1만
    python run_pipeline.py --phase 1b               # Phase 1-B만
    python run_pipeline.py --phase 2                # Phase 2만
    python run_pipeline.py --workers 4              # 각 스크립트 내부 워커 4개
    python run_pipeline.py --dry-run                # 전체 dry-run
    python run_pipeline.py --limit 100              # 각 단계 100건 제한
    python run_pipeline.py --skip-phase0            # Phase 0 건너뜀 (이미 완료)
"""

import argparse
import logging
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# 단계 정의
# ---------------------------------------------------------------------------

@dataclass
class Step:
    """파이프라인 단계 정의."""
    name: str
    script: str
    phase: str
    args: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    optional: bool = False


STEPS: list[Step] = [
    # Phase 1-A: ChEMBL (mapping → mechanism → admet, 내부적으로 순차)
    Step("chembl", "enrich_chembl.py", "1a"),

    # Phase 1-B: 독립 소스들 (chembl mapping 후 실행 가능)
    Step("fda", "enrich_fda.py", "1b", depends_on=["chembl"]),
    Step("opentargets", "enrich_opentargets.py", "1b", depends_on=["chembl"]),
    Step("pubmed", "enrich_pubmed.py", "1b", depends_on=["chembl"]),
    Step("trials", "enrich_trials.py", "1b", depends_on=["chembl"]),

    # Phase 1-C: 리포트
    Step("report", "enrichment_report.py", "1c",
         depends_on=["chembl", "fda", "opentargets", "pubmed", "trials"]),

    # Phase 1.5: 프로파일
    Step("profiles", "build_profiles.py", "1.5",
         depends_on=["report"]),

    # Phase 2-A: 신규 DB
    Step("v2_tables", "create_v2_tables.py", "2a",
         depends_on=["profiles"]),

    # Phase 2-B: LLM 생성 (독립 실행 가능)
    Step("medication_guide", "generate_medication_guide.py", "2b",
         depends_on=["v2_tables"]),
    Step("yakho_desc", "generate_yakho_desc.py", "2b",
         depends_on=["v2_tables"]),
]


# ---------------------------------------------------------------------------
# 실행 엔진
# ---------------------------------------------------------------------------

def run_step(step: Step, extra_args: list[str], timeout: int = 7200) -> tuple[str, bool, float, str]:
    """단일 단계를 subprocess로 실행한다.

    Returns:
        (step_name, success, elapsed_seconds, output_tail)
    """
    cmd = [sys.executable, step.script] + step.args + extra_args
    logger.info("▶ [%s] 시작: %s", step.name, " ".join(cmd))
    start = time.monotonic()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=None,  # 현재 디렉토리
        )
        elapsed = time.monotonic() - start
        success = result.returncode == 0

        # 마지막 20줄 로그
        output_lines = (result.stdout + result.stderr).strip().splitlines()
        tail = "\n".join(output_lines[-20:]) if output_lines else "(출력 없음)"

        if success:
            logger.info("✅ [%s] 완료 (%.1f초)", step.name, elapsed)
        else:
            logger.error(
                "❌ [%s] 실패 (exit=%d, %.1f초)\n%s",
                step.name, result.returncode, elapsed, tail,
            )

        return step.name, success, elapsed, tail

    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        logger.error("⏰ [%s] 타임아웃 (%d초)", step.name, timeout)
        return step.name, False, elapsed, f"타임아웃 ({timeout}초)"

    except Exception as e:
        elapsed = time.monotonic() - start
        logger.error("💥 [%s] 예외: %s", step.name, e)
        return step.name, False, elapsed, str(e)


def resolve_phases(phase_filter: str | None) -> set[str]:
    """--phase 인자를 phase 코드 집합으로 변환한다."""
    if not phase_filter:
        return {s.phase for s in STEPS}

    mapping = {
        "1": {"1a", "1b", "1c"},
        "1a": {"1a"},
        "1b": {"1b"},
        "1c": {"1c"},
        "1.5": {"1.5"},
        "2": {"2a", "2b"},
        "2a": {"2a"},
        "2b": {"2b"},
    }
    return mapping.get(phase_filter.lower(), {phase_filter})


def run_pipeline(
    phase_filter: str | None = None,
    workers: int = 1,
    limit: int = 0,
    dry_run: bool = False,
    dev: bool = False,
    skip_phase0: bool = True,
    timeout: int = 7200,
):
    """전체 파이프라인을 의존성 순서에 맞춰 실행한다."""
    phases = resolve_phases(phase_filter)

    # 실행 대상 필터링
    active_steps = [s for s in STEPS if s.phase in phases]

    if not active_steps:
        logger.error("실행할 단계가 없습니다 (phase=%s)", phase_filter)
        return False

    # 공통 추가 인자 구성
    extra_args: list[str] = []
    if workers > 1:
        extra_args.extend(["--workers", str(workers)])
    if limit > 0:
        extra_args.extend(["--limit", str(limit)])
    if dry_run:
        extra_args.append("--dry-run")
    if dev:
        extra_args.append("--dev")

    logger.info("=" * 60)
    logger.info("PharmPort Enrichment Pipeline")
    logger.info("  대상 Phase: %s", ", ".join(sorted(phases)))
    logger.info("  단계 수: %d", len(active_steps))
    logger.info("  워커: %d, limit: %d, dry-run: %s",
                workers, limit, dry_run)
    logger.info("=" * 60)

    # 실행 상태 추적
    completed: dict[str, bool] = {}  # step_name → success
    results: list[tuple[str, bool, float, str]] = []
    total_start = time.monotonic()

    # 단계별 실행 (토폴로지 순서)
    while len(completed) < len(active_steps):
        # 실행 가능한 단계 찾기 (의존성 충족 + 미완료)
        ready = []
        for step in active_steps:
            if step.name in completed:
                continue
            # 의존성 중 active_steps에 포함된 것만 체크
            active_deps = [
                d for d in step.depends_on
                if any(s.name == d for s in active_steps)
            ]
            if all(completed.get(d) for d in active_deps):
                ready.append(step)

        if not ready:
            # 의존성 실패로 더 이상 진행 불가
            blocked = [
                s.name for s in active_steps
                if s.name not in completed
            ]
            logger.error(
                "의존성 실패로 중단. 미완료 단계: %s",
                ", ".join(blocked),
            )
            break

        # 준비된 단계들을 동시 실행
        if len(ready) == 1:
            # 단일 단계 — 직접 실행
            step = ready[0]
            name, success, elapsed, tail = run_step(step, extra_args, timeout)
            completed[name] = success
            results.append((name, success, elapsed, tail))
        else:
            # 다수 단계 — ProcessPoolExecutor로 동시 실행
            logger.info(
                "🔀 동시 실행: %s",
                ", ".join(s.name for s in ready),
            )
            with ProcessPoolExecutor(max_workers=len(ready)) as executor:
                futures = {
                    executor.submit(run_step, step, extra_args, timeout): step
                    for step in ready
                }
                for future in as_completed(futures):
                    step = futures[future]
                    try:
                        name, success, elapsed, tail = future.result()
                    except Exception as e:
                        name = step.name
                        success = False
                        elapsed = 0.0
                        tail = str(e)
                        logger.error("💥 [%s] executor 예외: %s", name, e)

                    completed[name] = success
                    results.append((name, success, elapsed, tail))

    # 최종 리포트
    total_elapsed = time.monotonic() - total_start
    logger.info("")
    logger.info("=" * 60)
    logger.info("Pipeline 결과 요약 (총 소요: %.1f초)", total_elapsed)
    logger.info("-" * 60)

    all_success = True
    for name, success, elapsed, _ in results:
        status = "✅" if success else "❌"
        logger.info("  %s %-20s  %.1f초", status, name, elapsed)
        if not success:
            all_success = False

    not_run = [
        s.name for s in active_steps if s.name not in completed
    ]
    if not_run:
        for name in not_run:
            logger.info("  ⏭️  %-20s  (건너뜀 — 의존성 실패)", name)
        all_success = False

    logger.info("=" * 60)

    if all_success:
        logger.info("🎉 전체 파이프라인 성공!")
    else:
        logger.error("⚠️  일부 단계 실패 — 위 로그를 확인하세요.")

    return all_success


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="PharmPort Enrichment Pipeline 오케스트레이터",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Phase 구성:
  1, 1a, 1b, 1c  — 외부 데이터 수집
  1.5             — 프로파일 해싱/클러스터링
  2, 2a, 2b      — 신규 DB 생성 + LLM 가이드 생성

예시:
  python run_pipeline.py                          # 전체
  python run_pipeline.py --phase 1b --workers 4   # Phase 1-B 4워커
  python run_pipeline.py --phase 2 --dry-run      # Phase 2 dry-run
  python run_pipeline.py --limit 50 --workers 2   # 각 50건씩, 2워커
""",
    )
    parser.add_argument(
        "--phase",
        help="실행할 Phase (1, 1a, 1b, 1c, 1.5, 2, 2a, 2b)",
    )
    parser.add_argument(
        "--workers", type=int, default=1,
        help="각 스크립트에 전달할 병렬 워커 수 (기본 1)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="각 단계의 처리 건수 제한 (기본 0=전체)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="전체 단계 dry-run 모드",
    )
    parser.add_argument(
        "--dev", action="store_true",
        help="dev DB 사용",
    )
    parser.add_argument(
        "--timeout", type=int, default=7200,
        help="단계별 타임아웃 초 (기본 7200=2시간)",
    )
    parser.add_argument(
        "--step", nargs="+",
        help="특정 단계만 실행 (예: --step chembl fda)",
    )
    args = parser.parse_args()

    # --step 으로 특정 단계만 실행
    if args.step:
        global STEPS
        step_names = set(args.step)
        STEPS = [s for s in STEPS if s.name in step_names]
        if not STEPS:
            logger.error("지정된 단계를 찾을 수 없음: %s", args.step)
            sys.exit(1)

    success = run_pipeline(
        phase_filter=args.phase,
        workers=args.workers,
        limit=args.limit,
        dry_run=args.dry_run,
        dev=args.dev,
        timeout=args.timeout,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
