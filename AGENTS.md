# PharmPort Agent Guide

## Project Identity

PharmPort is a pharmaceutical data enrichment pipeline. It matches Korean medicines to HIRA ingredient codes, enriches from 5 external APIs, and generates bilingual medication guides via LLM.

## Quick Start

```bash
python run_pipeline.py                    # Full pipeline
python run_pipeline.py --phase 1b        # Phase 1-B only
python run_pipeline.py --dry-run         # Dry run (no DB writes)
python enrich_chembl.py --limit 10       # Single script, 10 records
```

## Documentation Map

| Document | Purpose | When to Read |
|----------|---------|--------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, data flow, module map | Understanding system structure |
| [docs/DESIGN.md](docs/DESIGN.md) | Design patterns and key decisions | Before making architectural changes |
| [docs/design-docs/core-beliefs.md](docs/design-docs/core-beliefs.md) | Foundational engineering principles | Before any design decision |
| [docs/design-docs/layer-rules.md](docs/design-docs/layer-rules.md) | Layer dependency rules | Before adding imports or new modules |
| [docs/QUALITY.md](docs/QUALITY.md) | Quality standards, thresholds | Modifying matching or enrichment logic |
| [docs/QUALITY_SCORE.md](docs/QUALITY_SCORE.md) | Quality scorecard across dimensions | Assessing project health |
| [docs/RELIABILITY.md](docs/RELIABILITY.md) | Resilience, recovery, operational controls | Debugging failures or adding steps |
| [docs/SECURITY.md](docs/SECURITY.md) | Secrets, network, data security | Handling credentials or DB access |
| [docs/PRODUCT_SENSE.md](docs/PRODUCT_SENSE.md) | What PharmPort does and why | Understanding business context |
| [docs/FRONTEND.md](docs/FRONTEND.md) | Frontend status (none; output consumers) | Understanding data consumers |
| [docs/PLANS.md](docs/PLANS.md) | Active plans and milestones | Understanding roadmap |
| [docs/generated/db-schema.md](docs/generated/db-schema.md) | Database schema reference | Working with tables |
| [docs/exec-plans/tech-debt-tracker.md](docs/exec-plans/tech-debt-tracker.md) | Known tech debt | Prioritizing improvements |

## Layer Architecture

```
L4 Orchestration   run_pipeline.py
L3 Generation      build_profiles.py, create_v2_tables.py, generate_medication_guide.py, generate_yakho_desc.py
L2 Enrichment      create_enrichment_tables.py, enrich_chembl/fda/opentargets/pubmed/trials.py, enrichment_report.py
L1 Matching        match_ingredient_v2.py, sort_and_embed.py
L0 Infrastructure  common.py, embedding_service.py, enrich_base.py, analysis.py
```

**Rule**: Each layer imports only from L0. Cross-layer data flows through the database. See [layer-rules.md](docs/design-docs/layer-rules.md).

## Critical Rules

1. **Never import across layers** (L1/L2/L3 only import from L0)
2. **Never modify source DB** (`teoul_pharminfo` is read-only; write to `teoul_pharminfo_v2` or `edb_*`)
3. **Always add `--dry-run` support** to new scripts
4. **Always use `enrich_base.py` utilities** for rate limiting, status tracking, batch insert
5. **Register new steps** in `run_pipeline.py` STEPS list with correct phase and dependencies
6. **Profile hash changes** require regeneration flag update

## Common Patterns

### Adding a New Enrichment Source
1. Create `enrich_newsource.py` in L2
2. Import only from `common.py` and `enrich_base.py` (L0)
3. Use `api_call_with_retry()` for API calls
4. Use `batch_insert()` for DB writes
5. Update `edb_enrichment_status` via `update_status()`
6. Add `--dry-run`, `--limit`, `--dev`, `--workers` CLI flags
7. Register in `run_pipeline.py` STEPS with dependencies

### Adding a New Generation Script
1. Create script in L3
2. Import from `common.py` and `enrich_base.py` only
3. Query enrichment data from `edb_*` tables
4. Write results to `teoul_pharminfo_v2`
5. Use profile hash for deduplication

## Environment Setup

```bash
cp .env.example .env    # Configure credentials
pip install -r requirements.txt
python run_pipeline.py --dry-run --limit 5   # Verify setup
```

Required: Python 3.12+, Azure PostgreSQL access, API keys for Azure OpenAI, Anthropic, DeepL.

## Existing Documentation (Pre-Harness)

| File | Content |
|------|---------|
| `docs/enrichment-format-parity.md` | Enrichment + Format Parity master plan (RALPLAN-DR) |
| `docs/unmatched-recovery.md` | 11,641 unmatched records recovery strategy |
| `docs/methodology.md` | 3-filter matching methodology |
| `pharmport_erd.dbml` | Core PharmPort DBML schema |
| `productinfos_erd.dbml` | ProductInfos DBML schema |
| `teoul_pharminfo_full_erd.dbml` | Full database DBML schema |
