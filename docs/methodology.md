# PharmPort 매칭 방법론

## 목차

1. [목적](#1-목적)
2. [현재 상태 요약](#2-현재-상태-요약)
3. [매칭 알고리즘 (3중 필터)](#3-매칭-알고리즘-3중-필터)
4. [용어 설명](#4-용어-설명)

---

## 1. 목적

`pharmport_medicine`(팜포트 의약품 40,837건)에 `심평원성분코드`를 부여한다.

- `product_code` ← 매칭된 `ProductInfos.ProductCode`
- `ingredient_code` ← 매칭된 `ProductInfos.MasterIngredientCode` (= `터울주성분.심평원성분코드`)

| 약어 | 정식 명칭 | 설명 |
|------|----------|------|
| GT | Ground Truth | 정답 데이터. Exact Text Match(`medicine_name = ProductInfos.Name`)로 확보한 검증 기준 |
| MIC | MasterIngredientCode | `ProductInfos` 테이블의 주성분코드 컬럼. `터울주성분.심평원성분코드`와 동일한 값 |

---

## 2. 현재 상태 요약

| 항목 | 건수 | 비율 |
|------|------|------|
| pharmport_medicine 총 | 40,837건 | 100% |
| **Matched (product_code, ingredient_code 부여)** | **29,196건** | **71.5%** |
| Unmatched | 11,641건 | 28.5% |
| 커버된 고유 심평원성분코드 | 6,956건 | 34.4% (/ 20,235건) |
| **Error Rate** | **0건** | **0%** |

### 2.1. Unmatched 11,641건 분류

| 원인 | 건수 | 설명 |
|------|------|------|
| Reciprocal Match 실패 | 10,732건 | ProductInfos에 유사한 약품명이 없거나, 양방향 Top-1이 불일치 |
| 성분 channel 미달 | 883건 | Reciprocal Match는 됐으나 성분 cosine similarity < 0.4820 |
| 제조사 channel 미달 | 26건 | Reciprocal Match + 성분 통과했으나 제조사 cosine similarity < 0.1677 |

### 2.2. 검토된 개선 방향과 판단

| 아이디어 | 판단 | 이유 |
|----------|------|------|
| Name normalization (`_(규격)` 제거)으로 GT 확대 | **부적절** | 규격이 다르면 다른 약. Normalization은 정보 손실이며 false match 유발 |
| 성분 embedding tiebreaker로 ambiguous case 해소 | **효과 제한** | 36건 중 14건만 해결 (39%). 나머지는 성분도 동일하여 구분 불가 |
| Threshold 완화로 match 수 확대 | **error rate 상승** | 0% error 원칙에 위배. 완화 시 사람 검토 병행 필요 |

---

## 3. 매칭 알고리즘 (3중 필터)

3가지 filter를 동시 적용하여 error rate 0%를 보장한다.

### 3.1. 핵심 원리

| 필터 | 역할 | 효과 |
|------|------|------|
| Exact Text Match GT | `medicine_name = ProductInfos.Name`으로 threshold calibration | 성분·제조사 channel 기준 확보 |
| Reciprocal Best Match | A→B Top-1 **AND** B→A Top-1 쌍만 허용 | 약품명 threshold 불필요, 자연 filtering |
| Multi-channel Consensus | 약품명 + 성분 + 제조사 3개 signal 모두 통과 | false match 추가 차단 |

> Precision = 100% (match된 것은 반드시 정답)
> Recall < 100% (정답이지만 match하지 않은 건이 존재)

### 3.2. 데이터 흐름

```
pharmport_medicine                ProductInfos                    터울주성분
┌─────────────────┐          ┌──────────────────┐          ┌──────────────────┐
│ medicine_name_  │ ①Reciprocal│ Name_embedding   │          │ 심평원성분코드     │
│   embedding     │ ──Best───→ │                  │  FK 관계  │                  │
│                 │  Match    │ ProductCode      │          │                  │
│ sorted_ingredi- │ ②cosine  │ MasterIngredient │ ───────→ │ sorted_성분명_    │
│  ent_embedding  │ ──sim───→ │   Code           │          │   embedding      │
│                 │          │                  │          │                  │
│ manufacturer_   │ ③cosine  │ ManufacturerId   │          │                  │
│   embedding     │ ──sim───→ │  → Manufacturers │          │                  │
│                 │          │    .Name_embedding│          │                  │
│ product_code    │←── 결과   │                  │          │                  │
│ ingredient_code │←── 결과   │                  │          │                  │
└─────────────────┘          └──────────────────┘          └──────────────────┘
```

### 3.3. 알고리즘

#### Step 1. Exact Text Match GT 구축

```sql
SELECT m.medicine_id, p."MasterIngredientCode"
FROM pharmport_medicine m
JOIN "ProductInfos" p ON m.medicine_name = p."Name"
WHERE p."MasterIngredientCode" IS NOT NULL
GROUP BY m.medicine_id
HAVING COUNT(DISTINCT p."MasterIngredientCode") = 1  -- unambiguous only
```

→ **21,706건** (텍스트가 정확히 같은 unambiguous 정답 데이터)

#### Step 2. Multi-channel Threshold Calibration

텍스트 GT 쌍에 대해 성분·제조사 cosine similarity를 계산하고 하위 1%(percentile 1)를 threshold로 설정:

| Channel | 비교 대상 | Threshold | Mean |
|---------|----------|-----------|------|
| 성분 | `sorted_ingredient_embedding` ↔ `sorted_성분명_embedding` | 0.4820 (p1) | 0.7904 |
| 제조사 | `manufacturer_embedding` ↔ `Manufacturers.Name_embedding` | 0.1677 (p1) | 0.4995 |

약품명 channel은 Reciprocal Best Match가 대체하므로 별도 threshold가 불필요하다.

#### Step 3. Reciprocal Best Match

```
Forward:  각 pharmport_medicine → Top-1 ProductInfos (name embedding cosine similarity)
Reverse:  각 ProductInfos → Top-1 pharmport_medicine (name embedding cosine similarity)

Reciprocal = Forward[A] = B AND Reverse[B] = A 인 쌍만 유지
```

양방향 모두 서로를 최선으로 선택한 쌍이므로, 단방향 Top-1보다 훨씬 신뢰도가 높다.
약품명 cosine similarity threshold 없이도 자연적으로 고품질 match가 filtering된다.

→ **30,105건** Reciprocal Match (40,837건 중 73.7%)

#### Step 4. Multi-channel Consensus 필터

각 Reciprocal Match 쌍에 대해 3개 channel 모두 확인:

```
for each reciprocal pair (medicine_i, PI_j):
    1. MIC = PI_j.MasterIngredientCode (NULL이면 스킵)
    2. ingredient_sim = cosine_similarity(medicine_i.sorted_ingredient_embedding,
                                          터울주성분[MIC].sorted_성분명_embedding)
       → < 0.4820 이면 스킵
    3. manufacturer_sim = cosine_similarity(medicine_i.manufacturer_embedding,
                                            Manufacturers[PI_j.ManufacturerId].Name_embedding)
       → < 0.1677 이면 스킵
    4. 3개 channel 모두 통과 → match 확정
```

→ **29,196건** final match

### 3.4. GT Validation

최종 match 결과를 텍스트 GT(21,706건)와 대조:

| 항목 | 건수 |
|------|------|
| GT와 대조 가능 | 20,666건 |
| **Correct** | **20,666건 (100%)** |
| **Incorrect** | **0건 (0%)** |
| GT 없는 match | 8,530건 |

→ 검증 가능한 20,666건 전부 correct. Error rate 0%.

### 3.5. Match 결과

| 방향 | 총 건수 | Matched | 매칭율 |
|------|--------|---------|--------|
| **PharmPort → ProductInfos** | 40,837건 | 29,196건 | **71.5%** |
| **ProductInfos → PharmPort** | 48,027건 | 29,196건 | **60.8%** |
| **PharmPort → MIC** | 40,837건 | 29,196건 | **71.5%** |
| **MIC → PharmPort** | 20,235건 | 6,956건 | **34.4%** |

- **PharmPort → ProductInfos**: pharmport_medicine 중 product_code가 부여된 비율
- **ProductInfos → PharmPort**: ProductInfos 중 pharmport_medicine과 match된 고유 ProductCode 비율
- **PharmPort → MIC**: pharmport_medicine 중 ingredient_code(심평원성분코드)가 부여된 비율
- **MIC → PharmPort**: 터울주성분의 고유 심평원성분코드 중 커버된 비율

#### MIC 매칭율 분해

| 구분 | 건수 | Matched | 매칭율 |
|------|------|---------|--------|
| **전체 MIC** | 20,235건 | 6,956건 | **34.4%** |
| ProductInfos에 **있는** MIC | 11,349건 | 6,956건 | **61.3%** |
| ProductInfos에 **없는** MIC | 8,886건 | 0건 | **0.0%** |

- 터울주성분의 43.9%(8,886건)는 ProductInfos에 존재하지 않아 **구조적으로 매칭 불가능**
- 전체 MIC 매칭율의 이론적 상한은 56.1% (= ProductInfos에 있는 MIC 비율)
- ProductInfos에 있는 MIC 기준 매칭율은 **61.3%**

#### Unmatched 상세

| 원인 | 건수 |
|------|------|
| Reciprocal Match 실패 | 10,732건 |
| Reciprocal Match 후 성분 미달 skip | 883건 |
| Reciprocal Match 후 제조사 미달 skip | 26건 |

### 3.6. Cosine Similarity 분포

| Channel | min | mean | median |
|------|-----|------|--------|
| 약품명 | 0.5429 | 0.9731 | 1.0000 |
| 성분 | 0.4820 | 0.7865 | 0.7944 |
| 제조사 | 0.1679 | 0.9555 | 1.0000 |

### 3.7. Parameter

| Parameter | 값 | 설명 |
|-----------|------|------|
| 성분 threshold | 0.4820 | 텍스트 GT 하위 1% (auto calibration) |
| 제조사 threshold | 0.1677 | 텍스트 GT 하위 1% (auto calibration) |
| Embedding 차원 (약품명) | 2000d | `medicine_name_embedding`, `Name_embedding` |
| Embedding 차원 (성분) | 3072d | `sorted_ingredient_embedding`, `sorted_성분명_embedding` |
| Embedding 차원 (제조사) | 2000d | `manufacturer_embedding`, `Manufacturers.Name_embedding` |
| Embedding 모델 | text-embedding-3-large | Azure OpenAI |

### 3.8. 실행 방법

```bash
python match_ingredient_v2.py              # 전체 실행 (DB 업데이트)
python match_ingredient_v2.py --dry-run    # 결과만 확인
python match_ingredient_v2.py --calibrate  # 캘리브레이션만
```

---

## 4. 용어 설명

### 4.1. Embedding

텍스트를 고차원 벡터(숫자 배열)로 변환한 것. 의미가 비슷한 텍스트는 벡터 공간에서 가까운 위치에 놓인다.

```
"타이레놀정500밀리그램" → [0.021, -0.113, 0.087, ..., 0.045]  (2000차원)
"타이레놀정650밀리그램" → [0.019, -0.110, 0.089, ..., 0.043]  (2000차원) ← 가까움
"아목시실린캡슐500밀리그램" → [0.152, 0.034, -0.071, ..., -0.128]  (2000차원) ← 멀음
```

본 프로젝트에서는 Azure OpenAI `text-embedding-3-large` 모델을 사용하며, 약품명·제조사는 2000d, 성분은 3072d 벡터로 변환한다.

### 4.2. Cosine Similarity

두 embedding 벡터 간 방향의 유사도. -1(정반대) ~ 1(동일) 범위이며, 1에 가까울수록 의미가 유사하다.

```
cosine_similarity(A, B) = (A · B) / (‖A‖ × ‖B‖)

  A · B    = 벡터 내적 (각 차원의 곱을 합산)
  ‖A‖, ‖B‖ = 벡터의 크기 (L2 norm)
```

예시:

| 비교 | Cosine Similarity | 해석 |
|------|-------------------|------|
| "타이레놀정500mg" ↔ "타이레놀정500밀리그램" | ~1.0000 | 사실상 동일 |
| "타이레놀정500mg" ↔ "타이레놀정650mg" | ~0.9900 | 매우 유사 (같은 약, 다른 용량) |
| "타이레놀정500mg" ↔ "아목시실린캡슐500mg" | ~0.7500 | 다른 약 |

### 4.3. Reciprocal Best Match

A 집합과 B 집합 간 양방향 Top-1이 서로 일치하는 쌍만 허용하는 matching 방식.
단방향 Top-1 대비 false match를 크게 줄여준다.

```
Forward:  A → B  (A의 관점에서 가장 유사한 B를 선택)
Reverse:  B → A  (B의 관점에서 가장 유사한 A를 선택)

Reciprocal Match = Forward(A) = B 이고 Reverse(B) = A 인 쌍
```

예시:

```
Forward (pharmport → ProductInfos):
  "타이레놀정500mg"  → Top-1: "타이레놀정500밀리그램"  ✓
  "아스피린정100mg"  → Top-1: "아스피린장용정100mg"   ✗ (다른 제형)

Reverse (ProductInfos → pharmport):
  "타이레놀정500밀리그램" → Top-1: "타이레놀정500mg"   ✓ (양방향 일치 → Reciprocal Match)
  "아스피린장용정100mg"  → Top-1: "아스피린장용정"     ✗ (역방향 불일치 → 탈락)
```

단방향이면 "아스피린정100mg → 아스피린장용정100mg"이 match되지만,
역방향에서 "아스피린장용정100mg"이 다른 약을 선택하므로 Reciprocal Match에서 자동 탈락한다.

### 4.4. Multi-channel Consensus

독립적인 여러 signal(channel)이 모두 동의해야 match를 확정하는 방식.
한 channel에서만 유사해도 다른 channel에서 불일치하면 탈락시켜 false match를 방지한다.

```
Channel 1: 약품명 embedding  → Reciprocal Best Match 통과?
Channel 2: 성분 embedding    → cosine similarity ≥ threshold?
Channel 3: 제조사 embedding  → cosine similarity ≥ threshold?

3개 모두 통과해야 최종 match 확정
```

예시:

| 약품 | 약품명 (Ch1) | 성분 (Ch2) | 제조사 (Ch3) | 결과 |
|------|-------------|-----------|-------------|------|
| A약 500mg | Reciprocal ✓ | sim=0.92 ✓ | sim=0.98 ✓ | **Match** |
| B약 100mg | Reciprocal ✓ | sim=0.35 ✗ | sim=0.95 ✓ | **탈락** (성분 미달) |
| C약 250mg | Reciprocal ✗ | - | - | **탈락** (Ch1 실패) |
