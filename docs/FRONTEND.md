# PharmPort Frontend

## Status

PharmPort is a **backend-only data pipeline**. There is no frontend application in this repository.

## Output Consumers

The pipeline generates data consumed by external applications:

### Teoul Platform (External)
- Reads from `teoul_pharminfo_v2` database
- Displays medication guides (A4/A5 format) to pharmacists and patients
- Shows pharmacological descriptions (약효설명)

### Data Formats Generated

| Output | Format | Consumer |
|--------|--------|----------|
| Medication guides (A4) | Structured text (EN + KO) | Teoul web/mobile app |
| Medication guides (A5) | Structured text (EN + KO) | Teoul print system |
| Pharmacological descriptions | Bilingual text fields | Teoul product pages |
| Enrichment reports | Console/log output | Internal monitoring |

## Future Considerations

If a dashboard or admin UI is ever needed, it would likely:
- Display enrichment pipeline status and coverage metrics
- Provide ingredient match review interface
- Show LLM generation quality metrics
- Monitor API rate limit consumption
