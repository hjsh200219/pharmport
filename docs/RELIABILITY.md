# PharmPort Reliability

## Pipeline Resilience

### Orchestrator (run_pipeline.py)
- **DAG execution**: topological ordering with dependency tracking
- **Parallel execution**: independent phases run concurrently via ProcessPoolExecutor
- **Failure isolation**: failed step blocks only its dependents, not sibling branches
- **Timeout protection**: per-step timeout (default 2 hours), catches TimeoutExpired
- **Phase granularity**: `--phase`, `--step` flags allow selective re-execution

### Enrichment Workers (enrich_*.py)
- **Idempotent by design**: `edb_enrichment_status` tracks per-code completion; re-runs skip already-done records
- **Thread-safe DB**: `get_thread_connection()` provides per-thread psycopg2 connections
- **Token-bucket rate limiter**: prevents API throttling with per-source configuration
- **Exponential backoff**: 3 retries with `backoff^attempt` delay
- **Batch processing**: configurable `--limit`, `--batch-size` for controlled execution

### Embedding Service (embedding_service.py)
- **Batch parallelism**: splits into 100-item chunks, processes via ThreadPoolExecutor (8 workers)
- **Retry with backoff**: 3 attempts with increasing delay (5s, 10s, 15s)
- **Progress logging**: periodic batch completion reporting

## Database Reliability

### Connection Management (common.py)
- **SSL required**: all connections use `sslmode=require`
- **TCP keepalive**: `idle=30s`, `interval=10s`, `count=5` prevents silent disconnects
- **Context manager**: `get_cursor()` auto-commits on success, rolls back on exception, closes connection in finally
- **Multi-DB routing**: separate connection factories for teoul_pharminfo, teoul_pharminfo_v2, vector DB, dev DB
- **Environment validation**: raises ValueError on missing connection parameters

### Data Safety
- **Dual-DB isolation**: source data (teoul_pharminfo) never modified by enrichment/generation pipeline; all generated content goes to teoul_pharminfo_v2
- **UNIQUE constraints**: prevent duplicate enrichment records (per-code, per-source)
- **IF NOT EXISTS**: all DDL uses `CREATE TABLE IF NOT EXISTS` for safe re-execution
- **Batch commits**: large operations commit in configurable batch sizes (default 5000)

## Failure Recovery

### Re-execution Strategy
1. **Pipeline level**: `python run_pipeline.py --phase 1b` re-runs only Phase 1-B
2. **Script level**: `python enrich_chembl.py --code 101301AIJ` re-processes a single code
3. **Status-based resume**: pending codes query (`get_pending_codes()`) automatically finds incomplete records
4. **Match method tagging**: `match_method` column enables selective rollback of specific matching strategies

### Monitoring
- `enrichment_report.py` generates coverage/quality reports after Phase 1
- Per-step success/failure logging with elapsed time
- Pipeline summary report at completion (pass/fail per step)
- `--stats` flag on generation scripts for progress monitoring

## Operational Controls

| Flag | Purpose |
|------|---------|
| `--dry-run` | All scripts support dry-run (no DB writes) |
| `--limit N` | Process at most N records |
| `--workers N` | Control parallelism |
| `--dev` | Use dev DB (teoul_201201) |
| `--step X` | Run specific pipeline step |
| `--verify` | V2 migration verification (row count comparison) |
| `--recompute` | Force recompute existing profile hashes |
