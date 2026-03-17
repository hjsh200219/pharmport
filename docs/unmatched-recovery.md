# PharmPort 미매칭 11,641건 복구 전략

> 생성일: 2026-03-16
> **최종 수정: 2026-03-17 (Iteration 5 — Opus 최종 리뷰 반영: Cal/Val fallback, Prefix 양방향 guardrail, v2↔v3 import 정합성, threshold 근거 보완)**
> 상태: 계획 수립 완료 — 사용자 확인 대기

---

## RALPLAN-DR Summary

> **RALPLAN-DR**: Requirements → Analysis → Layered Plan → Decision Record. 본 문서의 구조화된 의사결정 프레임워크.

### Principles (핵심 원칙)

1. **Zero Error 불변**: 어떤 단계에서든 Error Rate 0%를 유지한다. 매칭하지 않는 것은 허용하되, 잘못된 매칭은 절대 불가.
2. **GT 우선 캘리브레이션 및 Data Leakage 방지**: 성분/제조사 등 핵심 channel threshold는 기존 텍스트 GT(21,706건)를 **Calibration Set(70%)과 Validation Set(30%)으로 분리**하여 설정한다. Calibration Set으로 threshold를 찾고, Validation Set에서 0% Error가 유지되는지 교차 검증하여 과적합(Overfitting)을 방지한다. 약품명/sim gap 같은 보조 guardrail은 휴리스틱을 둘 수 있으나, 무근거 ad-hoc 상수는 금지하며 GT-covered subset 또는 baseline matched set으로 근거를 문서화한다.
3. **단계적 확장 (Easy First)**: 확실하고 단순한 건부터 회수하고, 점차 리스크와 구현 복잡도가 높은 영역으로 확장한다.
4. **경로 다변화**: ProductInfos 경유 경로에만 의존하지 않고, 직접 경로(pharmport_medicine → 터울주성분)를 병행 개척한다.
5. **역추적 가능 설계**: 모든 매칭에 `match_method` tag를 부여하여, 문제 발생 시 특정 방법의 결과만 선택적으로 rollback할 수 있어야 한다.

### Decision Drivers (의사결정 핵심 요인)

1. **수확량 대비 안전성**: 11,641건 중 최대한 많이 복구하되, 한 건의 오류도 불허. 모든 전략의 예상 precision이 100%여야 채택.
2. **구조적 한계 돌파 가능성**: 터울주성분 8,886건이 ProductInfos에 없는 구조적 병목. 이것을 우회하지 않으면 회수 가능 상한이 제한됨.
3. **구현 복잡도 vs ROI**: 복잡한 전략(외부 API, NLP 파이프라인 등)은 수확량이 충분히 클 때만 정당화됨.

---

## Viable Options

### Option A: 단계적 회수 (Layered Recovery) — **채택**

**핵심**: 현재 파이프라인 구조를 유지하면서 각 실패 단계별로 타겟화된 완화 전략을 적용한다.

> **Iteration 2 변경**: Phase 순서를 Easy First 원칙에 따라 재배치.
> Prefix Match(텍스트 기반, LOW-MED)를 Top-K Reciprocal(임베딩 기반, MEDIUM)보다 먼저 수행.

#### Phase 1. 제조사 channel 26건 회수

| 항목 | 내용 |
|------|------|
| **대상** | Reciprocal Match + 성분 통과했으나 제조사 sim < 0.1677인 26건 |
| **방법** | 약품명 sim ≥ `name_mfr_exempt_thresh` **AND** 성분 sim ≥ `ingr_mfr_exempt_thresh` 이면 제조사 channel 면제 |
| **threshold 결정** | GT Calibration Set(70%) 중 제조사 미달 건(`mfr_sim < mfr_thresh`)의 `name_sim`, `ingr_sim` 분포를 jointly profile하여 exemption threshold를 정한다. **소표본 fallback**: 해당 subset이 n < 30이면 Cal/Val 분할 대신 GT 전체를 사용하고, Phase 1 전수검토(26건)로 검증을 대체한다. |
| **근거** | 약품명과 성분이 모두 높은 유사도로 일치하면 제조사 불일치는 OEM/수입처 차이일 가능성 높음 |
| **예상 수확** | ~20-26건 |
| **위험도** | LOW — 이미 2개 strong signal 통과 |
| **검증** | GT Validation Set(30%) 대조로 100% 정확도 확인 |

#### Phase 2. 적응형 성분 threshold (883건)

| 항목 | 내용 |
|------|------|
| **대상** | Reciprocal Match 통과했으나 성분 sim < 0.4820인 883건 |
| **방법** | **Tiered Threshold**: 약품명 sim 구간별 성분 threshold 차등 적용 |
| **threshold 설정** | `name_sim` 구간 경계(`name_high`, `name_mid`)는 GT Calibration Set(70%)의 name_sim 분포 상위 구간에서 캘리브레이션한다. 성분 threshold는 **해당 name_sim 구간 내 GT 건의 ingr_sim 분포**에서 산출한다: `name_sim ≥ name_high` 구간 → `ingr_thresh = 해당 구간 ingr_sim p5`, `name_sim ≥ name_mid` 구간 → `ingr_thresh = 해당 구간 ingr_sim p3`, 그 외: 기존 전체 p1 유지 |
| **근거** | 약품명이 거의 동일하면 같은 약일 확률이 높음. 성분 sim이 낮은 이유는 (1) 복합제 성분 순서, (2) 함량 표기 차이, (3) 성분 임베딩 노이즈 |
| **예상 수확** | ~200-400건 |
| **위험도** | LOW-MEDIUM — 약품명 near-identical이 강력한 보정 signal |
| **검증** | GT Validation Set(30%) 대조 + 수동 샘플 **300건** 검토 |

#### Phase 3. Prefix Text Match (4,001건) ← *기존 Phase 4에서 승격*

| 항목 | 내용 |
|------|------|
| **대상** | 미매칭 11,641건 중 ProductInfos.Name과 prefix 관계인 4,001건 |
| **방법** | Prefix 일치를 "후보 고정"으로 사용. 짧은 쪽이 긴 쪽의 prefix일 때, **긴 쪽의 suffix(차이 부분)에 숫자+단위(mg, g, ml, % 등)가 포함된 경우 매칭을 보류(수동 검토 이관)**하여 함량/규격 차이로 인한 오매칭을 방지한다. 이 검사는 `medicine_name`이 prefix인 경우와 `PI.Name`이 prefix인 경우 **양방향 모두** 적용한다. 해당 PI 후보에 대해 성분·제조사 multi-channel 검증. Prefix 중 가장 긴 공통 부분을 가진 PI를 우선 선택 |
| **순서 변경 근거** | (1) 텍스트 기반이라 구현이 단순하고 디버깅이 쉬움 (2) 위험도 LOW-MED로 Top-K의 MEDIUM보다 낮음 (3) Prefix 매칭 결과를 확보한 후 Top-K 대상 풀이 줄어 연산량 감소 |
| **근거** | "타이레놀정500밀리그램" ↔ "타이레놀정500밀리그램(아세트아미노펜)" 같은 경우 prefix 관계이면서 동일 약품. Embedding reciprocal이 실패하는 이유는 뒤에 붙는 성분명 때문 |
| **예상 수확** | ~1,000-2,500건 |
| **위험도** | LOW-MEDIUM — 텍스트 prefix는 강한 signal, multi-channel이 이중 검증 |
| **검증** | GT Validation Set(30%) 대조 + prefix 길이 분포 분석 + 수동 샘플 **300건** |

#### Phase 4. Top-K Soft Reciprocal (10,732건 대상) ← *기존 Phase 3에서 이동*

| 항목 | 내용 |
|------|------|
| **대상** | Reciprocal Match 실패 10,732건 중 Phase 3(Prefix)에서 미해결인 잔여 건 (forward Top-1 sim ≥ `topk_name_floor`). Phase 1-2는 reciprocal 성공 건이므로 10,732건과 겹치지 않음. |
| **방법** | Forward Top-3 후보를 생성하고, 각 후보에 대해 reverse Top-3 내에 해당 medicine이 있으면 "Soft Reciprocal"로 인정. 이후 `name_sim ≥ topk_name_floor` + 성분·제조사 모두 기존 threshold 이상 통과 필수. `topk_name_floor`는 GT Calibration Set에서 reciprocal match가 성공한 건의 name_sim 분포 하위 5%(p5)로 설정한다. |
| **ambiguity check (양방향)** | (a) 같은 medicine에 2+ PI가 Soft Reciprocal → 성분 sim 격차가 `ambiguity_gap_thresh` 이상이면 1위 승자 독식, 아니면 스킵, (b) **같은 PI에 2+ medicine이 Soft Reciprocal → 동일 조건 적용**. `ambiguity_gap_thresh`는 GT Calibration Set에서 동일 medicine에 복수 PI가 매칭되는 케이스의 성분 sim 격차 분포를 분석하여 결정한다 (초기 구현값 0.05, 캘리브레이션으로 대체). |
| **근거** | 약품명이 유사한 다수의 제품이 존재할 때 Top-1이 아닌 Top-2/3이 정답인 경우가 있음 |
| **예상 수확** | ~500-1,500건 |
| **위험도** | MEDIUM — Top-K로 candidate 풀이 넓어지므로 multi-channel 필터의 역할이 중요 |
| **검증** | GT Validation Set(30%) 대조 + 무작위 **300건** 수동 검토 |

#### Phase 5. 직접 경로 (PharmPort → 터울주성분, PI 우회)

| 항목 | 내용 |
|------|------|
| **대상** | Phase 1-4 이후 남은 미매칭 건 (예상 ~6,000-9,000건) |
| **방법** | `sorted_ingredient_embedding` ↔ `sorted_성분명_embedding` 직접 cosine similarity. 매우 높은 threshold (≥ p1 from direct GT calibration) + 추가 검증 조건: (a) Top-1이 유일하게 높은 sim (2위와 gap ≥ `direct_gap_thresh`), (b) Reciprocal check (터울주성분 → pharmport_medicine 역방향 Top-1 일치) — 단, 역방향 Top-1이 일치하더라도 Top-2와의 gap이 `direct_gap_thresh` 미만이면 스킵. **성분 reciprocal 한계**: 약품명 reciprocal과 달리 동일 성분의 복수 약품(다른 함량/제형)이 존재하므로 성분 reciprocal만으로는 1:1 보장이 불충분하다. gap 조건이 이를 보완하는 핵심 guardrail이다. **주의**: 심평원성분코드가 함량/제형을 구분하는 체계라면 이 방식은 N:1 오매칭을 유발하므로 비즈니스 합의 선행 필수. |
| **스키마 게이트** | Phase 4 완료 후, Phase 5 시작 **전에** 저장 구조 확정 필수 (아래 "Phase 5 저장 구조" 섹션 참조) |
| **근거** | ProductInfos에 없는 8,886 MIC를 커버할 수 있는 유일한 경로. 성분 정보가 핵심이므로 직접 비교가 논리적 |
| **예상 수확** | ~1,000-3,000건 |
| **위험도** | MEDIUM-HIGH — 약품명 anchor 없이 성분만으로 판단. 같은 성분의 다른 제형/함량 약품이 오매칭될 위험 |
| **검증** | GT Validation Set(30%) 전수 검증 + 수동 검토 **500건** + 역방향 cross-check |

**Option A 종합:**

| Phase | 예상 수확 | 누적 | 위험도 | 구현 복잡도 |
|-------|----------|------|--------|-----------|
| 1. 제조사 면제 | 20-26 | 20-26 | LOW | 낮음 |
| 2. 적응형 threshold | 200-400 | 220-426 | LOW-MED | 낮음 |
| 3. Prefix Match | 1,000-2,500 | 1,220-2,926 | LOW-MED | 중간 |
| 4. Top-K Reciprocal | 500-1,500 | 1,720-4,426 | MEDIUM | 중간 |
| 5. 직접 경로 | 1,000-3,000 | 2,720-7,426 | MED-HIGH | 높음 |
| **합계** | **2,720-7,426** | | | |

- **Pros**: 단계별 리스크 관리, 각 단계 독립적으로 rollback 가능, 기존 시스템과 호환, Easy First 순서로 빠른 성과 확보
- **Cons**: Phase 5의 직접 경로는 precision 유지가 도전적, 전체 구현에 시간 소요

---

### Option B: 직접 경로 우선 + 보완 (Direct-First)

**핵심**: ProductInfos 경유를 최소화하고, 성분 임베딩 직접 비교를 1순위로 두어 구조적 한계를 먼저 돌파한다.

#### Phase 1. 직접 경로 캘리브레이션

- 기존 GT(21,706건)를 이용해 직접 경로의 similarity 분포 파악
- 각 GT 쌍에 대해 `pharmport_medicine.sorted_ingredient_embedding` ↔ `터울주성분.sorted_성분명_embedding[해당 MIC]` 직접 계산
- 분포에서 p1을 direct path threshold로 설정
- 추가로 "sim gap" (Top-1과 Top-2 차이) 분포도 파악

#### Phase 2. 직접 경로 매칭 (전체 미매칭 대상)

- 40,837건 전체(매칭된 건 포함)에 대해 직접 경로 실행
- 이미 매칭된 29,196건에 대해 cross-validation (직접 경로 결과 ↔ 기존 결과 일치율)
- 불일치 건 분석으로 직접 경로의 신뢰도 파악
- 미매칭 11,641건에 적용: threshold 이상 + sim gap ≥ 0.05 + reciprocal (터울→pharmport)

#### Phase 3. 보완 (Option A의 Phase 1-4 중 남은 건)

- 직접 경로로 해결되지 않은 건에 대해 Option A의 Phase 1-4 보완 적용

**Option B 종합:**

| Phase | 예상 수확 | 누적 | 위험도 | 구현 복잡도 |
|-------|----------|------|--------|-----------|
| 1. 캘리브레이션 | 0 (분석) | 0 | NONE | 중간 |
| 2. 직접 경로 | 2,000-5,000 | 2,000-5,000 | MEDIUM | 높음 |
| 3. 보완 | 500-2,000 | 2,500-7,000 | LOW-MED | 중간 |
| **합계** | **2,500-7,000** | | | |

- **Pros**: 구조적 한계를 정면 돌파, ProductInfos 의존성 제거, 코드가 단순해질 수 있음
- **Cons**: 직접 경로 자체의 precision이 검증 전까지 불확실, 같은 성분 다른 제형 문제

---

### 기각된 대안과 사유

| 대안 | 기각 사유 |
|------|----------|
| **Threshold 전면 완화** | p1 → p5로 일괄 완화하면 error rate 상승 불가피. methodology.md에서 이미 기각됨 |
| **약품명 정규화 (규격 제거)** | "_(500mg)" 제거 시 다른 용량의 약품이 merge됨. 약품 식별 정보 손실 |
| **외부 API (식약처, e-약은방)** | 구현 복잡도 높음 + API rate limit + 데이터 포맷 불일치. 현재 데이터만으로 해결 가능한 부분을 먼저 소진한 후 검토 |
| **LLM 기반 매칭 (GPT-4 판단)** | 40,000건 규모에서 비용 과다 + 환각(hallucination) 위험으로 0% error 보장 불가 |
| **IngredientCode 활용** | MasterIngredientCode와 달리 1:N 관계가 많아 ambiguity 증가. 추가 가치 제한적 |

---

## ADR (Architecture Decision Record)

### Decision

**Option A (단계적 회수)를 채택한다.** Phase 순서는 Easy First에 따라 Prefix → Top-K. Phase 5의 직접 경로는 Option B의 캘리브레이션 방식을 차용하되, GT-covered subset 검증을 우선하고 baseline matched set 비교는 보조 진단 지표로 사용한다.

### Drivers

1. **Error Rate 0% 유지**가 최우선이므로, 각 단계별로 GT 검증 후 다음 단계로 진행하는 접근이 안전
2. Phase 1-3(~1,200-2,900건)은 기존 인프라를 활용하여 빠르게 구현 가능하고, 위험도가 LOW-MED 이하
3. Phase 4(Top-K)는 Phase 3(Prefix)로 대상 풀이 줄어든 후 수행하여 연산량과 ambiguity 감소
4. Phase 5(직접 경로)는 GT-covered subset에서 0 wrong를 확인한 뒤 적용하고, baseline matched set 비교는 drift 감지용 보조 지표로 활용

### Alternatives Considered

- **Option B (직접 경로 우선)**: 구조적 한계 돌파에 유리하나, 직접 경로의 precision이 사전 검증 없이는 불확실. Phase 5로 미루되, 캘리브레이션 방식은 차용.
- **Threshold 전면 완화**: error rate 상승 → 기각
- **외부 API**: 현재 데이터로 해결 가능한 범위를 먼저 소진한 후 검토

### Consequences

- 예상 추가 매칭: **2,700-7,400건** (11,641건의 23-64%)
- 최종 매칭율: **78-90%** (현재 71.5%)
- 구현 기간: Phase 0-2 (1-2일), Phase 3-4 (2-3일), Phase 5 (3-5일)
- 모든 단계에 match_method tag 부여 → 문제 시 선택적 rollback

### Follow-ups

- Phase 5 완료 후 남은 미매칭 건(~4,000-9,000건) 프로파일링
- 외부 API 활용 여부 재검토
- 수동 검토 파이프라인 설계 (borderline 건)

---

## Architect Synthesis 판단

| 제안 | 판단 | 근거 |
|------|------|------|
| **계층적 검증 (보조 검증 집합)** | **채택** | Phase 3-4에서 GT 검증 불가능한 건(GT 없는 매칭)에 대해, Phase 1-2의 확정 결과를 보조 검증 집합으로 활용하여 추가 cross-check. 단, 공식 GT로 승격하지 않고 보조 지표로만 사용. |
| **Stratified Sampling** | **채택** | 수동 검토 시 단순 무작위 대신 `name_sim` 구간별 층화 추출. 저유사도 구간에서 error가 집중될 가능성이 높으므로 해당 구간 over-sampling. 각 Phase의 수동 검토에 적용. |
| **Gated Release (staging 테이블)** | **후속 검토** | Phase 1-4는 기존 `product_code`/`ingredient_code` 컬럼에 직접 저장 + `match_method`로 추적하여 rollback 가능. Phase 5는 별도 저장 구조가 필요하므로 Phase 5 스키마 결정 시 staging 테이블 여부를 함께 확정. |

---

## Phase 5 저장 구조

### 문제

Phase 5(직접 경로)는 ProductInfos를 경유하지 않으므로 `product_code`가 없다. `product_code = NULL`로 저장하면 기존 스키마 계약("product_code와 ingredient_code는 항상 쌍으로 존재")을 위반한다.

### 결정 게이트

**Phase 4 완료 후, Phase 5 구현 시작 전에 아래 중 하나를 확정한다:**

| 옵션 | 설명 | 장점 | 단점 |
|------|------|------|------|
| **A. 별도 컬럼** | `direct_ingredient_code` 컬럼 추가 | 기존 스키마 불변, 쿼리 시 두 경로 명확 구분 | 조회 로직에서 COALESCE 필요 |
| **B. 별도 테이블** | `pharmport_direct_match(medicine_id, ingredient_code, match_method, confidence, ...)` | 완전 분리, 기존 시스템 영향 0 | JOIN 추가, 통합 뷰 필요 |
| **C. NULL 허용 (현행)** | `product_code = NULL, ingredient_code = '...'` | 변경 최소 | 스키마 계약 위반, 다운스트림 오류 가능 |

> 현시점 **권장**: 옵션 A (별도 컬럼). Phase 1-4 결과를 확인한 후 Phase 5 실제 수확량 규모에 따라 최종 확정.

---

## 파일 구조 및 v2 관계

### 파일 트리

```
pharmport/
├── common.py                   # DB 연결 유틸 (공유)
├── embedding_service.py        # Azure OpenAI 임베딩 API + 성분 정렬
├── sort_and_embed.py           # 정렬 + 임베딩 + DB 저장
├── match_ingredient.py         # Method 1 (v1, 레거시)
├── match_ingredient_v2.py      # Method 2 (현재 적용, 3중 필터)
├── match_ingredient_v3.py      # [신규] Method 3 (미매칭 복구)
├── analyze_unmatched.py        # [신규] 미매칭 11,641건 프로파일링
├── analysis.py                 # 기존 분석 스크립트
└── methodology.md              # 매칭 방법론 문서
```

### v2 ↔ v3 관계: **함수 import + 독립 로직**

`match_ingredient_v3.py`는 v2에서 **공용 유틸리티 함수만 import**하고, 매칭 로직 자체는 독립 구현한다.

| v2에서 import하는 함수 | 용도 |
|----------------------|------|
| `parse_vector` | 벡터 문자열 파싱 |
| `normalize_rows` | 행렬 정규화 |
| `cosine_sim` | 코사인 유사도 계산 |
| `load_medicine` | pharmport_medicine 로드 |
| `load_productinfos` | ProductInfos 로드 |
| `load_ingredient_map` | 터울주성분 임베딩 로드 |
| `load_manufacturer_map` | Manufacturers 임베딩 로드 |
| `build_text_gt` | 텍스트 GT 구축 |

> **참고**: v2의 `calibrate_channels`는 GT 전체를 사용하여 threshold를 반환하므로, Cal/Val 분할이 필요한 v3에서는 직접 import하지 않는다. v3에서 `calibrate_channels_with_split()`로 독립 구현한다 (아래 참조).

v3에서 **독립 구현하는 것들:**

| 함수/모듈 | 역할 |
|----------|------|
| `calibrate_channels_with_split()` | Cal/Val 분할 후 성분·제조사 threshold 캘리브레이션 (v2 `calibrate_channels` 대체) |
| `calibrate_mfr_exempt_thresh()` | Phase 1: Cal Set 중 mfr 미달 건의 name_sim, ingr_sim 분포 → exemption threshold (소표본 시 GT 전체 fallback) |
| `calibrate_ambiguity_gap()` | Phase 4: Cal Set에서 복수 PI 매칭 케이스의 성분 sim 격차 분포 → `ambiguity_gap_thresh` |
| `find_topk_reciprocal()` | Phase 4: Top-K Soft Reciprocal + 양방향 ambiguity check |
| `find_prefix_matches()` | Phase 3: Prefix Text Match 후보 생성 (양방향 suffix guardrail 포함) |
| `direct_path_calibrate()` | Phase 5a: 직접 경로 GT 캘리브레이션 |
| `direct_path_match()` | Phase 5c: 직접 경로 매칭 |
| Phase별 `apply_phase_N()` | 각 Phase 실행 + match_method 태깅 |

`analyze_unmatched.py`는 v2와 **독립적**이며, v2의 결과(DB에 저장된 product_code/ingredient_code)를 읽어서 미매칭 건의 통계를 출력한다.

---

## 수동 검토 프로토콜

### 통계적 근거

| 샘플 수 | 에러 0건 시 95% CI 상한 | 의미 |
|---------|----------------------|------|
| n=50 | ~5.8% | 최대 5.8% 에러율 가능 |
| n=100 | ~3.0% | 최대 3.0% 에러율 가능 |
| **n=300** | **~1.0%** | **GT가 닿지 않는 구간의 잔여 리스크 상한을 추정하는 보조 근거** |
| **n=500** | **~0.6%** | **더 낮은 리스크 상한 추정을 제공하지만, 0%를 증명하지는 않음** |

### Phase별 수동 검토 건수

| Phase | 수동 검토 | Sampling 방식 |
|-------|----------|--------------|
| 1. 제조사 면제 | **전수** (26건) | N/A (전수검토) |
| 2. 적응형 threshold | **300건** | Stratified: `name_sim` 구간별 (≥0.99, 0.97-0.99, <0.97) |
| 3. Prefix Match | **300건** | Stratified: prefix 길이 + `ingr_sim` 구간별 |
| 4. Top-K Reciprocal | **300건** | Stratified: `name_sim` 구간별 (0.90-0.95, 0.95-0.99, ≥0.99) |
| 5. 직접 경로 | **500건** | Stratified: `direct_sim` 구간별 + `sim_gap` 구간별 |

---

## Rollback 절차

### 파이프라인 롤백 연쇄 작용 (Cascading Rollback)

파이프라인이 앞선 Phase의 결과를 제외하고 다음 Phase를 진행하는 구조이므로, 특정 Phase를 롤백할 경우 데이터 정합성을 위해 **해당 Phase 이후의 모든 Phase도 함께 롤백하고 재실행**해야 한다.
(예: Phase 3 롤백 시, Phase 4와 5도 반드시 함께 롤백)

### match_method 기반 선택적 Rollback

각 Phase의 매칭 결과에 `match_method` 값을 부여하여, 문제 발생 시 해당 Phase만 정밀하게 되돌린다.

| Phase | match_method 값 |
|-------|----------------|
| 기존 v2 | `'v2'` (기존 값, 변경 없음) |
| Phase 1 | `'v3_mfr_exempt'` |
| Phase 2 | `'v3_adaptive_ingr'` |
| Phase 3 | `'v3_prefix'` |
| Phase 4 | `'v3_topk_reciprocal'` |
| Phase 5 | `'v3_direct'` |

### Rollback SQL 템플릿

```sql
-- 특정 Phase rollback (예: Phase 4)
UPDATE pharmport_medicine
SET product_code = NULL,
    ingredient_code = NULL,
    match_method = NULL
WHERE match_method = 'v3_topk_reciprocal';

-- 전체 v3 rollback (모든 Phase)
UPDATE pharmport_medicine
SET product_code = NULL,
    ingredient_code = NULL,
    match_method = NULL
WHERE match_method LIKE 'v3_%';

-- Phase 5 rollback (저장 구조 옵션 A 채택 시 — 별도 컬럼 방식)
UPDATE pharmport_medicine
SET direct_ingredient_code = NULL,
    match_method = NULL
WHERE match_method = 'v3_direct';

-- Rollback 후 건수 확인
SELECT match_method, COUNT(*) as cnt
FROM pharmport_medicine
WHERE match_method IS NOT NULL
GROUP BY match_method
ORDER BY match_method;
```

---

## 상세 Task Flow

### Phase 0: 인프라 준비

**목표**: 단계별 매칭 결과를 추적 가능하게 저장하고, 미매칭 현황을 프로파일링

- [ ] `pharmport_medicine`에 `match_method` 컬럼 추가 (varchar, 매칭 방법 식별)
- [ ] 기존 29,196건에 `match_method = 'v2'` 설정
- [ ] `analyze_unmatched.py` 작성: 11,641건의 상세 프로파일 (name sim 분포, ingredient sim 분포, prefix 매칭 현황, 제조사 미달 건의 ingr_sim 분포)
- [ ] dry-run 모드 기본 지원
- [ ] `match_ingredient_v3.py` 스켈레톤 작성: v2에서 공용 함수 import 확인 (유틸리티 + 로더만. `calibrate_channels`는 Cal/Val 분할이 필요하므로 v3에서 독립 구현)

**수락 기준**: 미매칭 건의 상세 통계 출력, match_method 컬럼 존재, 기존 건에 'v2' 태그 확인

### Phase 1: 제조사 channel 면제 (26건)

**목표**: Reciprocal + 성분 통과, 제조사만 미달인 26건 회수

- [ ] GT 데이터(21,706건)를 Calibration Set(70%)과 Validation Set(30%)으로 분할
- [ ] `calibrate_mfr_exempt_thresh()` 구현: Calibration Set에서 `mfr_sim < mfr_thresh`인 건의 `name_sim`, `ingr_sim` 분포를 jointly profile하여 `name_mfr_exempt_thresh`, `ingr_mfr_exempt_thresh` 산출. **소표본 fallback**: 해당 subset n < 30이면 GT 전체 사용 + Phase 1 전수검토로 검증 대체
- [ ] Phase 1 로직: `name_sim ≥ name_mfr_exempt_thresh AND ingr_sim ≥ ingr_mfr_exempt_thresh` → 제조사 면제
- [ ] Validation Set 검증 결과 100% 정확도 확인
- [ ] match_method = `'v3_mfr_exempt'`

**수락 기준**: 26건 중 GT 대조 가능한 전수에서 0% error, 회수 건수 ≥ 20

### Phase 2: 적응형 성분 threshold (883건)

**목표**: 약품명이 거의 동일한 경우 성분 threshold 완화

- [ ] Tiered threshold 로직: Calibration Set의 name_sim 분포에서 구간 경계(`name_high`, `name_mid`)를 먼저 캘리브레이션한 뒤, **해당 구간 내 GT 건의 ingr_sim 분포**에서 성분 threshold를 산출
  - `name_sim ≥ name_high`: `ingr_thresh = 해당 구간 ingr_sim p5`
  - `name_sim ≥ name_mid`: `ingr_thresh = 해당 구간 ingr_sim p3`
  - 그 외: 기존 전체 p1 유지 (변경 없음)
- [ ] Validation Set 검증 + Stratified 수동 샘플 **300건** 검토
- [ ] match_method = `'v3_adaptive_ingr'`

**수락 기준**: GT 검증 0% error, 회수 건수 ≥ 200

### Phase 3: Prefix Text Match (4,001건)

**목표**: 약품명 prefix 관계를 후보 생성 기준으로 활용

- [ ] `medicine_name`이 `ProductInfos.Name`의 prefix이거나 그 반대인 쌍 추출
- [ ] **함량/규격 Guardrail (양방향)**: 짧은 쪽이 긴 쪽의 prefix일 때, 긴 쪽의 suffix 부분에 숫자+단위(mg, g, ml, % 등) 정규식 매칭 시 후보에서 제외 (수동 검토 이관). `medicine_name`이 prefix인 경우와 `PI.Name`이 prefix인 경우 모두 적용
- [ ] 각 prefix 쌍에 대해 multi-channel 검증 (성분 + 제조사, 기존 threshold)
- [ ] 다수의 prefix 후보가 있으면 가장 긴 공통 prefix를 가진 후보 선택, 동률 시 성분 sim 최대 후보
- [ ] Phase 1-2에서 이미 매칭된 건은 제외
- [ ] Validation Set 검증 + Stratified 수동 샘플 **300건**
- [ ] match_method = `'v3_prefix'`

**수락 기준**: Validation Set 검증 0% error, 회수 건수 ≥ 1,000

### Phase 4: Top-K Soft Reciprocal (10,732건 대상)

**목표**: Reciprocal 조건을 완화하여 Top-K 범위에서 매칭 시도

- [ ] Forward Top-3, Reverse Top-3 계산
- [ ] Soft Reciprocal: `forward Top-3에 PI_j 존재 AND reverse Top-3에 med_i 존재`
- [ ] `topk_name_floor` 설정: GT Calibration Set에서 reciprocal match 성공 건의 name_sim 분포 하위 5%(p5)
- [ ] 추가 조건: `name_sim ≥ topk_name_floor AND ingr_sim ≥ ingr_thresh AND mfr_sim ≥ mfr_thresh`
- [ ] `ambiguity_gap_thresh` 캘리브레이션: Cal Set에서 동일 medicine에 복수 PI가 매칭되는 케이스의 성분 sim 격차 분포 분석 (초기 구현값 0.05)
- [ ] **양방향 ambiguity check**:
  - (a) 같은 medicine에 2+ PI가 Soft Reciprocal → 성분 sim 격차 `ambiguity_gap_thresh` 이상 시 1위 선택, 아니면 스킵
  - (b) 같은 PI에 2+ medicine이 Soft Reciprocal → 동일 조건 적용
- [ ] Phase 1-3에서 이미 매칭된 건은 제외
- [ ] Validation Set 검증 + Stratified 무작위 **300건** 수동 검토
- [ ] match_method = `'v3_topk_reciprocal'`
- [ ] 보조 검증 집합 cross-check: Phase 1-3 확정 결과를 공식 GT와 분리된 보조 검증 집합으로 활용

**수락 기준**: Validation Set 검증 0% error, 회수 건수 ≥ 500

### Phase 5: 직접 경로 (PharmPort → 터울주성분)

**목표**: ProductInfos를 우회하여 성분 임베딩 직접 비교

> **게이트**: Phase 4 완료 후, 저장 구조(별도 컬럼 vs 별도 테이블 vs NULL 허용) 확정 필요.

- [ ] **5a. 캘리브레이션**: Calibration Set 중 direct path를 계산할 수 있는 subset에서 direct cosine sim 분포 파악. 정답 MIC에 대한 분포 → p1을 `direct_thresh`로 설정
- [ ] **5b. Baseline 비교**: 기존 매칭 29,196건(`baseline matched set`) 전체에 대해 직접 경로를 실행하고, 기존 결과와의 일치율을 측정한다. 이 값은 drift 감지용 보조 지표이며, 단독 통과 기준으로 사용하지 않는다.
- [ ] **5c. 미매칭 적용**: Phase 1-4 후 남은 미매칭 건에 대해 직접 경로 실행
  - 조건: `direct_sim ≥ direct_thresh AND sim_gap ≥ direct_gap_thresh AND reciprocal(터울→pharmport 역방향 Top-1 일치 AND 역방향 Top-1↔Top-2 gap ≥ direct_gap_thresh)`
- [ ] **5d. 검증**: Validation Set 대조 + Stratified 수동 검토 **500건**
- [ ] match_method = `'v3_direct'`
- [ ] 저장: 확정된 스키마에 따라 저장 (별도 컬럼 `direct_ingredient_code` 권장)

**수락 기준**: Validation Set 검증 0% error. Baseline matched set 일치율은 보고하되, 95% 미만이면 원인 분석 및 threshold 재조정 후 재검증.

---

## 예상 수확량 요약

| Phase | 대상 | 예상 회수 (보수적) | 예상 회수 (낙관적) | 위험도 |
|-------|------|------------------|------------------|--------|
| 1. 제조사 면제 | 26건 | 20건 | 26건 | LOW |
| 2. 적응형 threshold | 883건 | 200건 | 400건 | LOW-MED |
| 3. Prefix Match | 4,001건 | 1,000건 | 2,500건 | LOW-MED |
| 4. Top-K Reciprocal | 10,732건* | 500건 | 1,500건 | MEDIUM |
| 5. 직접 경로 | 잔여 | 1,000건 | 3,000건 | MED-HIGH |
| **합계** | **11,641건** | **2,720건** | **7,426건** |  |
| **최종 매칭율** | | **78.2%** | **89.7%** |  |

*Phase 4 대상은 Phase 3에서 매칭된 건을 제외한 잔여분

---

## Success Criteria (성공 기준)

1. ✅ 모든 Phase에서 Validation Set 검증 Error Rate = 0% (Data Leakage 방지)
2. ✅ 추가 매칭 ≥ 2,500건 (최소 목표)
3. ✅ 모든 매칭에 match_method tag 부여
4. ✅ 각 Phase 독립 rollback 가능 (SQL 템플릿 제공)
5. ✅ 최종 매칭율 ≥ 78%
6. ✅ 수동 검토: n≥300 (Phase 2-4), n≥500 (Phase 5), 전수 (Phase 1)
7. ✅ GT-uncovered subset은 수동 검토 + 보조 검증 집합 + staged/dry-run 검토로만 승격

---

## Guardrails

### Must Have
- Error Rate 0% 유지 (모든 Phase)
- GT 검증을 거치지 않은 방법은 적용 금지
- 핵심 channel threshold는 GT percentile 기반, 보조 guardrail은 근거와 검증 절차 문서화
- match_method 추적 가능
- dry-run 모드 우선 실행
- 수동 검토: Stratified Sampling, n≥300 (Phase 5는 n≥500)

### Must NOT Have
- Threshold 일괄 완화
- GT 검증 없는 직접 경로 적용
- 기존 29,196건 매칭 결과 변경
- 수동 검토 없는 Phase 적용
- Phase 5 저장 구조 미확정 상태에서 구현 시작
- `product_code = NULL` 상태의 `ingredient_code` 저장 (스키마 게이트 통과 전)

---

## 구현 순서 및 일정 (권장)

```
Day 1-2: Phase 0 (인프라) + Phase 1 (26건) + Phase 2 (883건)
         → 빠른 성과 확보 (~220-426건)

Day 3-4: Phase 3 (Prefix Match) + Phase 4 (Top-K Reciprocal)
         → 주요 수확 (~1,500-4,000건)

Day 4 끝: Phase 5 저장 구조 확정 (스키마 게이트)

Day 5-7: Phase 5 (직접 경로)
         → 캘리브레이션 + cross-validation + 적용
         → 최종 수확 (~1,000-3,000건)

Day 8:   전체 결과 리포트 + 잔여 미매칭 프로파일링
```

---

## Changelog (Iteration 2)

> Architect/Critic 피드백 반영 내역

| # | 피드백 | 변경 내용 | 영향 범위 |
|---|--------|----------|----------|
| **1** | Phase 순서: Prefix → Top-K (Easy First) | Phase 3 ↔ Phase 4 교체. Prefix Match(LOW-MED)를 Top-K(MEDIUM) 이전으로. 순서 변경 근거 3가지 명시. | Phase 3, 4, 종합 테이블, Task Flow, 일정 |
| **2** | Phase 1 ingr_sim 0.7 → GT percentile 기반 | ad-hoc `0.7` 제거 후, GT-covered subset의 분포를 활용하는 캘리브레이션 방향으로 정리. `calibrate_channels()` 패턴과 일관성 확보. | Phase 1 조건, Task Flow |
| **3** | 수동 샘플 크기 상향 (n≥300/500) | Phase 2: 50→300, Phase 3: 100→300, Phase 4: 100→300, Phase 5: 200→500. 샘플 수 상향으로 GT-uncovered 구간의 잔여 리스크 상한을 더 낮게 추정할 수 있도록 변경. | 모든 Phase 검증 절차, 수동 검토 프로토콜 신규 섹션 |
| **4** | Phase 5 저장 구조 결정 게이트 | 별도 컬럼/별도 테이블/NULL 허용 3개 옵션 비교표 추가. "Phase 4 완료 후, Phase 5 시작 전 확정" 게이트 명시. Guardrails에 추가. | Phase 5, 저장 구조 신규 섹션, Guardrails |
| **5** | 파일 구조 및 v2 관계 정의 | 파일 트리, v2→v3 import 함수 목록, v3 독립 구현 함수 목록, `analyze_unmatched.py` 역할 명시. | 파일 구조 신규 섹션 |
| **6** | Phase 4 양방향 ambiguity check | medicine→PI 뿐 아니라 **PI→medicine도 1:1 확인**: "같은 PI에 2+ medicine이 Soft Reciprocal이면 스킵" 추가. | Phase 4 조건, Task Flow |
| **7** | Architect Synthesis 3건 판단 | 계층적 검증(보조 검증 집합): **채택**, Stratified Sampling: **채택**, Gated Release: **후속 검토**. 각각 근거 명시. | Architect Synthesis 신규 섹션, Phase 4 Task Flow |
| **8** | Rollback 절차 구체화 | match_method별 rollback SQL 템플릿 4종 (특정 Phase, 전체 v3, Phase 5 별도 컬럼, 확인 쿼리). | Rollback 절차 신규 섹션 |

## Changelog (Iteration 3)

> 리뷰 수정안 반영 내역

| # | 수정 사항 | 변경 내용 | 영향 범위 |
|---|----------|----------|----------|
| **1** | GT와 baseline 용어 분리 | `29,196건`을 GT처럼 쓰지 않고 `baseline matched set`으로 분리. Phase 5 수락 기준을 `GT-covered subset 0 wrong` 중심으로 재정의. | Phase 5, Success Criteria, ADR |
| **2** | threshold 원칙 정합화 | "모든 threshold" 표현을 "핵심 channel threshold + 보조 guardrail" 구조로 정리하고, name/sim gap 기준은 근거 문서화 대상으로 변경. | Principles, Guardrails, Phase 1/2/4/5 |
| **3** | 수동 검토 해석 수정 | n=300/500 표를 `Zero Error 증명`이 아닌 `잔여 리스크 상한 추정`으로 표현 수정. | 수동 검토 프로토콜 |
| **4** | 보조 검증 용어 정리 | `2차 GT` 표현을 `보조 검증 집합`으로 변경해 공식 GT와 혼동되지 않도록 수정. | Architect Synthesis, Phase 4 Task Flow |

## Changelog (Iteration 4)

> Gemini 심층 리뷰 반영 내역

| # | 수정 사항 | 변경 내용 | 영향 범위 |
|---|----------|----------|----------|
| **1** | Data Leakage 방지 | GT를 Calibration Set(70%)과 Validation Set(30%)으로 분리하여 threshold 설정과 검증을 엄격히 분리. | Principles, 각 Phase 검증 단계, Success Criteria |
| **2** | Prefix Match 함량 리스크 방어 | Suffix에 숫자+단위(mg 등)가 포함된 경우 매칭을 보류하는 Guardrail 정규식 조건 추가. | Phase 3 방법 및 Task Flow |
| **3** | 직접 경로 비즈니스 로직 경고 | Phase 5가 제형/함량 차이를 무시하고 N:1 매칭을 유발할 수 있음을 명시하고 비즈니스 합의 선행 조건 추가. | Phase 5 방법 |
| **4** | 롤백 연쇄 작용 원칙 | 특정 Phase 롤백 시 데이터 정합성을 위해 이후 Phase도 모두 롤백해야 한다는 파이프라인 운영 원칙 추가. | Rollback 절차 |
| **5** | Top-K 회수율 방어 | Phase 4의 양방향 ambiguity check 시 무조건 스킵 대신 성분 sim 격차(0.05) 기반 Tie-breaker 로직 추가. | Phase 4 방법 및 Task Flow |

## Changelog (Iteration 5)

> Opus 최종 리뷰 반영 내역

| # | 수정 사항 | 변경 내용 | 영향 범위 |
|---|----------|----------|----------|
| **1** | Phase 1 소표본 fallback | Cal Set에서 `mfr_sim < mfr_thresh` subset이 n < 30이면 Cal/Val 분할 대신 GT 전체 사용 + 전수검토로 대체하는 fallback 절차 추가. | Phase 1 threshold 결정, Task Flow |
| **2** | Prefix Guardrail 양방향 명시 | suffix 숫자+단위 검사를 `medicine_name`이 prefix인 경우와 `PI.Name`이 prefix인 경우 양방향 모두 적용하도록 정규화. | Phase 3 방법, Task Flow |
| **3** | `calibrate_channels` v3 독립 구현 | v2의 `calibrate_channels`는 GT 전체를 사용하므로 Cal/Val 분할과 모순. v2 import 목록에서 제거하고 v3에서 `calibrate_channels_with_split()`로 독립 구현. | 파일 구조, Phase 0 Task Flow |
| **4** | Phase 4 ambiguity 0.05 → 캘리브레이션 기반 | ad-hoc 상수 0.05를 `ambiguity_gap_thresh`로 변수화하고, Cal Set에서 복수 PI 매칭 케이스의 격차 분포로 결정하도록 변경. 초기값 0.05는 구현 시 캘리브레이션으로 대체. | Phase 4 방법, Task Flow, v3 독립 구현 목록 |
| **5** | Phase 2 percentile 모집단 명시 | p3, p5가 해당 name_sim 구간 **내** GT 건의 ingr_sim 분포에서 산출됨을 명시. | Phase 2 threshold 설정, Task Flow |
| **6** | `topk_name_floor` 출처 정의 | Cal Set에서 reciprocal match 성공 건의 name_sim 분포 하위 5%(p5)로 설정 방법 명시. | Phase 4 방법, Task Flow |
| **7** | Phase 5 성분 reciprocal 한계 명시 | 약품명 reciprocal과 달리 동일 성분 복수 약품 문제를 해결하지 못함을 명시하고, 역방향에도 gap 조건을 적용하는 추가 guardrail 추가. | Phase 5 방법, Task Flow |
| **8** | Phase 4 대상 풀 관계 명확화 | Phase 1-2는 reciprocal 성공 건이므로 10,732건과 겹치지 않고, Phase 3만 잔여분에 영향을 줌을 본문에서 명시. | Phase 4 대상 |
| **9** | RALPLAN-DR 약어 설명 추가 | 문서 구조 프레임워크의 약어 풀이 추가. | 문서 헤더 |
| **10** | Rollback SQL 조건부 레이블 | Phase 5 rollback SQL에 "저장 구조 옵션 A 채택 시" 조건 명시. | Rollback 절차 |
