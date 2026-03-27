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

## Resolved Tech Debt

_None yet._
