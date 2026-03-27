# PharmPort Architecture

## System Purpose

PharmPort is a pharmaceutical data enrichment pipeline that:
1. Matches 40,837 PharmPort medicines to 20,235 HIRA ingredient codes (심평원성분코드) with 0% error rate
2. Enriches matched ingredients from 5 external APIs (ChEMBL, openFDA, OpenTargets, PubMed, ClinicalTrials)
3. Generates LLM-powered medication guides (복약안내) and pharmacological descriptions (약효설명)

## Infrastructure

| Component | Technology |
|-----------|-----------|
| Primary DB | Azure PostgreSQL Flexible Server (`teoul_pharminfo`) |
| V2 DB | Azure PostgreSQL (`teoul_pharminfo_v2`) — LLM-generated content |
| Embedding | Azure OpenAI `text-embedding-3-large` (3072-dim vectors) |
| LLM | Claude Sonnet 4 (medication guide generation) |
| Translation | DeepL API (EN -> KO) |
| Language | Python 3.12+ |
| Vector Ext | pgvector |

## Data Flow

```
pharmport_medicine (40,837)
    |
    | match_ingredient_v2.py (3-filter: reciprocal match + ingredient + manufacturer)
    | -> product_code, ingredient_code
    v
터울주성분 (20,235) -- 심평원성분코드 PK
    |
    | Phase 0: create_enrichment_tables.py (edb_* 10 tables DDL)
    | Phase 1-A: enrich_chembl.py (mapping + mechanism + ADMET)
    | Phase 1-B: enrich_fda.py, enrich_opentargets.py, enrich_pubmed.py, enrich_trials.py
    | Phase 1-C: enrichment_report.py
    v
edb_* tables (enrichment data in teoul_pharminfo)
    |
    | Phase 1.5: build_profiles.py (SHA-256 hash -> cluster_id)
    v
edb_enrichment_status (profile_hash, cluster_id)
    |
    | Phase 2-A: create_v2_tables.py (DDL + data migration to teoul_pharminfo_v2)
    | Phase 2-B: generate_medication_guide.py (Claude + DeepL)
    |            generate_yakho_desc.py (Claude + DeepL)
    v
teoul_pharminfo_v2 (터울복약안내A4, 터울약효설명, etc.)
```

## Module Map

### Core Infrastructure
| File | Purpose |
|------|---------|
| `common.py` | DB connection factory (psycopg2, SSL, env-based config) |
| `embedding_service.py` | Azure OpenAI embedding API + ingredient sort logic |
| `enrich_base.py` | Shared enrichment utilities: rate limiter, status tracking, batch insert, Layer 1 validation |
| `run_pipeline.py` | DAG-based pipeline orchestrator (subprocess + ProcessPoolExecutor) |

### Matching Layer
| File | Purpose |
|------|---------|
| `match_ingredient_v2.py` | Method 2: GT-independent 3-filter matching (current, 0% error) |
| `match_ingredient.py` | Method 1: single-channel matching (deprecated) |
| `sort_and_embed.py` | Sorted ingredient embedding pipeline |
| `analysis.py` | Table data access helpers |

### Enrichment Layer (Phase 1)
| File | Purpose |
|------|---------|
| `create_enrichment_tables.py` | Phase 0: edb_* DDL (10 tables) |
| `enrich_chembl.py` | Phase 1-A: ChEMBL compound mapping + MoA + ADMET |
| `enrich_fda.py` | Phase 1-B: openFDA labeling + FAERS adverse events |
| `enrich_opentargets.py` | Phase 1-B: Open Targets disease associations |
| `enrich_pubmed.py` | Phase 1-B: PubMed literature mining |
| `enrich_trials.py` | Phase 1-B: ClinicalTrials.gov trial data |
| `enrich_new_ingredient.py` | Incremental enrichment for newly detected codes |
| `enrichment_report.py` | Phase 1-C: coverage/quality report |

### Profile & Generation Layer (Phase 1.5-2)
| File | Purpose |
|------|---------|
| `build_profiles.py` | Phase 1.5: SHA-256 profile hashing + clustering |
| `create_v2_tables.py` | Phase 2-A: V2 DB DDL + data migration |
| `generate_medication_guide.py` | Phase 2-B: Claude medication guide (EN -> DeepL KO -> Claude refine) |
| `generate_yakho_desc.py` | Phase 2-B: Claude pharmacological descriptions |

### Schema Definitions
| File | Purpose |
|------|---------|
| `pharmport_erd.dbml` | PharmPort core tables DBML |
| `productinfos_erd.dbml` | ProductInfos extended DBML |
| `teoul_pharminfo_full_erd.dbml` | Full DB ERD |

## Database Architecture (Dual-DB)

**teoul_pharminfo** (source DB):
- `pharmport_medicine` — hub table (40,837 medicines)
- `pharmport_extra_text` / `pharmport_medicine_extra` — N:M extra info
- `pharmport_usage_text` / `pharmport_medicine_usage` — N:M usage info
- `pharmport_비교` — comparison data with embeddings
- `ProductInfos` — product master (48,027)
- `Manufacturers` — manufacturer master (659)
- `터울주성분` — HIRA ingredient master (20,235)
- `edb_*` tables — enrichment data (10 tables)

**teoul_pharminfo_v2** (generated content DB):
- Mirrored source tables + LLM-generated columns
- `터울복약프로파일` — profile hash + cluster
- `터울복약안내A4` / `터울복약안내A5` — medication guides
- `터울약효설명` — pharmacological descriptions (with LLM columns)
- Compatibility views for legacy app support

## Key Design Decisions

1. **0% Error Matching**: Reciprocal Top-1 + 3-channel consensus. Unmatched is acceptable; false match is not.
2. **심평원성분코드 1-4 Optimization**: Codes sharing first 4 digits share pharmacological base — single API call per base, results copied to all variants.
3. **Profile Hash Clustering**: SHA-256 of 6 enrichment fields -> identical profiles share LLM-generated content, avoiding redundant API calls.
4. **English-First Bilingual**: Claude generates English -> DeepL translates -> Claude refines Korean medical terminology.
5. **Dual-DB Separation**: Source data untouched in teoul_pharminfo; all generated content in teoul_pharminfo_v2.
