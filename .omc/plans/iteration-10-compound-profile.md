# Iteration 10 — 복합제(Compound Drug) Profile 전략 (v2)

> **RALPLAN-DR Plan for updating `enrichment-format-parity.md` (Iteration 9 → 10)**
> 생성일: 2026-03-20
> v2 수정: 2026-03-20 (Architect/Critic ITERATE 피드백 반영)
> 상태: Architect/Critic 재검토 대기

---

## v1 → v2 변경 요약

| # | 피드백 (Must-Fix) | v2 변경 내용 |
|---|---|---|
| **MF-1** | 4,209 vs 7,791 스코프 불일치 | 전체 7,791건 복합제(YY='00')를 스코프로 확장. 성분 수 기반 5-tier 전략 정의 |
| **MF-2** | Compound hash가 constituent profile_hash에 의존 (cascade fragile) | 구성 성분 심평원성분코드 리스트를 직접 해시. `needs_regeneration` 플래그 추가 |
| **MF-3** | 구성 성분 식별 알고리즘 미정의 | 3단계 fallback 알고리즘 정의 + 구체적 예시 |
| **MF-4** | Tiered LLM 입력 전략 없음 | 3-tier (Small/Medium/Large) + 토큰 예산 정의 |

| # | 피드백 (Should-Fix) | v2 변경 내용 |
|---|---|---|
| **SF-1** | 96.2%를 "enrichment completion"으로 오해 가능 | "코드 존재율"로 명확화. 실제 enrichment 완료율은 Phase 1 결과 의존 |
| **SF-2** | Compound profile_json 스키마 미정의 | 구체적 JSON 스키마 + 예시 추가 |
| **SF-3** | CASE B 순서 제약 누락 | 구성 성분 enrichment+profiling 완료 후 compound profiling 진행 제약 명시 |
| **SF-4** | 파일럿 케이스가 스코프 정의와 불일치 | 5-tier별 파일럿 케이스 재정의 |

---

## Problem Statement (v2 수정)

현재 계획(Iteration 9)은 각 심평원성분코드를 원자적 단위로 enrichment 프로파일링한다. 그러나 분석 결과:

- **7,791건 (38.5%)** 의 터울주성분이 복합제(YY='00') — 전체 20,226건의 38.5%
- 성분 수 기준 분포:
  - **1성분 복합제 코드** (텍스트상 단일 성분이지만 코드가 '00'): 약 1,200건 추정
  - **2-3성분 복합제**: 약 2,382건 추정 (7,791 - 1,200 - 4,209)
  - **4-9성분 복합제**: 약 3,100건 (4,209건 중 다수)
  - **10-15성분 복합제**: 약 900건 (비타민 복합, 영양수액 등)
  - **16+성분 복합제**: 약 209건 (초대형 비타민/TPN 등)
- 구성 성분의 단일제 코드 존재율(YY!='00' 코드가 터울주성분에 존재) ~~96.2%~~ → **정확히는 "코드 존재율"이며, 해당 코드의 Phase 1 enrichment 완료 여부는 별개** (SF-1)
- 단일제 프로파일의 기계적 합산(union)은 복약안내로 부적절:
  - 성분 간 상호작용 누락
  - 복합 목적 맥락 상실 ("종합감기 증상 완화")
  - 부작용 우선순위 판단 불가
  - A5 공간 제약으로 10+ 단일제 프로파일 나열 불가

---

## RALPLAN-DR 요약 (v2)

### Principles (설계 원칙)

1. **단일제 enrichment 재활용 극대화 (Single-Ingredient Reuse)**: 복합제 구성 성분의 단일제 코드 존재율은 약 96%이다. 이 중 Phase 1 enrichment 완료 건의 단일제 enrichment를 구성 블록(building block)으로 재활용한다. **단, "코드 존재"와 "enrichment 완료"는 별개이며, Phase 1 결과에 따라 실제 재활용률이 결정된다.** (MF-1, SF-1)

2. **복합제 고유 맥락 보존 (Compound-Specific Context)**: 단일 성분 프로파일의 기계적 합산(union)은 복약안내로서 부적절하다. 성분 간 상호작용, 복합 목적(종합감기, 비타민 복합 등), 부작용 우선순위가 복합제 고유의 맥락이며, 이를 LLM이 판단하여 반영해야 한다.

3. **동일 조성 복합제 중복 제거 (Compound Composition Deduplication)**: 동일한 구성 성분 코드 조합을 가진 복합제 심평원성분코드들은 하나의 compound profile을 공유한다. **구성 성분 심평원성분코드 리스트를 정렬+해시하여 compound hash를 생성** — enrichment 버전과 무관하게 성분 조합이 같으면 동일 해시. (MF-2)

4. **기존 단일제 프로파일 시스템 비파괴 (Non-Breaking Extension)**: Iteration 9의 프로파일 시스템(터울복약프로파일, 해시, 매핑)의 기본 구조를 유지하면서, compound profile을 확장 레이어로 추가한다. 단일제 프로파일 로직은 변경하지 않는다.

5. **A5 공간 제약 인식 + Tiered LLM 입력 (A5 Space-Aware + Tiered Input)**: 복합제 규모에 따라 LLM 입력 전략을 차등 적용한다. 소규모(2-6성분)는 전체 enrichment, 중규모(7-15)는 요약 enrichment, 대규모(16+)는 카테고리 기반 요약. (MF-4)

### Decision Drivers (핵심 의사결정 요인)

| 순위 | 요인 | 이유 |
|------|------|------|
| 1 | **전체 복합제 커버리지 (7,791건)** | v1의 4,209건(4+성분)만 다루면 2-3성분 복합제 3,582건이 unaddressed. 모든 YY='00' 코드에 대한 전략이 필요하다 (MF-1) |
| 2 | **복합제 복약안내 품질** | 단일제 프로파일 합산으로는 "이 약은 종합감기약입니다"라는 맥락, 성분 간 상호작용, 부작용 우선순위를 전달할 수 없다 |
| 3 | **LLM 호출 효율 + 토큰 관리** | 7,791건 복합제를 개별 LLM 호출하면 비효율적이다. 성분 코드 해싱 + tiered 입력으로 중복 제거와 토큰 비용을 통제한다 (MF-2, MF-4) |

### Viable Options

#### Option A: Compound Profile Layer + 5-Tier 전략 (채택, v2 개정)

| 항목 | 내용 |
|------|------|
| **전략** | (1) 전체 7,791건 복합제를 성분 수 기반 5-tier로 분류. (2) Tier 1(1성분)은 단일제 프로파일로 처리. (3) Tier 2-5(2+성분)는 구성 성분을 3단계 fallback 알고리즘으로 식별. (4) 구성 성분 심평원성분코드 정렬+해시로 compound hash 생성 (enrichment 버전 무관). (5) Tiered LLM 입력: Small(전체), Medium(요약), Large(카테고리). (6) 동일 compound hash → 기존 profile 재사용(LLM 0회) |
| **스키마 변경** | `터울복약프로파일`에 `profile_type`, `constituent_hash`, `needs_regeneration` 컬럼 추가. `터울복합프로파일구성` 신규 테이블. compound profile의 `profile_json`에 tiered 구조 포함 |
| **장점** | (1) 7,791건 전체 커버. (2) 성분 코드 기반 해시로 cascade 무관 안정성. (3) Tiered 입력으로 토큰 비용 통제. (4) 기존 프로파일 시스템 호환 |
| **단점** | (1) 5-tier 분류 + 3-fallback 식별로 구현 복잡도 증가. (2) 구성 성분 식별 실패 시 fallback 처리 필요. (3) needs_regeneration 관리 오버헤드 |

#### Option B: 단일제 프로파일 기계적 합산 (Union Profile) — 기각

| 항목 | 내용 |
|------|------|
| **기각 근거** | Problem Statement에서 확인된 4가지 핵심 한계 그대로 적용. "기계적 합산이 작동하지 않는다"는 것이 이 iteration의 출발점 |

### ADR (Architecture Decision Record)

| 항목 | 내용 |
|------|------|
| **Decision** | Option A 채택 (v2). 전체 7,791건 복합제에 대해 5-tier compound profile layer를 추가 |
| **Drivers** | 전체 복합제 커버리지(7,791), 복약안내 품질, LLM 효율 + 토큰 관리 |
| **Alternatives Considered** | Option B (기계적 합산) — 복합 맥락 상실로 기각 |
| **Why Chosen** | 5-tier 전략으로 1성분 복합제는 단일제 처리, 2+성분은 규모별 최적화된 LLM 입력 제공. 성분 코드 기반 해시로 enrichment 버전과 무관한 안정적 중복 제거 |
| **Consequences** | 신규 테이블 1개(`터울복합프로파일구성`), 기존 테이블 컬럼 추가 3개(`profile_type`, `constituent_hash`, `needs_regeneration`). compound profile 500~1,500개 예상 (v1의 300~800에서 상향 — 2-3성분 포함). Phase 1.5 일정 +1.5일 |
| **Follow-ups** | 구성 성분 식별 알고리즘 정확도 검증, Tiered LLM 프롬프트 파일럿(5-tier별 각 1건), 성분 수 분포 실측 확인 |

---

## 5-Tier 복합제 분류 전략 (MF-1 해결)

### Tier 정의

| Tier | 성분 수 | 예상 건수 | 처리 전략 | LLM 입력 |
|------|---------|-----------|-----------|----------|
| **Tier 1** | 1성분 | ~1,200건 | **단일제 프로파일로 처리** (텍스트상 단일 성분이지만 코드가 '00'인 경우) | 단일제와 동일 (Tier 해당 없음) |
| **Tier 2** | 2-3성분 | ~2,382건 | Full enrichment pass-through | Small (전체 enrichment) |
| **Tier 3** | 4-9성분 | ~3,100건 | Full enrichment pass-through | Small (전체 enrichment) |
| **Tier 4** | 10-15성분 | ~900건 | Summarized enrichment per constituent | Medium (요약) |
| **Tier 5** | 16+성분 | ~209건 | Category-based summarization | Large (카테고리) |

**합계**: 7,791건 = Tier 1(~1,200) + Tier 2(~2,382) + Tier 3(~3,100) + Tier 4(~900) + Tier 5(~209)

> **주의**: 위 건수는 추정치. Phase 1.5 시작 시 실제 분포를 `_split_ingredients()`로 계측하여 확정한다.

### Tier 1 처리: 1성분 복합제

```
코드가 YY='00'이지만 성분명 텍스트에 콤마가 없는 경우 (단일 성분 텍스트):
  → 해당 성분명으로 단일제 enrichment/프로파일 매칭 시도
  → 매칭 성공 시: 단일제 프로파일(profile_type='single')에 매핑
  → 매칭 실패 시: 해당 성분의 단일제 enrichment 실행 후 단일제 프로파일 생성

코드가 YY='00'이고 구성 성분 식별 결과 1개만 발견된 경우도 동일 처리.
```

### Tier 2-3 처리: 2-9성분 (Small LLM Input)

```
구성 성분의 단일제 enrichment 전체를 LLM에 전달:
  - 각 구성 성분의 6개 필드 전체 (mechanism, side_effects, contraindications,
    interactions, monitoring, special_pop)
  - 복합 목적 맥락 ("종합감기약", "복합 진통제" 등)
  - 성분 간 상호작용 특별 지시

토큰 예산: ~4,000-8,000 tokens (입력)
```

### Tier 4 처리: 10-15성분 (Medium LLM Input)

```
각 구성 성분에서 핵심 정보만 요약하여 전달:
  - mechanism: action_type + target_name (1줄)
  - side_effects: severity='critical'/'severe'만 (상위 3개)
  - interactions: critical interactions만 (상위 3개)
  - contraindications: 전체 (환자안전)
  - monitoring/special_pop: 생략 (compound 레벨에서 LLM이 판단)

토큰 예산: ~6,000-10,000 tokens (입력)
```

### Tier 5 처리: 16+성분 (Large LLM Input)

```
구성 성분을 therapeutic class(약효분류)별로 그룹핑 후 카테고리 요약:
  예: "비타민 B군 6종: B1, B2, B3, B5, B6, B12"
      "미네랄 4종: Fe, Zn, Cu, Mn"
      "아미노산 8종: ..."

  각 카테고리에서:
    - 공통 mechanism 1줄
    - 카테고리 대표 side_effects (상위 2개)
    - 카테고리 대표 critical interactions (있을 경우)

토큰 예산: ~4,000-8,000 tokens (입력 — 카테고리 압축으로 제어)
```

---

## 구성 성분 식별 알고리즘 (MF-3 해결)

### 3단계 Fallback 알고리즘

복합제 심평원성분코드의 구성 성분(단일제 코드)을 식별하는 데 3가지 접근법을 우선순위 순으로 적용한다.

#### Step 1 (Primary): ProductInfos.IngredientCode 파싱

```
복합제 심평원성분코드 → pharmport_medicine.ingredient_code 매칭
  → 해당 medicine의 product_code로 ProductInfos 조회
  → ProductInfos.IngredientCode 필드에서 개별 성분코드 추출

ProductInfos.IngredientCode 포맷 예시:
  "101340AIJ;201520BTB;305100ACR"
  → 세미콜론(;)으로 분리 → ["101340AIJ", "201520BTB", "305100ACR"]
  → 각각이 단일제 심평원성분코드(9자리)

장점: 구조화된 코드 → 파싱 정확도 100%
단점: pharmport_medicine 매칭(29,882건)이 필요. 매칭 안 된 복합제는 불가
```

**구체적 예시**:
```
복합제: 101300ACR (acetaminophen+codeine 복합제)
  → pharmport_medicine에서 ingredient_code='101300ACR' 검색
  → product_code='655900020' 발견
  → ProductInfos에서 ProductCode='655900020' 조회
  → IngredientCode = "101301AIJ;120201AIJ"
  → 구성 성분: 101301AIJ (acetaminophen 단일제), 120201AIJ (codeine 단일제)
```

#### Step 2 (Fallback): 터울주성분.성분명 텍스트 파싱

```
복합제 코드의 성분명 텍스트를 콤마로 분리(괄호 내 콤마 무시)
  → 각 파트에서 함량 제거 → clean 성분명
  → 터울주성분에서 성분명 ILIKE 매칭 + YY!='00' 필터
  → 단일제 심평원성분코드 후보 추출

기존 코드: enrich_new_ingredient.py의 _handle_combo() + _split_ingredients()

예시:
  복합제 101300ACR, 성분명: "Acetaminophen 500mg, Codeine phosphate 30mg"
  → 분리: ["Acetaminophen", "Codeine phosphate"]
  → 터울주성분 검색: "Acetaminophen" → 101301AIJ 등 발견
  → 터울주성분 검색: "Codeine phosphate" → 120201AIJ 등 발견

장점: ProductInfos 매칭 불필요. 기존 코드 존재
단점: 텍스트 파싱의 부정확성 (성분명 변형, 동의어)
      → 후보가 여러 개일 때 어떤 코드를 선택할지 판단 필요
      → 동일 주성분(1-4자리) 중 대표 코드를 선택하는 로직 필요
```

#### Step 3 (Last resort): 심평원성분코드 1-4자리(base) + YY='01~' 룩업

```
복합제의 1-4자리(주성분 일련번호) → 동일 base를 가진 YY!='00' 코드 검색
  → 이것은 "이 복합제 자체의 단일제 변형"을 찾는 것이 아님
  → 복합제의 성분명 텍스트에서 추출된 개별 성분명에 대해,
     해당 성분명의 base(1-4자리)를 알아낸 뒤 대표 코드를 선택

단, Step 2에서 이미 성분명→코드 매칭이 실패한 경우에만 도달.
이 경우 수동 매핑 대상으로 분류.
```

### 식별 실패 처리

```
3단계 모두 실패한 구성 성분:
  → constituent_identification_status = 'unresolved'
  → 해당 복합제 전체를 "manual_review" 큐에 등록
  → 성분 수에서 식별 실패 건을 제외한 나머지로 partial compound profile 생성하지 않음
  → 전체 구성 성분 식별 성공 후에만 compound profile 생성

목표: 구성 성분 파싱 성공률 >= 95% (7,791건 중 >= 7,401건)
```

### 알고리즘 적용 순서 요약

```
[1] 복합제 코드 7,791건 수집
    │
[2] Tier 분류 (성분 수 판별)
    │  └─ _split_ingredients()로 성분 수 카운트
    │  └─ Tier 1(1성분) → 단일제 프로파일로 직접 처리 (compound profile 불필요)
    │
[3] Tier 2-5: 구성 성분 식별
    │  ├─ Step 1: ProductInfos.IngredientCode 파싱 (우선)
    │  ├─ Step 2: 터울주성분.성분명 텍스트 매칭 (fallback)
    │  └─ Step 3: base+YY 룩업 (last resort)
    │
[4] 식별 성공 → compound hash 생성 + profile 생성
    식별 실패 → manual_review 큐
```

---

## Compound Hash 설계 (MF-2 해결)

### v1 문제점

v1은 구성 성분의 `profile_hash`를 concat하여 compound hash를 생성했다:
```
v1: SHA-256(sort([profileHash_A, profileHash_B, profileHash_C]))
```

**문제**: 구성 성분의 enrichment가 업데이트되면 → 단일제 profile_hash 변경 → compound hash 변경 → cascade invalidation. 동일 성분 조합인데도 해시가 달라져서 compound profile이 중복 생성된다.

### v2 수정: 성분 코드 직접 해시

```
v2: SHA-256(sort([심평원성분코드_A, 심평원성분코드_B, 심평원성분코드_C]))
```

**규칙**:
1. 복합제의 구성 성분 심평원성분코드(단일제)를 수집
2. 알파벳순 정렬
3. 파이프(|)로 concat: `"101301AIJ|120201AIJ|305100ACR"`
4. SHA-256 해시 = `constituent_hash`
5. **동일 성분 코드 조합이면 반드시 동일 해시** — enrichment 버전, profile 버전과 무관

### `needs_regeneration` 플래그

구성 성분의 enrichment가 변경되었을 때 compound profile의 복약안내를 재생성해야 하는지 추적:

```
constituent_hash: 성분 코드 조합 해시 (불변 — 성분이 같으면 동일)
needs_regeneration: BOOLEAN DEFAULT FALSE
  → TRUE로 설정되는 조건:
    1. 구성 성분 중 하나의 단일제 enrichment가 업데이트됨
    2. 구성 성분 중 하나의 단일제 profile이 변경됨
  → FALSE로 리셋되는 조건:
    1. compound profile의 LLM 복약안내가 재생성됨

재생성 우선순위:
  - needs_regeneration=TRUE인 compound profile을 주기적으로 스캔
  - 구성 성분의 변경이 safety-critical인 경우 즉시 재생성
  - 그 외는 배치로 재생성
```

---

## Compound profile_json 스키마 (SF-2 해결)

### JSON 스키마 정의

```json
{
  "profile_type": "compound",
  "tier": 3,
  "compound_purpose": "종합감기 증상 완화",
  "constituent_count": 4,
  "constituents": [
    {
      "code": "101301AIJ",
      "name": "Acetaminophen",
      "name_kr": "아세트아미노펜",
      "role_in_compound": "해열/진통",
      "single_profile_id": 42,
      "enrichment_summary": {
        "mechanism": ["COX inhibitor (central)"],
        "top_side_effects": ["간독성 (critical)", "위장장애 (moderate)"],
        "critical_interactions": ["와파린", "이소니아지드"],
        "critical_contraindications": ["중증 간장애"]
      }
    },
    {
      "code": "120201AIJ",
      "name": "Chlorpheniramine maleate",
      "name_kr": "클로르페니라민말레산염",
      "role_in_compound": "항히스타민(비염/재채기)",
      "single_profile_id": 87,
      "enrichment_summary": {
        "mechanism": ["H1 receptor antagonist"],
        "top_side_effects": ["졸음 (severe)", "입마름 (moderate)"],
        "critical_interactions": ["MAO 억제제", "중추신경 억제제"],
        "critical_contraindications": ["녹내장", "전립선비대증"]
      }
    }
  ],
  "compound_interactions": [
    {
      "between": ["Acetaminophen", "Chlorpheniramine"],
      "type": "additive_sedation",
      "description": "중추신경 억제 효과 상승"
    }
  ],
  "compound_context": {
    "therapeutic_class": "종합감기약",
    "primary_indication": "감기 증상(발열, 코막힘, 기침, 재채기) 완화",
    "key_warnings": ["졸음 — 운전/기계조작 주의", "1일 최대 복용량 초과 금지(간독성 위험)"]
  },
  "llm_input_tier": "small",
  "token_budget": 6000,
  "version": 1,
  "generated_at": "2026-03-20T10:00:00Z"
}
```

### Tier별 profile_json 차이

| 필드 | Small (Tier 2-3) | Medium (Tier 4) | Large (Tier 5) |
|------|-------------------|------------------|-----------------|
| `constituents[].enrichment_summary` | 6개 필드 전체 | mechanism + top 3 side_effects + critical interactions/contraindications만 | 생략 (카테고리 요약으로 대체) |
| `compound_interactions` | 전체 | critical만 | 카테고리 간 상호작용만 |
| `compound_context.categories` | 없음 | 없음 | 있음 (약효분류 그룹핑) |
| `token_budget` | 4,000-8,000 | 6,000-10,000 | 4,000-8,000 |

---

## Section-by-Section 변경 목록

아래는 `enrichment-format-parity.md` (Iteration 9)에서 Iteration 10으로 업데이트해야 하는 섹션별 변경 사항이다.

### 1. Header + 메타데이터 (Line 1-7)

- "Iteration 9" -> "Iteration 10"
- 최종 수정 줄 업데이트: "Iteration 10 — 복합제(Compound Drug) Profile 전략. 7,791건(38.5%) 복합제 전체 대응: 5-tier 분류 + 성분 코드 기반 compound hash + tiered LLM 입력"
- Principle #10 추가 언급

### 2. 목차 (Line 11-41)

- Section 4.9 설명 업데이트: "Enrichment 결과 해싱 -> 프로파일 생성 -> **단일제/복합제 5-tier 분기** -> 성분 그룹핑"
- Section 3.2 설명 업데이트: "터울복약프로파일 **+ profile_type/constituent_hash/needs_regeneration**, 매핑 테이블 DDL"

### 3. RALPLAN-DR 요약 — Principles (Line 47-57)

**Principle #10 신규 추가**:

> 10. **복합제 Compound Profile 전략**: 7,791건(38.5%) 복합제를 5-tier로 분류하여 전체 커버한다. Tier 1(1성분)은 단일제 처리, Tier 2-5(2+성분)는 구성 성분의 단일제 enrichment를 재활용하되, 복합 맥락(상호작용, 복합 목적, 부작용 우선순위)을 tier별 LLM 입력 전략으로 생성한다. 동일 성분 코드 조합은 constituent_hash로 중복 제거한다.

### 4. RALPLAN-DR 요약 — ADR (Line 87-96)

- Consequences 업데이트:
  - "신규 테이블: enrichment 9개(기존 DB) + 프로파일 5개 + **복합제구성 1개** + 복약안내 3개 + 매핑/메타(신규 DB)"
  - "LLM 호출 ~~20,000→500~1,500~~ → 1,000~3,000건 (단일제 500~1,500 + 복합제 500~1,500)"
  - "Phase 1.5: 프로파일 클러스터링 + **복합제 5-tier 프로파일링** 포함"

### 5. Section 3.2 프로파일 시스템 테이블 DDL (Line 381-453)

**터울복약프로파일 DDL 변경**:
```sql
-- 터울복약프로파일에 컬럼 추가:
profile_type        VARCHAR(20) NOT NULL DEFAULT 'single',  -- 'single' | 'compound'
constituent_hash    VARCHAR(64),  -- compound인 경우: 구성 성분 코드 조합 해시 (SHA-256). single은 NULL
needs_regeneration  BOOLEAN DEFAULT FALSE,  -- compound: 구성 성분 enrichment 변경 시 TRUE

-- 인덱스 추가:
CREATE INDEX idx_profile_type ON "터울복약프로파일"(profile_type);
CREATE INDEX idx_constituent_hash ON "터울복약프로파일"(constituent_hash) WHERE constituent_hash IS NOT NULL;
CREATE INDEX idx_needs_regen ON "터울복약프로파일"(needs_regeneration) WHERE needs_regeneration = TRUE;
```

**신규 테이블 DDL 추가**:
```sql
-- 복합제 프로파일 구성 성분 매핑
CREATE TABLE "터울복합프로파일구성" (
    compound_profile_id  INT NOT NULL REFERENCES "터울복약프로파일"(profile_id),
    constituent_code     VARCHAR(450) NOT NULL,  -- 구성 성분 심평원성분코드(단일제)
    constituent_profile_id INT REFERENCES "터울복약프로파일"(profile_id),  -- 해당 성분의 단일제 프로파일 (NULL 가능: enrichment 미완료)
    role_in_compound     TEXT,           -- 복합제 내 역할 ("해열/진통", "항히스타민" 등)
    sort_order           INT DEFAULT 0,
    PRIMARY KEY (compound_profile_id, constituent_code)
);
CREATE INDEX idx_compound_constituent ON "터울복합프로파일구성"(constituent_code);
```

**프로파일 해시 생성 규칙** 업데이트 (MF-2):
- 기존 단일제 해시 규칙 유지 (6개 필드 정규화 -> SHA-256 = `profile_hash`)
- **Compound constituent_hash 규칙 (v2 수정)**:
  1. 구성 성분 심평원성분코드를 알파벳순 정렬
  2. 파이프(|)로 concat: `"101301AIJ|120201AIJ|305100ACR"`
  3. SHA-256(concat 결과) = `constituent_hash`
  4. **동일 성분 코드 조합이면 반드시 동일 해시 — enrichment/profile 버전과 무관**
  5. compound의 `profile_hash`는 별도로 생성: LLM 생성 결과 기반 (단일제와 동일 로직)
  6. `needs_regeneration` = TRUE일 때 `profile_hash`와 복약안내를 재생성

**프로파일 예시** (SF-2 반영):
```
프로파일 #C (복합 감기약 — 아세트아미노펜+클로르페니라민+슈도에페드린+덱스트로메토르판):
  profile_type: "compound"
  tier: 3 (4성분 → Tier 3)
  constituent_hash: SHA-256("101301AIJ|120201AIJ|305100ACR|410250AIJ") = "a1b2c3..."
  profile_json: { ... compound_context, constituents 전체 enrichment ... }

  → LLM 입력: Small tier (4개 단일제 enrichment 전체 + "종합감기 증상 완화 복합제" 맥락)
  → LLM 출력: 복합 맥락 반영 복약안내 (상호작용, 우선순위, 통합 목적)
  → 동일 4성분 코드 조합의 다른 복합제 코드 → 동일 constituent_hash → 동일 compound profile 재사용
  → 구성 성분 enrichment 변경 시: needs_regeneration = TRUE → 배치 재생성
```

### 6. Section 3.3 복약안내 테이블 (Line 455-537)

- **변경 없음**. compound profile도 동일한 `터울복약안내A4/A5` 테이블 + 프로파일 매핑을 사용. profile_id 기반이므로 단일제/복합제 구분 없이 동일 구조.

### 7. Section 3.5 DB 분리 아키텍처 다이어그램 (Line 608-700)

- 신규 DB 다이어그램에 `터울복합프로파일구성` 테이블 추가 (터울복약프로파일의 하위)
- 신규 DB 테이블 목록에 16번째 행 추가:

| 16 | `터울복합프로파일구성` | 신규 | compound profile -> 구성 성분 매핑 | ~6,600 x avg 4.5 = ~29,700 |

- `터울복약프로파일` 예상 건수: "500~1,500" -> "1,000~3,000 (단일제 500~1,500 + 복합제 500~1,500)"

### 8. Section 4.9 Phase 1.5 프로파일 클러스터링 (Line 975-1033)

**가장 큰 변경 섹션**. 전체 프로세스를 2단계로 분리. **순서 제약 추가 (SF-3)**.

**기존 프로세스 [1]~[5]를 "Step A: 단일제 프로파일링"으로 리네이밍** (로직 변경 없음)

**순서 제약 (SF-3)**: Step B는 반드시 Step A 완료 후 실행한다. 이유: compound profile의 구성 성분이 단일제 프로파일에 이미 배정되어 있어야 constituent_profile_id를 기록할 수 있고, LLM 입력에 단일제 enrichment를 포함할 수 있다.

**Step B: 복합제 프로파일링 추가**:
```
[B0] 복합제 분포 계측 (1회성)
    └─ 터울주성분에서 YY='00'인 전체 7,791건 수집
    └─ 각 코드에 대해 _split_ingredients()로 성분 수 카운트
    └─ Tier 1/2/3/4/5 분포 확정 → 로그 출력 + 리포트 저장

[B1] Tier 1 처리: 1성분 복합제
    └─ 성분명 텍스트에 단일 성분만 존재하는 코드 필터
    └─ 해당 성분의 단일제 프로파일 검색 → 매칭 시 단일제 프로파일에 매핑
    └─ profile_type = 'single' (compound가 아닌 단일제 프로파일 공유)
    └─ 매칭 실패 시: Phase 1 enrichment 추가 대상으로 등록

[B2] Tier 2-5 구성 성분 식별 (3단계 fallback)
    └─ Step 1: ProductInfos.IngredientCode 파싱 (우선)
    └─ Step 2: 터울주성분.성분명 텍스트 매칭 (fallback)
    └─ Step 3: base+YY 룩업 (last resort)
    └─ 3단계 모두 실패 → manual_review 큐
    └─ ★ 구성 성분이 Step A에서 단일제 프로파일에 배정되었는지 확인 ★
        └─ 배정됨: constituent_profile_id 기록 가능
        └─ 미배정 (enrichment 미완료): 해당 성분 Phase 1 enrichment 완료 후 재시도
           또는 enrichment 부분 완료 시 "minimal" enrichment로 진행

[B3] Compound constituent_hash 생성
    └─ 구성 성분 심평원성분코드 알파벳순 정렬
    └─ 파이프(|)로 concat
    └─ SHA-256 = constituent_hash
    └─ ★ enrichment/profile 버전과 무관 — 성분 코드만으로 결정 ★

[B4] Compound 프로파일 생성/매핑
    └─ constituent_hash가 터울복약프로파일에 이미 존재?
        ├─ YES: 기존 compound profile_id에 복합제 코드 매핑 (LLM 0회)
        └─ NO:  신규 compound 프로파일 INSERT
              profile_type='compound'
              constituent_hash = 계산된 해시
              needs_regeneration = FALSE
              profile_json에 tier별 구조 포함 (SF-2)
              터울복합프로파일구성에 구성 관계 기록

[B5] Compound 프로파일 통계
    └─ Tier별 건수: Tier 1/2/3/4/5 각각
    └─ 총 compound profile 수, 복합제 코드 매핑 분포
    └─ 동일 조성 중복 제거율 (7,791건 → ~500~1,500 profiles)
    └─ 구성 성분 식별 성공률 (목표 >= 95%)
    └─ Tier별 평균 성분 수
```

**수락 기준 업데이트**:
- [ ] 단일제 enrichment 완료 성분 100% 프로파일 배정 (기존)
- [ ] 프로파일 해시 유일성 100% (기존)
- [ ] 프로파일 통계 리포트 생성 (기존)
- [ ] 단일제 프로파일 수가 단일제 성분 수의 3~25% (기존)
- [ ] **Step A(단일제 프로파일링) 완료 후에만 Step B(복합제) 착수** (SF-3)
- [ ] **복합제 7,791건 전체 Tier 분류 완료**
- [ ] **구성 성분 식별 성공률 >= 95% (7,791건 중 >= 7,401건)**
- [ ] **Tier 1(~1,200건) → 100% 단일제 프로파일에 매핑**
- [ ] **Tier 2-5(~6,591건) → 100% compound profile에 배정**
- [ ] **compound profile 수가 Tier 2-5 복합제 수의 7~23% (500~1,500 / 6,591)**
- [ ] **constituent_hash 유일성 100% (동일 성분 조합 = 동일 해시)**

**예상 결과 업데이트**:
```
단일제: ~12,429건 → 500~1,500 profiles
복합제: ~7,791건
  - Tier 1 (~1,200건) → 단일제 프로파일 공유 (추가 profile 0개)
  - Tier 2-5 (~6,591건) → 500~1,500 compound profiles
합계 프로파일: 1,000~3,000
LLM 호출 총계: 1,000~3,000 (기존 20,000 대비 85~95% 절감)
```

### 9. Section 5 Phase 2: Format Parity (Line 1036-1039)

- 게이트 설명: "Phase 1.5 프로파일 클러스터링(**단일제 Step A + 복합제 Step B**) 완료 후 착수"
- 핵심 변경 설명: "프로파일(1,000~3,000)마다 1회 호출. 단일제 프로파일은 기존 방식, **compound 프로파일은 tier별 LLM 입력 전략(Small/Medium/Large)으로 복합 맥락 전달**"

### 10. Section 5.2 복약안내 문장 생성 원칙 (Line 1075-1093)

LLM 프롬프트 가이드라인에 compound 전용 항목 추가:

> 5. 복합제의 경우, 복합 목적(종합감기, 비타민 보충 등)을 첫 문장에 명시할 것
> 6. 구성 성분 간 상호작용/상승효과를 우선적으로 언급할 것
> 7. 부작용은 빈도/심각도 기준으로 상위 5개 이내로 요약할 것 (A5 공간 제약)
> 8. **Tier 4-5(10+성분)의 경우**: 개별 성분 나열보다 카테고리 기반 설명 사용 (예: "비타민 B군", "미네랄류")
> 9. **Tier에 관계없이**: 환자안전 관련 critical 경고(BBW, 심각한 상호작용)는 반드시 포함

### 11. Section 5.3 A5 간략 포맷 (Line 1095-1132)

복합제 A5 예시 추가 (Tier별):

```
Tier 2-3 (2-9성분):
  [종합감기약] 해열, 항히스타민, 진해, 비충혈 완화 복합제입니다.
              졸음에 주의하고, 1일 최대 복용량을 초과하지 마십시오.

Tier 4 (10-15성분):
  [종합비타민/미네랄] 비타민 B군, 비타민 C, 철분 등 12종 영양소 복합입니다.
              철분 함유로 위장장애가 있을 수 있으며, 항생제와 간격을 두세요.

Tier 5 (16+성분):
  [고영양수액] 아미노산 15종, 전해질, 포도당 복합 수액입니다.
              전해질 불균형에 주의하며, 투여 속도를 준수하십시오.
```

Compound A5 JSONB 구조 예시:
```json
{
  "badges": ["알코올 주의", "운전 주의"],
  "약효분류": "종합감기약",
  "약효설명": "해열, 항히스타민, 진해, 비충혈 완화 복합제입니다. 졸음에 주의하고, 1일 최대 복용량을 초과하지 마십시오.",
  "source": "llm_generated",
  "profile_type": "compound",
  "tier": 3,
  "constituent_count": 4,
  "version": 1
}
```

### 12. Section 7 단계별 로드맵 (Line 1369-1528)

**Phase 1.5** (Day 14-15 -> Day 14-16.5, +1.5일):
- 기존 단일제 프로파일링 태스크 유지 (Step A — Day 14-15)
- **Step A 완료 후** 복합제 프로파일링 착수 (Step B — Day 15-16.5) (SF-3):
  - [ ] `build_profiles.py`에 compound profiling 로직 추가
    - [B0] 복합제 7,791건 Tier 분포 계측
    - [B1] Tier 1 처리 (단일제 프로파일 매핑)
    - [B2] 구성 성분 식별 (3단계 fallback)
    - [B3] constituent_hash 생성 + 중복 제거
    - [B4] compound profile 생성 + 터울복합프로파일구성 데이터 생성
    - [B5] 통계 리포트
  - [ ] compound 프로파일 통계 리포트 (Tier별 집계)

**Phase 2-A** (Day 17-18.5로 1.5일 shift):
- `create_v2_tables.py`에 `터울복합프로파일구성` DDL 추가
- `터울복약프로파일`에 `profile_type`, `constituent_hash`, `needs_regeneration` 컬럼 DDL 추가
- 프로파일 데이터 이관에 compound profiles 포함

**Phase 2-B** (Day 19.5-24로 1.5일 shift):
- LLM 프롬프트 템플릿에 compound 전용 3-tier 템플릿 추가 (Small/Medium/Large)
- **파일럿에 5-tier별 각 1건 포함** (SF-4):
  - Tier 1: 1성분 복합제 코드 → 단일제 프로파일 매핑 검증
  - Tier 2: 2-3성분 복합 진통제 (예: acetaminophen+codeine)
  - Tier 3: 4-6성분 종합감기약
  - Tier 4: 10-12성분 종합비타민
  - Tier 5: 16+성분 대형 비타민/TPN
- 수락 기준: "Tier 2-5 compound profile 100% LLM 생성 완료" 추가
- LLM 총 호출 수 기준: "<= 3,000 (단일제 1,500 + 복합제 1,500)"

### 13. Section 9.2 신규 코드 처리 Flow (Line 1617-1677)

**CASE B (복합제) 로직 업데이트** (SF-3 반영):
```
├─ CASE B: 복합제(00)
│   └─ [순서 제약] 구성 성분의 단일제 enrichment + profiling 완료 확인
│       ├─ 모두 완료: 아래 진행
│       └─ 미완료 건 존재: 해당 성분 enrichment 완료 대기 → 재시도 큐
│   └─ 성분 수 판별 → Tier 분류
│       ├─ Tier 1 (1성분): 단일제 프로파일 매칭 (compound profile 불필요)
│       └─ Tier 2-5: 구성 성분 식별 (3단계 fallback)
│   └─ 구성 성분 코드 정렬 → SHA-256 = constituent_hash
│   └─ 기존 compound profile 매칭 시도 (constituent_hash)
│       ├─ MATCH: 기존 compound profile 재사용 (LLM 0회)
│       └─ NO MATCH: tier별 LLM 1회 호출 (Small/Medium/Large)
│   └─ FDA label: 복합제 전용 label 검색 (성분 조합으로 openFDA 조회)
```

**Step 5 프로파일 매칭에 compound 분기 추가**:
- 단일제 코드 → 기존 단일제 프로파일 매칭 (변경 없음)
- 복합제 코드 Tier 1 → 단일제 프로파일 매칭 (신규)
- 복합제 코드 Tier 2-5 → compound profile 매칭 (신규)

### 14. Section 10 파일 구조 (Line 1691-1722)

- `build_profiles.py` 설명 업데이트: "[신규] Phase 1.5: Enrichment 프로파일 해싱 + 클러스터링 + **단일제(Step A)/복합제 5-tier(Step B)** + 매핑"
- `docs/llm-prompt-templates.md` 설명 업데이트: "[신규] LLM 복약안내 프롬프트 템플릿 (A4/A5, **단일제/복합제 3-tier(Small/Medium/Large)**)"
- 파일 수 변동 없음 (기존 파일 확장, 터울복합프로파일구성은 create_v2_tables.py에 포함)

### 15. Section 11 예상 수치 요약 (Line 1726-1745)

신규/변경 행:

| 항목 | 보수적 | 낙관적 | 근거 |
|------|--------|--------|------|
| **복합제 코드 수 (전체 YY='00')** | **7,791** | **7,791** | **전체 복합제. 기존 20,226건의 38.5%** |
| **Tier 1 (1성분 복합제)** | **~1,000** | **~1,400** | **단일제 프로파일 공유 → 추가 profile 0개** |
| **Tier 2-5 (2+성분 복합제)** | **~6,391** | **~6,791** | **compound profile 대상** |
| **구성 성분 단일제 코드 존재율** | **93%** | **97%** | **96% 평균. "코드 존재"이며 enrichment 완료와 별개 (SF-1)** |
| **구성 성분 식별 성공률** | **95%** | **98%** | **3단계 fallback 알고리즘** |
| **Compound profile 수 (추정)** | **500** | **1,500** | **동일 성분 코드 조합 중복 제거** |
| **단일제 profile 수** | **500** | **1,500** | **(기존 유지)** |
| **총 프로파일 수** | **1,000** | **3,000** | **단일제 + 복합제** |
| **LLM 복약안내 생성 대상** | **1,000** | **3,000** | **프로파일 단위 생성. 기존 20,000 대비 85~95% 절감** |

기존 행 수정:
- "Enrichment 프로파일 수": 500~1,500 -> 1,000~3,000
- "LLM API 호출 예상": ~500~1,500 -> ~1,000~3,000
- "프로파일당 평균 매핑 성분 수": 단일제/복합제 별도 산출
  - 단일제: ~8~24 (12,429 / 500~1,500)
  - 복합제: ~4~13 (6,591 / 500~1,500)

### 16. Section 12 Success Criteria (Line 1748-1769)

**신규 항목 추가**:
- 21. **복합제 7,791건 전체가 Tier 분류 완료 (누락 0건)**
- 22. **Tier 1 복합제 100% 단일제 프로파일에 매핑**
- 23. **Tier 2-5 복합제 100% compound profile에 매핑 (누락 0건)**
- 24. **compound profile LLM 생성 복약안내에 복합 맥락(목적, 성분 간 상호작용) 포함 확인 (5-tier 파일럿 전문가 검토)**
- 25. **동일 성분 코드 조합 복합제의 constituent_hash 일치율 = 100% (구조적 보장)**
- 26. **구성 성분 식별 성공률 >= 95%**
- 27. **constituent_hash는 성분 코드만으로 생성 — enrichment/profile 버전 변경으로 hash가 변하지 않음을 검증**

**기존 항목 수정**:
- #17: "전체 enriched 성분이 프로파일에 매핑" -> "전체 enriched 성분(**단일제 + 복합제 7,791건 전체**)이 프로파일에 매핑"
- #19: "LLM 호출 수 <= 1,500" -> "LLM 호출 수 <= 3,000 (단일제 <= 1,500 + 복합제 <= 1,500)"

### 17. Section 13 Guardrails (Line 1773-1809)

**Must Have 추가**:
- 복합제 7,791건 전체를 5-tier로 분류하여 처리 (4+성분만 다루지 않음)
- compound constituent_hash는 **구성 성분 심평원성분코드 정렬+concat+SHA-256**으로 생성 (enrichment/profile 버전 무관) (MF-2)
- 구성 성분 식별에 3단계 fallback 알고리즘 적용 (ProductInfos → 텍스트 파싱 → base 룩업) (MF-3)
- compound profile LLM 프롬프트에 tier별 입력 전략 적용 (Small/Medium/Large) (MF-4)
- **Step B(복합제 프로파일링)는 Step A(단일제 프로파일링) 완료 후에만 착수** (SF-3)
- 구성 성분 중 단일제 enrichment 미완료 건은 해당 성분 Phase 1 enrichment 완료 후 compound profiling 진행
- `needs_regeneration` 플래그로 구성 성분 enrichment 변경 시 compound profile 재생성 추적

**Must NOT Have 추가**:
- 복합제에 대해 구성 성분 단일제 프로파일의 기계적 합산(union)으로 복약안내 생성 (compound 전용 LLM 호출 필수)
- 복합제 구성 성분 파싱 없이 복합제 심평원성분코드를 단일제와 동일하게 처리
- compound hash를 구성 성분의 profile_hash에 의존하여 생성 (cascade invalidation 위험) (MF-2)
- Tier 4-5(10+성분)에 전체 enrichment를 LLM에 전달 (토큰 예산 초과 위험) (MF-4)

### 18. Changelog (Line 1813+)

Iteration 10 항목 추가:

| # | 피드백 | 변경 내용 | 영향 범위 |
|---|--------|----------|----------|
| **44** | 사용자: 복합제 대응 | v1: 4,209건(4+성분)만 다룸 → v2: **7,791건(38.5%) 전체** 복합제 대응. 5-tier 분류(1성분/2-3/4-9/10-15/16+). Principle #10 신규 추가 | Principle #10, ADR, Section 3.2, 3.5, 4.9, 5, 7, 9, 11, 12, 13 |
| **45** | Architect: 4,209 vs 7,791 스코프 불일치 (MF-1) | 전체 7,791건 복합제를 5-tier로 분류. Tier 1(1성분)은 단일제 처리, Tier 2-5는 compound profile. 모든 수치 업데이트 | 전체 수치, 예상 결과, 수락 기준 |
| **46** | Architect: compound hash cascade 문제 (MF-2) | v1: profile_hash concat → v2: **성분 코드 직접 해시**. `needs_regeneration` 플래그 추가. enrichment 버전과 무관한 안정적 해시 | Section 3.2 DDL, 해시 규칙, Guardrails |
| **47** | Critic: 구성 성분 식별 알고리즘 미정의 (MF-3) | 3단계 fallback: ProductInfos.IngredientCode → 텍스트 파싱 → base+YY 룩업. 구체적 예시 포함 | Section 4.9, 9.2 |
| **48** | Critic: Tiered LLM 입력 전략 없음 (MF-4) | Small(2-9성분, 전체 enrichment, 4-8K tokens) / Medium(10-15성분, 요약, 6-10K) / Large(16+성분, 카테고리, 4-8K). 토큰 예산 명시 | Section 4.9, 5.2, 5.3, 7 |
| **49** | Critic: 96.2%를 enrichment 완료로 오해 (SF-1) | "코드 존재율"로 명확화. Phase 1 enrichment 완료 여부는 별개 | Problem Statement, Principle #1 |
| **50** | Architect: profile_json 스키마 미정의 (SF-2) | JSON 스키마 정의 + tier별 차이 + 구체적 예시 | 별도 섹션 추가 |
| **51** | Architect: Step B 순서 제약 누락 (SF-3) | Step A(단일제) 완료 후 Step B(복합제) 착수 제약 명시. CASE B에도 순서 제약 추가 | Section 4.9, 7, 9.2, Guardrails |
| **52** | Critic: 파일럿 케이스 불일치 (SF-4) | 5-tier별 각 1건 파일럿으로 재정의. Tier 1: 1성분, Tier 2: 2-3성분 진통제, Tier 3: 4-6성분 감기약, Tier 4: 10-12성분 비타민, Tier 5: 16+성분 TPN | Section 7 Phase 2-B |
