# PharmPort Quality Standards

## Core Quality Principle

**Zero Error Rate** — no false matches. Unmatched records are acceptable; incorrect matches are not.

## Matching Quality (match_ingredient_v2.py)

### 3-Filter Validation
1. **Text Exact Match GT**: `medicine_name = ProductInfos.Name` (21,706 records) used for calibration
2. **Reciprocal Best Match**: A->B Top-1 AND B->A Top-1 on medicine name embeddings
3. **Multi-Channel Consensus**: medicine name + ingredient + manufacturer all must pass thresholds

### Current Results
| Metric | Value |
|--------|-------|
| Total medicines | 40,837 |
| Matched | 29,196 (71.5%) |
| Error rate | 0% (verified on 20,666 GT records) |
| Covered HIRA codes | 6,956 / 20,235 (34.4%) |

### Threshold Calibration
- Ingredient cosine similarity: >= 0.4820
- Manufacturer cosine similarity: >= 0.1677
- Thresholds derived from GT Calibration Set (70%) and validated on Validation Set (30%)
- Any threshold relaxation requires human review

## Enrichment Quality (enrich_base.py)

### Rate Limiting
Token-bucket rate limiter per API source:
| Source | RPS | Burst | Max Retries |
|--------|-----|-------|-------------|
| ChEMBL | 3.0 | 3 | 3 |
| OpenTargets | 5.0 | 5 | 3 |
| openFDA | 4.0 | 4 | 3 |
| PubMed | 3.0 | 3 | 3 |
| ClinicalTrials | 3.0 | 3 | 3 |

### Status Tracking
- `edb_enrichment_status` table tracks per-code, per-step completion
- Boolean + timestamp columns: `chembl_mapped`, `chembl_mapped_at`, etc.
- `last_error` column preserves failure context
- Layer 1 automatic integrity validation after each enrichment step

### Retry Strategy
- Exponential backoff: `retry_backoff ^ attempt` seconds
- Max 3 retries per API call
- Thread-safe connection management for parallel workers

## LLM Generation Quality (Phase 2)

### Medication Guide Pipeline
1. Only `validation_status = 'expert_reviewed'` data used for safety-critical sections
2. English generation via Claude Sonnet 4
3. DeepL translation (EN -> KO)
4. Claude Korean refinement (medical terminology correction)
5. `llm_version` tracking for regeneration control

### Profile-Based Deduplication
- SHA-256 hash of 6 enrichment fields (mechanism, side_effects, contraindications, interactions, monitoring, special_pop)
- Identical profiles share generated content -> no redundant LLM calls
- `needs_regeneration` flag when underlying enrichment data changes

## Data Integrity

### Connection Reliability
- SSL required (`sslmode: require`)
- TCP keepalive: idle=30s, interval=10s, count=5
- Context manager pattern: auto-commit on success, rollback on exception

### Pipeline Orchestration
- DAG-based dependency resolution in `run_pipeline.py`
- Independent phases run in parallel (ProcessPoolExecutor)
- Dependent phases wait for predecessors
- Per-step timeout (default 7200s)
- Dry-run mode for all scripts
