# 의약품-성분코드 매칭 플랜 v2

> **RALPLAN Iteration 2** — Architect/Critic 피드백 전수 반영  
> 생성일: 2026-03-16

---

## RALPLAN-DR 요약

### 원칙 (Principles)

1. **Ground Truth 우선**: product_code → ProductInfos → MasterIngredientCode 체인이 가장 신뢰할 수 있는 매칭 경로. 이 경로를 1순위로 사용하고, 나머지는 보완 수단으로만 사용.
2. **점진적 검증 (Incremental Validation)**: Stage 1+2 결과를 평가한 뒤 Stage 3 필요성을 데이터 기반으로 결정. 미리 과도하게 구현하지 않음 (YAGNI).
3. **측정 가능한 품질**: 모든 단계에 pass/fail 기준을 수치로 정의. "대략 좋다"가 아닌 precision ≥ X% 로 판단.
4. **미매칭 투명성**: 매칭 실패건은 삭제하지 않고 `manual_review` 플래그로 별도 관리하여 추적 가능하게 유지.

### 핵심 결정 동인 (Decision Drivers)

| 순위 | 동인 | 이유 |
|------|------|------|
| 1 | **매칭 정확도** | 의약품-성분코드 매칭 오류는 환자 안전에 직결 |
| 2 | **구현 단순성** | 파이썬 스크립트 4개 + SQL만으로 완결되어야 함 |
| 3 | **검증 가능성** | 자동 메트릭 + 수동 샘플링으로 이중 검증 |

### 옵션 비교

#### 옵션 A: 코드 체인 → sorted 임베딩 (3072d) 폴백 ✅ 채택

| 항목 | 내용 |
|------|------|
| **전략** | Stage 1 (코드 체인 19,841건) → Stage 2 (3072d sorted 임베딩 폴백 ~20,983건) → Stage 3 (교차 검증, 필요시) |
| **장점** | Ground Truth 최대 활용, 정렬 임베딩으로 순서 불변 매칭, 기존 인프라 활용 |
| **단점** | sorted_embedding에 HNSW 인덱스 필요 (1회 생성 비용) |
| **예상 커버리지** | 90-95% (Stage 1: ~49% + Stage 2: ~41-46%) |

#### 옵션 B: 코드 체인 → 혼합 임베딩 (2000d 이름 + 3072d 성분) 폴백

| 항목 | 내용 |
|------|------|
| **전략** | Stage 1 동일 → Stage 2에서 medicine_name_embedding(2000d)과 sorted_ingredient_embedding(3072d)을 가중 합산 |
| **장점** | 이름 유사성까지 반영하여 동명이약 구분 가능성 |
| **단점** | 차원이 다른 벡터 합산 로직이 복잡, 가중치 튜닝 필요, 기존 인덱스 재활용 불가 (복합 쿼리), 성분 정렬 임베딩 단독 대비 정확도 이점 불명확 |
| **예상 커버리지** | 90-95% (유사하나 복잡도 대비 이점 불명확) |

#### 옵션 B의 불채택 사유

- 3072d sorted 임베딩은 성분 순서를 정규화하여 이미 높은 정확도 기대
- 2000d 이름 임베딩 추가는 복잡도 대비 한계 개선만 제공
- 가중치 최적화가 추가 작업으로 필요하며 KISS 원칙 위반
- **단, Stage 2 정확도가 목표 미달 시 옵션 B로 전환하는 것을 Stage 3에서 고려** (ADR 참조)

---

## ADR (Architecture Decision Record)

| 항목 | 내용 |
|------|------|
| **결정** | 코드 체인 1순위 + sorted 임베딩(3072d) 폴백 2순위, 2단계 매칭 |
| **핵심 동인** | 정확도 우선 + 구현 단순성 + sorted 임베딩이 이미 양 테이블에 생성 완료 |
| **고려한 대안** | (A) 본안, (B) 혼합 차원 임베딩, (C) Stage 4 수동 매칭 UI (YAGNI로 제거) |
| **채택 이유** | 1:1 코드 체인이 48.6%를 확정적으로 커버, 3072d sorted 임베딩이 나머지를 충분히 보완 |
| **결과** | HNSW 인덱스 2개 신규 생성 필요, manual_review 테이블 추가 |
| **후속 조치** | Stage 2 precision < 90% 시 옵션 B 또는 medicine_name 임베딩 cross-validation 추가 검토 |

---

## 구현 단계

### Stage 0: 인프라 준비 (HNSW 인덱스 생성)

**파일**: `create_indexes.py`

**작업 내용**:
1. `pharmport_medicine.sorted_ingredient_embedding`에 HNSW 인덱스 생성
2. `터울주성분.sorted_성분명_embedding`에 HNSW 인덱스 생성
3. 매칭 결과 저장용 테이블 `pharmport_ingredient_match` 생성

**SQL 상세**:
```sql
-- 인덱스 생성 (cosine distance)
CREATE INDEX CONCURRENTLY ix_pharmport_medicine_sorted_ingredient_embedding
  ON pharmport_medicine
  USING hnsw (sorted_ingredient_embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX CONCURRENTLY ix_터울주성분_sorted_성분명_embedding
  ON "터울주성분"
  USING hnsw ("sorted_성분명_embedding" vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- 결과 테이블
CREATE TABLE IF NOT EXISTS pharmport_ingredient_match (
  match_id SERIAL PRIMARY KEY,
  medicine_id INT NOT NULL REFERENCES pharmport_medicine(medicine_id),
  심평원성분코드 VARCHAR(450),
  match_method VARCHAR(20) NOT NULL,  -- 'code_chain' | 'embedding'
  confidence FLOAT,                    -- 코사인 유사도 (code_chain은 1.0)
  manual_review BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(medicine_id)
);
```

**수용 기준**:
- [ ] 두 HNSW 인덱스가 `\di+`로 확인됨
- [ ] `pharmport_ingredient_match` 테이블 생성 확인
- [ ] 인덱스 생성 후 `EXPLAIN ANALYZE`로 벡터 검색이 Index Scan 사용 확인

---

### Stage 1: 코드 체인 매칭 (확정적 매칭)

**파일**: `match_by_code.py`

**매칭 로직**:
```
pharmport_medicine.product_code
  → ProductInfos.ProductCode
  → ProductInfos.MasterIngredientCode
  → 터울주성분.심평원성분코드
```

**SQL 핵심 쿼리**:
```sql
INSERT INTO pharmport_ingredient_match (medicine_id, 심평원성분코드, match_method, confidence)
SELECT
  m.medicine_id,
  p."MasterIngredientCode" AS 심평원성분코드,
  'code_chain' AS match_method,
  1.0 AS confidence
FROM pharmport_medicine m
JOIN "ProductInfos" p ON m.product_code = p."ProductCode"
JOIN "터울주성분" t ON p."MasterIngredientCode" = t."심평원성분코드"
WHERE m.product_code IS NOT NULL
  AND p."MasterIngredientCode" IS NOT NULL
ON CONFLICT (medicine_id) DO NOTHING;
```

**예상 결과**: ~19,841건 매칭 (전체 40,837건 중 48.6%)

**수용 기준**:
- [ ] 매칭 건수 ≥ 19,000건 (code_chain)
- [ ] 무작위 50건 수동 검증 시 precision = 100% (코드 체인이므로 확정적)
- [ ] `match_method = 'code_chain'`인 전건의 `심평원성분코드`가 `터울주성분` 테이블에 존재

**수동 검증 방법**:
```sql
-- 무작위 50건 추출
SELECT m.medicine_name, m.ingredients, m.product_code,
       t."성분명", t."성분명한글", t."심평원성분코드"
FROM pharmport_ingredient_match im
JOIN pharmport_medicine m ON im.medicine_id = m.medicine_id
JOIN "터울주성분" t ON im."심평원성분코드" = t."심평원성분코드"
WHERE im.match_method = 'code_chain'
ORDER BY RANDOM() LIMIT 50;
```
→ 결과를 CSV로 추출하여 성분명 일치 여부를 육안 확인

---

### Stage 2: Sorted 임베딩 폴백 매칭

**파일**: `match_by_embedding.py`

**대상**: Stage 1에서 매칭되지 않은 ~20,996건

**매칭 로직**:
```sql
-- Stage 1 미매칭건 각각에 대해
SELECT t."심평원성분코드",
       1 - (m.sorted_ingredient_embedding <=> t."sorted_성분명_embedding") AS similarity
FROM pharmport_medicine m,
     "터울주성분" t
WHERE m.medicine_id = :medicine_id
  AND m.sorted_ingredient_embedding IS NOT NULL
  AND t."sorted_성분명_embedding" IS NOT NULL
ORDER BY m.sorted_ingredient_embedding <=> t."sorted_성분명_embedding"
LIMIT 1;
```

**임계값 전략**:
| 유사도 범위 | 처리 |
|-------------|------|
| ≥ 0.95 | 자동 매칭 (high confidence) |
| 0.85 ~ 0.95 | 매칭하되 `manual_review = TRUE` |
| < 0.85 | 미매칭, `manual_review = TRUE`, `심평원성분코드 = NULL` |

**배치 처리**: 1,000건씩 커밋 (대량 처리 안정성)

**예상 결과**:
- 자동 매칭 (≥0.95): ~14,000-17,000건 (67-81%)
- 리뷰 필요 (0.85-0.95): ~2,000-4,000건
- 미매칭 (<0.85): ~1,000-3,000건

**수용 기준**:
- [ ] 유사도 ≥ 0.95 구간 무작위 50건 수동 검증 precision ≥ 95%
- [ ] 유사도 0.85-0.95 구간 무작위 50건 수동 검증 precision ≥ 80%
- [ ] 전체 커버리지 (Stage 1 + Stage 2 자동매칭) ≥ 85%
- [ ] `manual_review = TRUE`인 건이 모두 정확히 플래깅됨

**수동 검증 방법**:
```sql
-- 고신뢰 구간 50건
SELECT m.medicine_name, m.sorted_ingredients,
       t."sorted_성분명", t."성분명한글",
       im.confidence
FROM pharmport_ingredient_match im
JOIN pharmport_medicine m ON im.medicine_id = m.medicine_id
JOIN "터울주성분" t ON im."심평원성분코드" = t."심평원성분코드"
WHERE im.match_method = 'embedding' AND im.confidence >= 0.95
ORDER BY RANDOM() LIMIT 50;

-- 중간 구간 50건
-- (동일 쿼리, WHERE 조건만 confidence BETWEEN 0.85 AND 0.95)
```

---

### Stage 3: 교차 검증 (Cross-Validation) — 조건부 실행

> **실행 조건**: Stage 2 precision이 목표 미달일 때만 실행

**파일**: `cross_validate.py`

**목적**: Stage 2 매칭 결과의 신뢰도를 medicine_name ↔ ProductInfos.Name 임베딩(2000d)으로 교차 검증

**로직**:
```
Stage 2에서 매칭된 (medicine_id, 심평원성분코드) 쌍에 대해:
1. 심평원성분코드 → ProductInfos.MasterIngredientCode로 역추적
2. ProductInfos.Name_embedding과 medicine_name_embedding의 유사도 계산
3. 성분 유사도와 이름 유사도가 모두 높으면 신뢰도 상향
4. 불일치(성분 유사 but 이름 불일치)건 → manual_review = TRUE로 전환
```

**주의**: 독립적 매칭 경로가 아닌, Stage 2 결과를 **검증**하는 보조 수단

**수용 기준**:
- [ ] 교차 검증으로 재분류된 건수 리포트 출력
- [ ] 재분류 후 precision 변화율 측정 가능

---

### Validation: 통합 검증

**파일**: `validate_matching.py`

**검증 메트릭 및 쿼리**:

#### 1. 커버리지 메트릭
```sql
-- 전체 커버리지
SELECT
  COUNT(*) AS total_medicines,
  COUNT(im.match_id) AS matched,
  COUNT(*) - COUNT(im.match_id) AS unmatched,
  ROUND(COUNT(im.match_id)::numeric / COUNT(*)::numeric * 100, 2) AS coverage_pct
FROM pharmport_medicine m
LEFT JOIN pharmport_ingredient_match im ON m.medicine_id = im.medicine_id
WHERE im."심평원성분코드" IS NOT NULL;
```

#### 2. 방법별 분포
```sql
SELECT match_method,
       COUNT(*) AS cnt,
       ROUND(AVG(confidence)::numeric, 4) AS avg_confidence,
       MIN(confidence) AS min_confidence
FROM pharmport_ingredient_match
WHERE "심평원성분코드" IS NOT NULL
GROUP BY match_method;
```

#### 3. 신뢰도 분포 히스토그램
```sql
SELECT
  CASE
    WHEN confidence >= 0.99 THEN '0.99-1.00'
    WHEN confidence >= 0.95 THEN '0.95-0.99'
    WHEN confidence >= 0.90 THEN '0.90-0.95'
    WHEN confidence >= 0.85 THEN '0.85-0.90'
    ELSE '<0.85'
  END AS confidence_band,
  COUNT(*) AS cnt
FROM pharmport_ingredient_match
GROUP BY 1 ORDER BY 1 DESC;
```

#### 4. Stage 1↔2 교차 검증 (일관성)
```sql
-- Stage 1 매칭건 중 sorted 임베딩 유사도도 높은지 확인
SELECT
  COUNT(*) AS total_code_chain,
  COUNT(*) FILTER (WHERE 1 - (m.sorted_ingredient_embedding <=> t."sorted_성분명_embedding") >= 0.90) AS also_high_embedding,
  ROUND(
    COUNT(*) FILTER (WHERE 1 - (m.sorted_ingredient_embedding <=> t."sorted_성분명_embedding") >= 0.90)::numeric
    / COUNT(*)::numeric * 100, 2
  ) AS consistency_pct
FROM pharmport_ingredient_match im
JOIN pharmport_medicine m ON im.medicine_id = m.medicine_id
JOIN "터울주성분" t ON im."심평원성분코드" = t."심평원성분코드"
WHERE im.match_method = 'code_chain'
  AND m.sorted_ingredient_embedding IS NOT NULL
  AND t."sorted_성분명_embedding" IS NOT NULL;
```

#### 5. Manual Review 통계
```sql
SELECT manual_review, COUNT(*) AS cnt
FROM pharmport_ingredient_match
GROUP BY manual_review;
```

**Pass/Fail 기준 (구체적)**:

| 메트릭 | Pass 기준 | Fail 시 조치 |
|--------|-----------|-------------|
| 전체 커버리지 (매칭 성공률) | ≥ 85% | Stage 3 교차 검증 실행 또는 임계값 조정 |
| Stage 1 precision (수동 50건) | = 100% | 코드 체인 로직 버그 확인 |
| Stage 2 precision ≥0.95 (수동 50건) | ≥ 95% | 임계값 상향 (0.97) |
| Stage 2 precision 0.85-0.95 (수동 50건) | ≥ 80% | 해당 구간 전체 manual_review 전환 |
| Stage 1↔임베딩 일관성 | ≥ 85% | 임베딩 품질 점검 필요 |
| manual_review 비율 | ≤ 15% | 임계값 또는 임베딩 전략 재검토 |

**출력**: JSON 리포트 + 콘솔 summary

---

## 파일 구조

```
pharmport/
├── common.py                  # (기존) DB 연결
├── embedding_service.py       # (기존) 임베딩 서비스
├── sort_and_embed.py          # (기존) 정렬+임베딩
├── create_indexes.py          # [신규] Stage 0: 인덱스 + 테이블 생성
├── match_by_code.py           # [신규] Stage 1: 코드 체인 매칭
├── match_by_embedding.py      # [신규] Stage 2: 임베딩 폴백 매칭
├── cross_validate.py          # [신규] Stage 3: 교차 검증 (조건부)
├── validate_matching.py       # [신규] 통합 검증 스크립트
└── .omc/plans/
    └── ingredient-matching-v2.md  # 본 플랜
```

총 **신규 파일 5개**, 기존 파일 수정 **0개**

---

## 실행 순서

```
1. python create_indexes.py          # ~5-10분 (HNSW 인덱스 빌드)
2. python match_by_code.py           # ~1분 (SQL JOIN)
3. python validate_matching.py --stage 1  # Stage 1 검증
4. python match_by_embedding.py      # ~10-30분 (벡터 검색)
5. python validate_matching.py       # 전체 검증
6. [조건부] python cross_validate.py # Stage 2 precision 미달 시만
```

---

## 정량 예측

| 항목 | 예측값 | 근거 |
|------|--------|------|
| Stage 1 매칭 건수 | 19,841건 (±100) | product_code JOIN 실측 기반 |
| Stage 1 precision | 100% | 코드 체인 (확정적 매칭) |
| Stage 2 대상 건수 | ~20,996건 | 40,837 - 19,841 |
| Stage 2 자동매칭 (≥0.95) | 14,000-17,000건 | sorted 임베딩 유사도 분포 추정 |
| Stage 2 precision (≥0.95) | 95-99% | 정렬 임베딩의 성분 순서 정규화 효과 |
| 전체 커버리지 | 88-93% | (19,841 + 16,000) / 40,837 |
| manual_review 건수 | 2,000-5,000건 | 중간/미매칭 합산 |

---

## Architect/Critic 피드백 반영 매핑

| 피드백 | 반영 위치 |
|--------|----------|
| Stage 1+2 우선, 결과 평가 후 Stage 3 결정 | Stage 3에 "조건부 실행" 명시 |
| Stage 3을 cross-validation으로 재정의 | Stage 3 목적을 "교차 검증"으로 변경 |
| Stage 4 제거 (YAGNI) | 제거 완료 |
| manual_review 플래그 | 결과 테이블에 `manual_review BOOLEAN` 추가 |
| HNSW 인덱스 생성 단계 추가 | Stage 0으로 명시 |
| Stage 3이 "Ground Truth 우선"에 모순 | cross-validation으로 재정의하여 원칙 일관성 확보 |
| 옵션 B 공정 평가 | RALPLAN-DR에 장단점 비교 + 불채택 사유 명시 |
| 수용 기준 테스트 가능하게 | Pass/Fail 표로 구체적 수치 제시 |
| validate_matching.py 구체화 | 5개 SQL 쿼리 + 메트릭 명시 |
| 수동 샘플링 검증 포함 | Stage별 50건 수동 검증 쿼리 + 방법 명시 |
