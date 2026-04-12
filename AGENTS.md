# PharmPort

Pharmaceutical data enrichment pipeline: matches Korean medicines to HIRA ingredient codes, enriches from 5 external APIs, generates bilingual medication guides via LLM.

## Quick Reference

- **DB**: Azure PostgreSQL (`teoul_pharminfo` source, `teoul_pharminfo_v2` generated content)
- **Stack**: Python 3.12+ / psycopg2 / pgvector / Azure OpenAI Embeddings / Claude Sonnet 4 / DeepL
- **Entry point**: `python run_pipeline.py` (DAG-based orchestrator)
- **Core principle**: 0% error rate on ingredient matching (unmatched OK, false match never)

## Quick Start

```bash
python run_pipeline.py                    # Full pipeline
python run_pipeline.py --phase 1b        # Phase 1-B only
python run_pipeline.py --dry-run         # Dry run (no DB writes)
python enrich_chembl.py --limit 10       # Single script, 10 records
```

## Agent Instructions

Before making changes, read the relevant documentation:
- Architecture decisions: [ARCHITECTURE.md](ARCHITECTURE.md) and [docs/DESIGN.md](docs/DESIGN.md)
- Layer rules: [docs/design-docs/layer-rules.md](docs/design-docs/layer-rules.md) -- **never violate import constraints**
- Core beliefs: [docs/design-docs/core-beliefs.md](docs/design-docs/core-beliefs.md)
- Quality standards: [docs/QUALITY.md](docs/QUALITY.md)

## Knowledge Base

| Document | What it covers | When to Read |
|----------|---------------|--------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture (root-level) | Understanding system structure |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, data flow, module map, dual-DB architecture | Understanding system structure |
| [docs/DESIGN.md](docs/DESIGN.md) | Design patterns and key decisions | Before making architectural changes |
| [docs/design-docs/core-beliefs.md](docs/design-docs/core-beliefs.md) | Foundational engineering principles | Before any design decision |
| [docs/design-docs/layer-rules.md](docs/design-docs/layer-rules.md) | Layer dependency rules and import constraints | Before adding imports or new modules |
| [docs/QUALITY.md](docs/QUALITY.md) | Quality standards, matching validation, rate limits, LLM QA | Modifying matching or enrichment logic |
| [docs/QUALITY_SCORE.md](docs/QUALITY_SCORE.md) | Quality scorecard across dimensions | Assessing project health |
| [docs/RELIABILITY.md](docs/RELIABILITY.md) | Pipeline resilience, failure recovery, operational controls | Debugging failures or adding steps |
| [docs/SECURITY.md](docs/SECURITY.md) | Security posture, secrets management | Handling credentials or DB access |
| [docs/PRODUCT_SENSE.md](docs/PRODUCT_SENSE.md) | Product context and user needs | Understanding business context |
| [docs/PLANS.md](docs/PLANS.md) | Active plans and roadmap | Understanding roadmap |
| [docs/FRONTEND.md](docs/FRONTEND.md) | Frontend status (backend-only project) | Understanding data consumers |
| [docs/generated/db-schema.md](docs/generated/db-schema.md) | Database schema reference | Working with tables |
| [docs/design-docs/index.md](docs/design-docs/index.md) | Design document index | Finding design docs |
| [docs/product-specs/index.md](docs/product-specs/index.md) | Product specifications index | Finding product specs |
| [docs/exec-plans/tech-debt-tracker.md](docs/exec-plans/tech-debt-tracker.md) | Known tech debt items | Prioritizing improvements |

## Layer Map

```
L4 Orchestration   run_pipeline.py
L3 Generation      build_profiles.py, create_v2_tables.py, generate_medication_guide.py, generate_yakho_desc.py
L2 Enrichment      create_enrichment_tables.py, enrich_chembl/fda/opentargets/pubmed/trials.py, enrichment_report.py
L1 Matching        match_ingredient_v2.py, sort_and_embed.py
L0 Infrastructure  common.py, embedding_service.py, enrich_base.py
```

**Rule**: Each layer imports only from L0. Cross-layer data flows through the database, not imports. See [layer-rules.md](docs/design-docs/layer-rules.md).

## Pipeline Phases

```
Phase 0   create_enrichment_tables.py     DDL for edb_* tables
Phase 1-A enrich_chembl.py               ChEMBL mapping + MoA + ADMET
Phase 1-B enrich_fda/opentargets/pubmed/trials.py  (parallel after 1-A)
Phase 1-C enrichment_report.py           Coverage report
Phase 1.5 build_profiles.py              Profile hashing + clustering
Phase 2-A create_v2_tables.py            V2 DB DDL + migration
Phase 2-B generate_medication_guide.py   Claude + DeepL medication guides
          generate_yakho_desc.py         Claude + DeepL pharmacology descriptions
```

## Common CLI Flags

All scripts support: `--dry-run`, `--limit N`, `--dev`, `--workers N`

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
# Create .env with required credentials (see docs/SECURITY.md for variable list)
pip install -r requirements.txt
python run_pipeline.py --dry-run --limit 5   # Verify setup
```

Required: Python 3.12+, Azure PostgreSQL access, API keys for Azure OpenAI, Anthropic, DeepL.

> Be concise. No filler. Straight to the point. Use fewer words.


## TDD 필수

모든 새 기능/로직 변경은 반드시 TDD로 개발한다.
1. Red: 실패하는 테스트 먼저 작성
2. Green: 테스트를 통과하는 최소 코드 작성
3. Refactor: 코드 정리
테스트 없는 코드 변경은 허용하지 않는다.
