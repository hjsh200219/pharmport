# PharmPort Frontend

## 공통 금지 사항

- **이모지를 UI 아이콘으로 사용 금지.** OS/브라우저마다 렌더링이 다르고, 텍스트와 간격이 맞지 않음. SVG 아이콘 또는 Remixicon 사용.
- **미구현 페이지로 링크 금지.** 페이지가 없으면 disabled 처리 + "준비 중" 태그 표시.
- **E2E 테스트는 로그인/비로그인 두 상태 모두 검증.**
- **디자인 리뷰 시 모든 상태의 스크린샷 확인 필수.**


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
