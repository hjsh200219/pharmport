# Tech Debt Tracker

## Active Tech Debt

### TD-001: Deprecated match_ingredient.py Still in Repo
- **Severity**: Low
- **Description**: `match_ingredient.py` (Method 1: single-channel matching) is deprecated but still present. `match_ingredient_v2.py` (Method 2: 3-filter) is the active implementation.
- **Impact**: Confusion for new contributors; no runtime impact
- **Resolution**: Archive or remove after confirming no external references

### TD-002: SQL String Interpolation in enrich_base.py
- **Severity**: Medium
- **Description**: `batch_insert()` and `get_pending_codes()` use f-string interpolation for table/column names. While inputs are internal (not user-facing), this is a security antipattern.
- **Impact**: Low risk (internal-only inputs) but violates best practices
- **Resolution**: Use `psycopg2.sql` module for identifier quoting

### TD-003: No Automated Tests
- **Severity**: High
- **Description**: No test suite exists. Validation relies on GT calibration, manual verification, and `--dry-run` mode.
- **Impact**: Regression risk on matching thresholds, enrichment logic, and LLM prompt changes
- **Resolution**: Add unit tests for `enrich_base.py` utilities, integration tests for matching logic

### TD-004: Hardcoded Embedding Dimensions
- **Severity**: Low
- **Description**: 3072-dimension vectors are assumed throughout but not validated at runtime
- **Impact**: Silent failures if embedding model changes
- **Resolution**: Add dimension validation in `embedding_service.py`

### TD-005: No requirements.txt Version Pinning
- **Severity**: Medium
- **Description**: `requirements.txt` lists packages without version constraints (`psycopg2-binary`, `python-dotenv`, `openai`, `numpy`)
- **Impact**: Reproducibility risk across environments
- **Resolution**: Pin versions or add a lock file

### TD-006: Dead Module -- analysis.py
- **Severity**: Low
- **Description**: `analysis.py` is listed as L0 Infrastructure in ARCHITECTURE.md but is not imported by any other module in the project. All its exports (`fetch_table`, `fetch_medicine`, etc.) are unused.
- **Impact**: Dead code adds confusion; listed in docs as active module
- **Resolution**: Remove file or convert to a utility script with a `__main__` guard

### TD-007: Duplicated Ingredient Code Parser
- **Severity**: Low
- **Description**: `ParsedCode` dataclass and `parse_code()` function are duplicated across `enrich_new_ingredient.py` (L2), `enrich_fda.py` (L2), and partially in `build_profiles.py` (L3). The `enrich_fda.py` version even has a comment acknowledging the duplication.
- **Impact**: Bug risk from divergent copies; violates "shared utility > inline helper" principle
- **Resolution**: Move canonical `ParsedCode` + `parse_code()` to `enrich_base.py` (L0), import from there

### TD-008: Incomplete enrich_new_ingredient.py (TODO Stubs)
- **Severity**: Low
- **Description**: Three TODO comments in `enrich_new_ingredient.py` indicate Case B (compound) and Case C (fully new) enrichment paths are not implemented (lines 292, 300, 306).
- **Impact**: Only Case A (existing ingredient reuse) works; compound/new enrichment is stubbed
- **Resolution**: Implement or document as intentionally deferred

## Resolved Tech Debt

### TD-009: Incomplete requirements.txt (Fixed 2026-04-03)
- **Severity**: Medium
- **Description**: `requirements.txt` was missing `anthropic`, `requests`, and `httpx`
- **Resolution**: Added missing packages
