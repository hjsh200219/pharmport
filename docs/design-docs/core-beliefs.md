# Core Beliefs

Foundational principles that guide all PharmPort design and engineering decisions.

## 1. Zero Error Rate Over Coverage

False matches are never acceptable. Unmatched records are tolerable.
- Ingredient matching uses 3-filter consensus (reciprocal best match + ingredient + manufacturer)
- Threshold relaxation requires human review
- Current: 29,196/40,837 matched (71.5%) with 0% error on 20,666 GT records

## 2. Source Data Is Sacred

The source database (`teoul_pharminfo`) is read-only from the pipeline's perspective.
- All generated/enriched content goes to `teoul_pharminfo_v2` or `edb_*` tables
- Dual-DB architecture enforces this separation at the connection level
- No pipeline step modifies source tables

## 3. Database as Integration Bus

Modules communicate through the database, not through direct imports.
- Layer rules enforce this: L1-L3 import only from L0 (infrastructure)
- Cross-layer data flows through shared tables (`pharmport_medicine`, `edb_enrichment_status`)
- The orchestrator (L4) uses subprocess execution, not function calls

## 4. Idempotency by Default

Every pipeline step can be re-executed safely without side effects.
- `edb_enrichment_status` tracks per-code, per-step completion
- `CREATE TABLE IF NOT EXISTS` for all DDL
- `ON CONFLICT DO NOTHING` for enrichment inserts
- Re-runs skip already-completed records automatically

## 5. English-First Bilingual

Medical content generation follows a deliberate language pipeline.
- Claude generates in English (higher quality medical terminology)
- DeepL translates EN -> KO
- Claude refines Korean medical terminology
- This produces more accurate medical content than direct Korean generation

## 6. Profile Deduplication Over Brute Force

Identical enrichment profiles share generated content.
- SHA-256 hash of 6 enrichment fields identifies identical profiles
- Cluster assignment prevents redundant LLM API calls
- `needs_regeneration` flag tracks when underlying data changes

## 7. Operational Safety First

All scripts provide controls to limit blast radius.
- `--dry-run` on every script
- `--limit N` for bounded execution
- `--dev` for development database
- Per-step timeout (default 2 hours)
- Failure isolation: failed step blocks only its dependents
