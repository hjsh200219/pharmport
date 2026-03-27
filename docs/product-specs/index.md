# Product Specifications

## PharmPort Product Overview

PharmPort is a pharmaceutical data enrichment and medication guide generation system for Korean medicines.

### Target Users
- Pharmacists and healthcare providers using the Teoul platform
- Patients receiving medication guidance (A4/A5 format guides)

### Key Capabilities
1. **Ingredient Matching**: Maps PharmPort medicines to HIRA ingredient codes (0% error rate)
2. **Multi-Source Enrichment**: Aggregates data from ChEMBL, openFDA, OpenTargets, PubMed, ClinicalTrials.gov
3. **LLM Medication Guides**: Generates bilingual (EN/KO) medication guides using Claude + DeepL
4. **Profile Clustering**: Groups identical enrichment profiles to avoid redundant LLM generation

### Data Scale
| Entity | Count |
|--------|-------|
| PharmPort medicines | 40,837 |
| HIRA ingredient codes | 20,235 |
| Matched medicines | 29,196 (71.5%) |
| Product records | 48,027 |
| Manufacturers | 659 |

### Specs Index
_No individual product specs yet. Add specs here as features are specified._
