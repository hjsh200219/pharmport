# Open Questions

## unmatched-recovery - 2026-03-16

- [ ] Phase 5에서 `product_code = NULL`인 채로 `ingredient_code`만 부여하는 것이 허용되는가? — 직접 경로는 ProductInfos를 경유하지 않으므로 product_code를 채울 수 없음. 비즈니스 요건 확인 필요
- [ ] Phase 2의 tiered threshold 구간(0.99/0.97)은 GT 분석 후 재조정이 필요할 수 있음 — 캘리브레이션 결과에 따라 변동
- [ ] Phase 3의 Top-K에서 K=3이 최적인지, K=5까지 확장할 가치가 있는지 — ambiguity 증가 vs 수확량 trade-off
- [ ] Phase 4의 "prefix 관계" 정의: 최소 prefix 길이 제한이 필요한가? — 너무 짧은 prefix(예: 2글자)는 false match 유발 가능
- [ ] 외부 API(식약처 e-약은방, KIMS 등) 활용은 Phase 5 이후 남은 건에 대해 검토할 것인가? — 현재 데이터로 해결 가능한 범위를 먼저 소진 후 결정
- [ ] match_method 컬럼 추가 시 기존 29,196건의 method 값은 'v2_multichannel'로 설정하는가? — 기존 매칭과의 구분 필요

## enrichment-format-parity - 2026-03-19

- [ ] A4/A5 출력물의 최종 사용자는 누구인가? (약사, 의사, 환자, 내부 연구진) — 포맷 설계의 최상위 제약조건. 전문가 대상이면 ADMET/MoA 상세 포함, 환자 대상이면 안전성/용법 중심
- [ ] A4/A5 출력 포맷은 PDF인가, HTML인가, 또는 다른 형식인가? — 구현 기술 스택 결정 (ReportLab, WeasyPrint, Jinja2 등)
- [ ] NCBI API key 보유 여부 — PubMed rate limit이 key 없이 3 req/sec, key 있으면 10 req/sec. 20,235 성분 x 3 쿼리 = 60,705 호출 필요
- [ ] 터울주성분.약품분류ID와 약효설명ID에 대한 매핑 테이블이 별도로 존재하는가? — A4/A5 header의 약효 분류명 표시에 필요
- [x] ~~복합제 성분(콤마로 구분된 다수 성분)의 enrichment 전략: 개별 성분 각각을 enrichment할 것인가, 복합 조합 자체를 하나의 단위로 다룰 것인가?~~ — **Iteration 10에서 해결**: Compound Profile 전략 채택. 개별 성분은 단일제로 enrichment(96% 재활용) + 복합제는 compound profile layer로 LLM이 복합 맥락 통합 생성. `iteration-10-compound-profile.md` 참조
- [ ] enrichment 데이터의 갱신 주기: 1회성 수집인가, 주기적 업데이트가 필요한가? — enrichment_status 테이블의 fetched_at 기반 staleness 관리 여부
- [ ] Phase 2에서 기존 pharmport_extra_text/usage_text 데이터와 enrichment 데이터를 A4 출력물에서 어떻게 병합할 것인가? — 기존 "효능효과", "용법용량" 텍스트와 ChEMBL MoA/indication 데이터가 겹칠 수 있음

## enrichment-format-parity (Iteration 10 v2) - 2026-03-20

### v1에서 이관 (일부 수정)
- [ ] 복합제 구성 성분 파싱 로직: ProductInfos.IngredientCode 필드의 세미콜론 분해 규칙이 실제 데이터와 일치하는가? — v2에서 3단계 fallback의 Step 1으로 정의. 실제 DB 데이터 샘플 검증 필요 (예: 세미콜론 외 다른 구분자 사용 여부)
- [ ] 단일제 enrichment가 없는 구성 성분의 fallback 전략: Phase 1 enrichment를 추가 실행할 것인가, minimal profile로 처리할 것인가? — v2에서 "enrichment 미완료 시 완료 대기 또는 minimal 처리"로 기술했으나 구체적 기준 미확정
- [ ] compound profile hash에 "함량 차이"를 반영할 것인가? — v2에서 성분 코드만으로 해시(함량 무시)로 결정. 그러나 동일 4성분이라도 함량 비율이 다르면 부작용 우선순위가 달라질 수 있음. 현재 결정의 trade-off를 파일럿에서 검증 필요
- [ ] compound LLM 프롬프트에서 "복합 목적"(종합감기, 비타민 등) 정보를 어디서 추출하는가? — 터울약품분류 또는 ATC 코드로 유추 가능한지, 별도 매핑이 필요한지 확인 필요

### v2 신규 (Architect/Critic 피드백 반영)
- [ ] 5-tier 건수 추정치가 정확한가? — Tier 1(~1,200), Tier 2(~2,382), Tier 3(~3,100), Tier 4(~900), Tier 5(~209)는 추정값. Phase 1.5 Step B0에서 _split_ingredients() 실측 필요
- [ ] 구성 성분 식별 Step 1(ProductInfos.IngredientCode)의 커버리지: 29,882건 매칭 완료 중 복합제는 몇 건이 매칭되어 있는가? — Step 1의 실효성 판단에 필요
- [ ] Tier 4-5 카테고리 기반 요약에서 therapeutic class 그룹핑 로직: 터울약품분류.약품분류ID를 사용할 것인가, ATC 코드 1-2레벨을 사용할 것인가? — 그룹핑 품질에 직결
- [ ] needs_regeneration 배치 재생성 주기: daily cron인가, 수동 트리거인가? — 운영 부담과 데이터 freshness의 trade-off
- [ ] Tier 1(1성분 복합제) 중 코드가 '00'인 이유: 실제로 단일 성분인데 왜 복합제 코드가 부여되었는가? — 심평원 코드 체계의 특수 케이스 여부 확인. 처리 방식에 영향 가능
