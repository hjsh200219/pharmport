# PharmPort Architecture

## System Overview

PharmPort is a pharmaceutical data enrichment pipeline built in Python. It operates as a batch processing system with no web server, API, or frontend -- purely CLI-driven scripts orchestrated by a DAG executor.

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Primary DB | Azure PostgreSQL Flexible Server (`teoul_pharminfo`) |
| Generated DB | Azure PostgreSQL (`teoul_pharminfo_v2`) |
| Embeddings | Azure OpenAI `text-embedding-3-large` (3072-dim vectors) |
| Vector Extension | pgvector |
| LLM | Claude Sonnet 4 (via Anthropic API) |
| Translation | DeepL API (EN -> KO) |
| DB Driver | psycopg2-binary |
| Config | python-dotenv (.env) |

## Pipeline Architecture

```
                        +-----------------------+
                        |   run_pipeline.py     |  L4: DAG Orchestrator
                        |   (subprocess spawn)  |
                        +----------+------------+
                                   |
              +--------------------+--------------------+
              |                    |                    |
    +---------v--------+  +-------v--------+  +--------v--------+
    | Phase 1-A        |  | Phase 1-B      |  | Phase 2-B       |
    | enrich_chembl.py |  | enrich_fda.py  |  | generate_*      |
    |                  |  | enrich_ot.py   |  | (Claude+DeepL)  |
    +--------+---------+  | enrich_pub.py  |  +--------+--------+
             |            | enrich_tri.py  |           |
             |            +-------+--------+           |
             |                    |                    |
             +--------------------+--------------------+
                                  |
                        +---------v---------+
                        |   enrich_base.py  |  L0: Rate limiter,
                        |   common.py       |      Status tracking,
                        |   embedding_svc   |      DB connections
                        +-------------------+
```

## Data Flow

```
pharmport_medicine (40,837 medicines)
    |
    | match_ingredient_v2.py (3-filter: reciprocal + ingredient + manufacturer)
    v
터울주성분 (20,235 HIRA ingredient codes) --> product_code, ingredient_code
    |
    | Phase 0: DDL (edb_* tables)
    | Phase 1-A: ChEMBL (mapping + mechanism + ADMET)
    | Phase 1-B: FDA, OpenTargets, PubMed, ClinicalTrials (parallel)
    | Phase 1-C: Coverage report
    v
edb_* tables (enrichment data)
    |
    | Phase 1.5: SHA-256 profile hash -> cluster_id
    v
edb_enrichment_status (profile_hash, cluster_id)
    |
    | Phase 2-A: V2 DB DDL + migration
    | Phase 2-B: Claude + DeepL medication guides
    v
teoul_pharminfo_v2 (터울복약안내, 터울약효설명)
```

## Layer Architecture

### L0 -- Infrastructure
| File | Responsibility |
|------|---------------|
| `common.py` | DB connection factory (SSL, keepalive, multi-DB routing) |
| `embedding_service.py` | Azure OpenAI embedding API, batch parallelism |
| `enrich_base.py` | Rate limiter, status tracking, batch insert, Layer 1 validation |

### L1 -- Matching
| File | Responsibility |
|------|---------------|
| `match_ingredient_v2.py` | 3-filter matching (reciprocal best match + ingredient + manufacturer) |
| `match_ingredient.py` | Deprecated single-channel matching |
| `sort_and_embed.py` | Sorted ingredient embedding pipeline |

### L2 -- Enrichment
| File | Responsibility |
|------|---------------|
| `create_enrichment_tables.py` | DDL for 10 edb_* tables |
| `enrich_chembl.py` | ChEMBL compound mapping + MoA + ADMET |
| `enrich_fda.py` | openFDA labeling + FAERS adverse events |
| `enrich_opentargets.py` | OpenTargets disease associations |
| `enrich_pubmed.py` | PubMed literature mining |
| `enrich_trials.py` | ClinicalTrials.gov trial data |
| `enrich_new_ingredient.py` | Incremental enrichment for new codes |
| `enrichment_report.py` | Coverage and quality reporting |

### L3 -- Generation
| File | Responsibility |
|------|---------------|
| `build_profiles.py` | SHA-256 profile hashing + clustering |
| `create_v2_tables.py` | V2 DB DDL + data migration |
| `generate_medication_guide.py` | Claude + DeepL medication guides (A4/A5) |
| `generate_yakho_desc.py` | Claude + DeepL pharmacological descriptions |

### L4 -- Orchestration
| File | Responsibility |
|------|---------------|
| `run_pipeline.py` | DAG-based pipeline executor (subprocess + ProcessPoolExecutor) |

## Database Architecture

### Dual-DB Strategy
- **teoul_pharminfo** (source): Never modified by pipeline. Contains medicines, products, manufacturers, HIRA codes, enrichment data.
- **teoul_pharminfo_v2** (generated): All LLM-generated content. Mirrored source tables + generated columns.

### Key Tables
| Table | DB | Records | Role |
|-------|-----|---------|------|
| `pharmport_medicine` | source | 40,837 | Hub table with embeddings |
| `터울주성분` | source | 20,235 | HIRA ingredient master |
| `ProductInfos` | source | 48,027 | Product master |
| `edb_enrichment_status` | source | ~6,956 | Checkpoint tracking |
| `edb_*` (10 tables) | source | varies | Enrichment data |
| `터울복약안내A4/A5` | v2 | varies | Medication guides |
| `터울약효설명` | v2 | varies | Pharmacological descriptions |
| `터울복약프로파일` | v2 | varies | Profile hash + cluster |

## External Dependencies

| API | Module | Rate Limit |
|-----|--------|-----------|
| ChEMBL REST | enrich_chembl.py | 3 RPS |
| openFDA | enrich_fda.py | 4 RPS |
| OpenTargets GraphQL | enrich_opentargets.py | 5 RPS |
| PubMed E-utilities | enrich_pubmed.py | 3 RPS |
| ClinicalTrials.gov | enrich_trials.py | 3 RPS |
| Azure OpenAI Embedding | embedding_service.py | Managed |
| Anthropic Claude | generate_*.py | Managed |
| DeepL | generate_*.py | Managed |

## Concurrency Model

- **Inter-step**: ProcessPoolExecutor in `run_pipeline.py` (parallel independent phases)
- **Intra-step**: ThreadPoolExecutor in `enrich_base.py` (parallel API calls within a step)
- **Embedding**: ThreadPoolExecutor with 8 workers, 100-item batch chunks
- **DB**: Per-thread connections via `get_thread_connection()`
