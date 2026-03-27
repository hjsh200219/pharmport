# PharmPort Design Overview

## Design Philosophy

PharmPort follows a **pipeline architecture** with strict layer isolation. Each module belongs to exactly one layer, and communication between layers flows through the database, not direct imports.

## Architecture Patterns

### 1. Layered Pipeline (L0-L4)

```
L4  Orchestration   run_pipeline.py              (DAG executor, subprocess-based)
L3  Generation      build_profiles / create_v2 / generate_*   (LLM + DeepL)
L2  Enrichment      enrich_chembl/fda/opentargets/pubmed/trials (5 external APIs)
L1  Matching        match_ingredient_v2 / sort_and_embed       (embedding-based)
L0  Infrastructure  common / embedding_service / enrich_base   (DB, API, utilities)
```

Every layer imports only from L0. The orchestrator (L4) spawns scripts as subprocesses.

### 2. Dual-Database Separation

- **teoul_pharminfo**: Source data (read-only from pipeline)
- **teoul_pharminfo_v2**: Generated content (LLM outputs, profiles)

This prevents any pipeline bug from corrupting source data.

### 3. Status-Driven Resumability

`edb_enrichment_status` acts as a checkpoint table:
- Boolean + timestamp pairs per enrichment step
- `get_pending_codes()` queries for incomplete records
- Re-execution skips completed work automatically

### 4. Profile Hash Clustering

Instead of generating LLM content per-medicine:
1. Build SHA-256 hash from 6 enrichment fields
2. Assign cluster IDs to identical hashes
3. Generate content once per cluster
4. Share across all medicines in the cluster

## Design Documents

| Document | Description |
|----------|-------------|
| [design-docs/core-beliefs.md](design-docs/core-beliefs.md) | Foundational engineering principles |
| [design-docs/layer-rules.md](design-docs/layer-rules.md) | Layer dependency rules and import graph |
| [design-docs/index.md](design-docs/index.md) | Design document index |

## Key Design Decisions

1. **0% error matching**: Reciprocal Top-1 + 3-channel consensus. Coverage is secondary to accuracy.
2. **English-first bilingual**: Claude EN -> DeepL KO -> Claude refine. Better medical terminology accuracy.
3. **Database as bus**: No cross-layer imports. Data flows through PostgreSQL tables.
4. **Subprocess orchestration**: `run_pipeline.py` runs scripts as child processes, not function calls. Clean isolation.
5. **Token-bucket rate limiting**: Per-API-source configuration prevents throttling across parallel workers.
