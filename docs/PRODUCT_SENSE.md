# PharmPort Product Sense

## What PharmPort Does

PharmPort is a pharmaceutical data enrichment pipeline that serves the **Teoul platform** -- a Korean pharmacy information system. It transforms raw medicine data into clinically useful, bilingual medication guides.

## The Problem

Korean pharmacies need comprehensive medication information for 40,837+ medicines, but:
1. Raw data exists in fragmented sources (HIRA codes, product databases, international APIs)
2. No single source provides complete pharmacological context
3. Bilingual (English/Korean) medical content requires domain expertise
4. Manual creation of medication guides at this scale is infeasible

## How PharmPort Solves It

### Step 1: Ingredient Matching (0% error)
Maps PharmPort medicines to HIRA ingredient codes using embedding-based 3-filter matching. Prioritizes accuracy over coverage -- 71.5% matched, 0% error rate.

### Step 2: Multi-Source Enrichment
For each matched ingredient, aggregates data from 5 external APIs:
- **ChEMBL**: Compound IDs, mechanisms of action, ADMET properties
- **openFDA**: Drug labeling, adverse event reports (FAERS)
- **OpenTargets**: Disease associations with evidence scores
- **PubMed**: Relevant literature references
- **ClinicalTrials.gov**: Active and completed clinical trials

### Step 3: LLM Content Generation
Uses enriched data to generate bilingual medication guides:
- Claude Sonnet 4 generates English medical content
- DeepL translates to Korean
- Claude refines Korean medical terminology
- Output in A4/A5 print-ready formats

## Users

| User | What They Get |
|------|--------------|
| Pharmacists | Comprehensive medication guides for patient counseling |
| Patients | Clear bilingual medication information (A4/A5 printouts) |
| Teoul Platform | Enriched database with LLM-generated content |
| Pipeline Operators | CLI tools with dry-run, limits, and monitoring |

## Key Metrics

| Metric | Value | Why It Matters |
|--------|-------|----------------|
| Match error rate | 0% | Patient safety -- wrong ingredient info is dangerous |
| Match coverage | 71.5% (29,196/40,837) | More coverage = more medicines with guides |
| HIRA code coverage | 34.4% (6,956/20,235) | Breadth of ingredient enrichment |
| Profile clusters | Reduces LLM calls | Cost efficiency via deduplication |

## Product Constraints

1. **Safety-critical**: Only `validation_status = 'expert_reviewed'` data feeds safety sections
2. **Cost-sensitive**: LLM + translation API calls are expensive; profile clustering is essential
3. **Rate-limited**: 5 external APIs with varying rate limits (2-5 RPS)
4. **Bilingual**: All content must exist in both English and Korean
