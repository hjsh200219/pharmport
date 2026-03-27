# Database Schema Reference

Auto-generated from DBML files. See source files for full details:
- `pharmport_erd.dbml` -- Core PharmPort tables
- `productinfos_erd.dbml` -- ProductInfos extended schema
- `teoul_pharminfo_full_erd.dbml` -- Full database ERD

## Database: teoul_pharminfo (Source)

### Core Tables

| Table | Records | Purpose |
|-------|---------|---------|
| `pharmport_medicine` | 40,837 | Hub table: medicines with embeddings, product/ingredient code links |
| `pharmport_extra_text` | 22,964 | Extra info text records (field_type + content) |
| `pharmport_medicine_extra` | N:M | Junction: medicine <-> extra_text |
| `pharmport_usage_text` | -- | Usage info text records |
| `pharmport_medicine_usage` | N:M | Junction: medicine <-> usage_text |

### External Reference Tables

| Table | Records | Purpose |
|-------|---------|---------|
| `ProductInfos` | 48,027 | Product master (ProductCode PK, Name, manufacturer links) |
| `Manufacturers` | 659 | Manufacturer master |
| `터울주성분` | 20,235 | HIRA ingredient master (심평원성분코드 PK) |

### Enrichment Tables (edb_*)

| Table | Purpose |
|-------|---------|
| `edb_enrichment_status` | Per-code, per-step completion tracking (boolean + timestamp columns) |
| `edb_chembl_mapping` | ChEMBL compound ID mapping |
| `edb_mechanism` | Mechanism of action (action_type, target, organism) |
| `edb_admet` | ADMET properties |
| `edb_drug_disease` | Disease associations (OpenTargets, association_score >= 0.3) |
| `edb_safety` | Safety/labeling data (openFDA) |
| `edb_literature` | PubMed literature records |
| `edb_clinical_trial` | ClinicalTrials.gov trial data (nct_id) |
| `edb_faers` | FDA Adverse Event Reporting System data |
| `edb_indication_expansion` | Indication expansion data |

## Database: teoul_pharminfo_v2 (Generated Content)

### Mirrored + Generated Tables

| Table | Purpose |
|-------|---------|
| `터울복약프로파일` | Profile hash (SHA-256) + cluster_id assignment |
| `터울복약안내A4` | A4-format medication guides (LLM-generated, bilingual) |
| `터울복약안내A5` | A5-format medication guides (LLM-generated, bilingual) |
| `터울약효설명` | Pharmacological descriptions with LLM columns |

### Key Columns in pharmport_medicine

| Column | Type | Notes |
|--------|------|-------|
| `medicine_id` | serial PK | Auto-increment |
| `medicine_name` | varchar(200) | Unique, not null |
| `manufacturer` | varchar(200) | Unique constraint |
| `product_code` | varchar(100) | Logical FK to ProductInfos.ProductCode |
| `ingredient_code` | varchar(100) | Logical FK to 터울주성분.심평원성분코드 |
| `ingredient_embedding` | vector(3072) | Azure OpenAI text-embedding-3-large |
| `sorted_ingredient_embedding` | vector(3072) | Sorted ingredient embedding |
| `medicine_name_embedding` | vector | Medicine name embedding |
| `manufacturer_embedding` | vector | Manufacturer embedding |

### Enrichment Status Tracking Columns

| Column Pair | Step |
|-------------|------|
| `chembl_mapped` / `chembl_mapped_at` | ChEMBL compound mapping |
| `mechanism_fetched` / `mechanism_fetched_at` | Mechanism of action |
| `admet_fetched` / `admet_fetched_at` | ADMET properties |
| `disease_fetched` / `disease_fetched_at` | Disease associations |
| `safety_fetched` / `safety_fetched_at` | FDA safety data |
| `literature_fetched` / `literature_fetched_at` | PubMed literature |
| `trials_fetched` / `trials_fetched_at` | Clinical trials |
| `fda_fetched` / `fda_fetched_at` | FDA labeling |
| `last_error` | Last error message |
