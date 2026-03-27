# PharmPort Plans

## Active Plans

### Enrichment + Format Parity (RALPLAN-DR)
- **Document**: [enrichment-format-parity.md](enrichment-format-parity.md)
- **Status**: Planning (Iteration 11)
- **Scope**: Complete enrichment pipeline with format parity across all output types

### Unmatched Recovery Strategy
- **Document**: [unmatched-recovery.md](unmatched-recovery.md)
- **Status**: Planning
- **Scope**: Recover 11,641 unmatched records (28.5% of total) through advanced matching techniques

## Execution Plans

Active and completed execution plans are tracked in:
- [exec-plans/active/](exec-plans/active/) -- Currently in-progress plans
- [exec-plans/completed/](exec-plans/completed/) -- Finished plans

## Tech Debt

Tracked in [exec-plans/tech-debt-tracker.md](exec-plans/tech-debt-tracker.md).

Key items:
1. **TD-003** (High): No automated test suite
2. **TD-002** (Medium): SQL string interpolation in enrich_base.py
3. **TD-005** (Medium): No version pinning in requirements.txt

## Pipeline Milestones

| Milestone | Status | Description |
|-----------|--------|-------------|
| Phase 0: DDL | Done | Enrichment table creation |
| Phase 1-A: ChEMBL | Done | Compound mapping + MoA + ADMET |
| Phase 1-B: Multi-source | Done | FDA, OpenTargets, PubMed, ClinicalTrials |
| Phase 1-C: Report | Done | Coverage and quality reporting |
| Phase 1.5: Profiles | Done | SHA-256 hashing + clustering |
| Phase 2-A: V2 DB | Done | DDL + data migration |
| Phase 2-B: LLM Generation | Done | Medication guides + pharmacology descriptions |
| Unmatched Recovery | Planning | 11,641 records recovery |
