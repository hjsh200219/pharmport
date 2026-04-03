# Layer Dependency Rules

## Layer Definitions

```
Layer 0 — Infrastructure
  common.py, embedding_service.py, enrich_base.py

Layer 1 — Matching
  match_ingredient_v2.py, match_ingredient.py, sort_and_embed.py

Layer 2 — Schema & Enrichment
  create_enrichment_tables.py
  enrich_chembl.py, enrich_fda.py, enrich_opentargets.py
  enrich_pubmed.py, enrich_trials.py, enrich_new_ingredient.py
  enrichment_report.py

Layer 3 — Profile & Generation
  build_profiles.py
  create_v2_tables.py
  generate_medication_guide.py, generate_yakho_desc.py

Layer 4 — Orchestration
  run_pipeline.py
```

## Dependency Rules

### Allowed Dependencies
```
Layer 4 -> Layer 3, 2, 1, 0  (orchestrator can reference any layer)
Layer 3 -> Layer 0             (generation imports common, enrich_base)
Layer 2 -> Layer 0             (enrichment imports common, enrich_base)
Layer 1 -> Layer 0             (matching imports common, embedding_service)
Layer 0 -> (external only)     (psycopg2, openai, dotenv)
```

### Forbidden Dependencies
```
Layer 0 -> Layer 1, 2, 3      (infrastructure must not know about business logic)
Layer 1 -> Layer 2, 3          (matching must not depend on enrichment)
Layer 2 -> Layer 1, 3          (enrichment must not depend on matching or generation)
Layer 3 -> Layer 1, 2          (generation must not import enrichment scripts)
```

### Cross-Layer Communication
- **Layer 1 -> Layer 2**: Via database only (product_code, ingredient_code in pharmport_medicine)
- **Layer 2 -> Layer 3**: Via database only (edb_enrichment_status, edb_* tables)
- **Layer 4 -> All**: Via subprocess execution (run_pipeline.py spawns scripts as child processes)

## Import Graph (Current)

```
common.py         <- enrich_base.py, analysis.py, all enrich_*.py, all generate_*.py, all create_*.py
embedding_service.py <- sort_and_embed.py, match_ingredient_v2.py, match_ingredient.py
enrich_base.py    <- enrich_chembl.py, enrich_fda.py, enrich_opentargets.py,
                     enrich_pubmed.py, enrich_trials.py, enrich_new_ingredient.py,
                     enrichment_report.py, build_profiles.py,
                     generate_medication_guide.py, generate_yakho_desc.py
```

## External API Dependencies

| Module | External APIs |
|--------|--------------|
| embedding_service.py | Azure OpenAI Embedding API |
| enrich_chembl.py | ChEMBL REST API (ebi.ac.uk) |
| enrich_fda.py | openFDA Drug Labeling + FAERS API |
| enrich_opentargets.py | Open Targets GraphQL API |
| enrich_pubmed.py | PubMed E-utilities API |
| enrich_trials.py | ClinicalTrials.gov API |
| generate_medication_guide.py | Anthropic Claude API, DeepL API |
| generate_yakho_desc.py | Anthropic Claude API, DeepL API |

## Adding New Modules

1. Determine the correct layer based on functionality
2. Only import from lower layers (Layer 0 for most cases)
3. Communicate with other layers via database, not direct imports
4. Add `--dry-run`, `--limit`, `--dev` flags for operational control
5. Use `enrich_base.py` utilities: rate limiter, status tracking, batch insert
6. Register in `run_pipeline.py` STEPS list with correct phase and dependencies
