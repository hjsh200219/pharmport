# PharmPort 데이터베이스 ERD

## 개요

- **DB**: Azure Database for PostgreSQL (Flexible Server)
- **서버**: teoul-testpg.postgres.database.azure.com
- **데이터베이스**: teoul_pharminfo
- **테이블 수**: 9개
- **총 레코드**: 약 456,523건

---

## ERD (Mermaid)

```mermaid
erDiagram
    pharmport_medicine {
        int medicine_id PK "NOT NULL, SERIAL"
        varchar200 medicine_name UK "NOT NULL"
        varchar200 manufacturer UK "NULL"
        varchar100 color "NULL"
        text storage "NULL"
        text ingredients "NULL"
        text sorted_ingredients "NULL, 알파벳순 정렬"
        varchar100 product_code "NULL"
        varchar100 ingredient_code "NULL"
        vector ingredient_embedding "NULL"
        vector embedding "NULL"
        vector medicine_name_embedding "NULL"
        vector manufacturer_embedding "NULL"
        vector sorted_ingredient_embedding "NULL, 정렬 성분 임베딩"
        timestamptz created_at "DEFAULT CURRENT_TIMESTAMP"
    }

    pharmport_extra_text {
        int extra_text_id PK "NOT NULL, SERIAL"
        varchar31 field_type UK "NOT NULL"
        text content UK "NOT NULL"
        timestamptz created_at "DEFAULT CURRENT_TIMESTAMP"
    }

    pharmport_medicine_extra {
        int extra_id PK "NOT NULL, SERIAL"
        int medicine_id FK_UK "NOT NULL → pharmport_medicine"
        int extra_text_id FK_UK "NOT NULL → pharmport_extra_text"
        int sort_order "DEFAULT 0"
        timestamptz created_at "DEFAULT CURRENT_TIMESTAMP"
    }

    pharmport_usage_text {
        int usage_text_id PK "NOT NULL, SERIAL"
        text content UK "NOT NULL"
        timestamptz created_at "DEFAULT CURRENT_TIMESTAMP"
    }

    pharmport_medicine_usage {
        int usage_id PK "NOT NULL, SERIAL"
        int medicine_id FK_UK "NOT NULL → pharmport_medicine"
        int usage_text_id FK_UK "NOT NULL → pharmport_usage_text"
        int sort_order "DEFAULT 0"
        timestamptz created_at "DEFAULT CURRENT_TIMESTAMP"
    }

    pharmport_비교 {
        int id PK "NOT NULL, SERIAL"
        text 팜포트_의약품명 "NOT NULL"
        text 팜포트_성분 "NOT NULL"
        vector 팜포트_성분_embedding "NULL"
        timestamptz created_at "DEFAULT CURRENT_TIMESTAMP"
    }

    ProductInfos {
        varchar450 ProductCode UK "NOT NULL"
        varchar450 EdiCode "NULL"
        varchar450 ItemStandardCode "NULL"
        int ManufacturerId "NOT NULL"
        varchar450 AtcCode "NULL"
        varchar450 Name "NULL"
        int BrandId "NULL"
        text MasterIngredientCode "NULL"
        text IngredientCode "NULL"
        text DosageForm "NULL"
        text DosageFormName "NULL"
        text Unit "NULL"
        text Standard "NULL"
        text Type "NULL"
        text CoverType "NULL"
        vector Name_embedding "NULL"
        timestamp CreationDateTime "NOT NULL"
        timestamp ModificationDate "NOT NULL"
        text ModifiedBy "NULL"
    }

    터울주성분 {
        varchar450 심평원성분코드 PK "NOT NULL"
        int 약품분류ID "NULL"
        int 약효설명ID "NULL"
        text 성분명 "NULL"
        text sorted_성분명 "NULL, 알파벳순 정렬"
        text 성분명한글 "NULL"
        text 고갈영양소영문 "NULL"
        vector 성분명_임베딩 "NULL"
        vector sorted_성분명_embedding "NULL, 정렬 성분명 임베딩"
        boolean IsDeleted "NOT NULL"
        timestamp 등록일 "NOT NULL"
        timestamp 수정일 "NOT NULL"
        text ModifiedBy "NULL"
    }

    Manufacturers {
        int ManufacturerID PK "NOT NULL"
        varchar450 Name "NULL"
        timestamp ModificationDate "NOT NULL"
        timestamp CreationDate "NOT NULL"
        text Url "NULL"
        vector Name_embedding "NULL"
    }

    pharmport_medicine ||--o{ pharmport_medicine_extra : "medicine_id"
    pharmport_extra_text ||--o{ pharmport_medicine_extra : "extra_text_id"
    pharmport_medicine ||--o{ pharmport_medicine_usage : "medicine_id"
    pharmport_usage_text ||--o{ pharmport_medicine_usage : "usage_text_id"
    Manufacturers ||--o{ ProductInfos : "ManufacturerId"
```

---

## 테이블 관계 설명

### FK 제약조건 (확인됨)

| 자식 테이블 | 컬럼 | → | 부모 테이블 | 컬럼 |
|---|---|---|---|---|
| `pharmport_medicine_extra` | `medicine_id` | → | `pharmport_medicine` | `medicine_id` |
| `pharmport_medicine_extra` | `extra_text_id` | → | `pharmport_extra_text` | `extra_text_id` |
| `pharmport_medicine_usage` | `medicine_id` | → | `pharmport_medicine` | `medicine_id` |
| `pharmport_medicine_usage` | `usage_text_id` | → | `pharmport_usage_text` | `usage_text_id` |

### 논리적 관계 (FK 미설정, 컬럼명 기반 추정)

| 테이블 | 컬럼 | 관련 가능 테이블 | 설명 |
|---|---|---|---|
| `pharmport_비교` | `팜포트_의약품명` | `pharmport_medicine.medicine_name` | 의약품명 텍스트 매칭 |
| `ProductInfos` | `ProductCode` | `pharmport_medicine.product_code` | 약품코드 기반 매칭 |
| `ProductInfos` | `ManufacturerId` | `Manufacturers.ManufacturerID` | 제조사 ID 매칭 |
| `터울주성분` | `심평원성분코드` | `pharmport_medicine.ingredient_code` | 성분코드 기반 매칭 |

---

## 테이블별 상세

### 1. `pharmport_medicine` (의약품 마스터) — 40,837건

핵심 테이블. 의약품 기본 정보와 벡터 임베딩 4개를 포함.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `medicine_id` | int (SERIAL) | PK | 의약품 고유 ID |
| `medicine_name` | varchar(200) | NOT NULL, UNIQUE | 의약품명 |
| `manufacturer` | varchar(200) | UNIQUE | 제조사 |
| `color` | varchar(100) | | 색상 |
| `storage` | text | | 보관 방법 |
| `ingredients` | text | | 성분 정보 |
| `product_code` | varchar(100) | | 제품 코드 |
| `ingredient_code` | varchar(100) | | 성분 코드 |
| `sorted_ingredients` | text | | 알파벳순 정렬된 성분 (40,836건) |
| `ingredient_embedding` | vector(3072) | | 성분 임베딩 |
| `embedding` | vector | | 통합 임베딩 |
| `medicine_name_embedding` | vector | | 의약품명 임베딩 |
| `manufacturer_embedding` | vector | | 제조사 임베딩 |
| `sorted_ingredient_embedding` | vector(3072) | | 정렬 성분 임베딩 (40,836건) |
| `created_at` | timestamptz | | 생성일시 |

### 2. `pharmport_extra_text` (부가 텍스트) — 22,964건

의약품 부가 정보 텍스트 원본. field_type으로 종류 구분.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `extra_text_id` | int (SERIAL) | PK | 부가 텍스트 ID |
| `field_type` | varchar(31) | NOT NULL, UNIQUE | 항목 유형 |
| `content` | text | NOT NULL, UNIQUE | 텍스트 내용 |
| `created_at` | timestamptz | | 생성일시 |

### 3. `pharmport_medicine_extra` (의약품-부가정보 매핑) — 175,046건

의약품과 부가 텍스트를 N:M 연결하는 중간 테이블.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `extra_id` | int (SERIAL) | PK | 매핑 ID |
| `medicine_id` | int | FK → `pharmport_medicine` | 의약품 ID |
| `extra_text_id` | int | FK → `pharmport_extra_text` | 부가 텍스트 ID |
| `sort_order` | int | DEFAULT 0 | 정렬 순서 |
| `created_at` | timestamptz | | 생성일시 |

### 4. `pharmport_usage_text` (용법용량 텍스트) — 9,772건

용법용량 텍스트 원본.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `usage_text_id` | int (SERIAL) | PK | 용법 텍스트 ID |
| `content` | text | NOT NULL, UNIQUE | 용법용량 내용 |
| `created_at` | timestamptz | | 생성일시 |

### 5. `pharmport_medicine_usage` (의약품-용법 매핑) — 72,693건

의약품과 용법용량 텍스트를 N:M 연결하는 중간 테이블.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `usage_id` | int (SERIAL) | PK | 매핑 ID |
| `medicine_id` | int | FK → `pharmport_medicine` | 의약품 ID |
| `usage_text_id` | int | FK → `pharmport_usage_text` | 용법 텍스트 ID |
| `sort_order` | int | DEFAULT 0 | 정렬 순서 |
| `created_at` | timestamptz | | 생성일시 |

### 6. `pharmport_비교` (의약품 비교) — 66,290건

의약품 비교 데이터. 성분 임베딩 포함.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | int (SERIAL) | PK | 비교 ID |
| `팜포트_의약품명` | text | NOT NULL | 의약품명 |
| `팜포트_성분` | text | NOT NULL | 성분 정보 |
| `팜포트_성분_embedding` | vector | | 성분 임베딩 |
| `created_at` | timestamptz | | 생성일시 |

### 7. `ProductInfos` (제품 정보) — 48,027건

약품 제품 상세 정보. 식별 표시, 이미지, 성분코드 등 포함 (50개 컬럼).

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `ProductCode` | varchar(450) | UNIQUE | 제품 코드 |
| `EdiCode` | varchar(450) | | EDI 코드 |
| `ItemStandardCode` | varchar(450) | | 품목기준코드 |
| `ManufacturerId` | int | NOT NULL | 제조사 ID |
| `AtcCode` | varchar(450) | | ATC 분류코드 |
| `Name` | varchar(450) | | 제품명 |
| `BrandId` | int | | 브랜드 ID |
| `MasterIngredientCode` | text | | 주성분코드 |
| `IngredientCode` | text | | 성분코드 |
| `IngredientCodeWithoutStrength` | text | | 함량 제외 성분코드 |
| `MfdsCode` | text | | 식약처 코드 |
| `DosageForm` | text | | 제형 코드 |
| `DosageFormName` | text | | 제형명 |
| `Unit` | text | | 단위 |
| `Standard` | text | | 규격 |
| `Type` | text | | 유형 |
| `CoverType` | text | | 급여 유형 |
| `색상앞` / `색상뒤` | text | | 알약 앞/뒤 색상 |
| `표시앞` / `표시뒤` | text | | 알약 앞/뒤 표시 |
| `식별표시코드앞` / `식별표시코드뒤` | text | | 식별 표시 코드 |
| `약품장축길이` / `약품단축길이` | text | | 알약 크기 |
| `Name_embedding` | vector | | 제품명 임베딩 |
| `CreationDateTime` | timestamp | NOT NULL | 생성일시 |
| `ModificationDate` | timestamp | NOT NULL | 수정일시 |
| `ModifiedBy` | text | | 수정자 |

### 8. `Manufacturers` (제조사 마스터) — 659건

제조사 기본 정보. Name 임베딩 포함.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `ManufacturerID` | int | PK | 제조사 고유 ID |
| `Name` | varchar(450) | | 제조사명 |
| `ModificationDate` | timestamp | NOT NULL | 수정일시 |
| `CreationDate` | timestamp | NOT NULL | 생성일시 |
| `Url` | text | | 제조사 웹사이트 URL |
| `Name_embedding` | vector | | 제조사명 임베딩 |

### 9. `터울주성분` (주성분 마스터) — 20,235건

심평원 기준 주성분 정보. 성분명 임베딩 포함.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `심평원성분코드` | varchar(450) | PK | 심평원 성분 코드 |
| `약품분류ID` | int | | 약품 분류 ID |
| `약효설명ID` | int | | 약효 설명 ID |
| `성분명` | text | | 성분명 (영문) |
| `sorted_성분명` | text | | 알파벳순 정렬된 성분명 (19,972건) |
| `성분명한글` | text | | 성분명 (한글) |
| `고갈영양소영문` | text | | 고갈 영양소 (영문) |
| `성분명_임베딩` | vector | | 성분명 임베딩 |
| `sorted_성분명_embedding` | vector(3072) | | 정렬 성분명 임베딩 (19,972건) |
| `IsDeleted` | boolean | NOT NULL | 삭제 여부 |
| `등록일` | timestamp | NOT NULL | 등록일 |
| `수정일` | timestamp | NOT NULL | 수정일 |
| `ModifiedBy` | text | | 수정자 |

---

## 레코드 현황

| 테이블 | 건수 | 역할 |
|---|---|---|
| `pharmport_medicine` | 40,837 | 의약품 마스터 |
| `pharmport_medicine_extra` | 175,046 | 의약품↔부가정보 매핑 |
| `pharmport_medicine_usage` | 72,693 | 의약품↔용법 매핑 |
| `pharmport_비교` | 66,290 | 의약품 비교 데이터 |
| `ProductInfos` | 48,027 | 제품 정보 |
| `pharmport_extra_text` | 22,964 | 부가 텍스트 원본 |
| `터울주성분` | 20,235 | 주성분 마스터 |
| `pharmport_usage_text` | 9,772 | 용법용량 텍스트 원본 |
| `Manufacturers` | 659 | 제조사 마스터 |

---

## 성분 정렬 임베딩 (sorted embedding)

두 테이블의 성분 텍스트를 **콤마 기준 알파벳순 정렬 → Azure text-embedding-3-large로 임베딩**하여 비교 가능하도록 처리.

### 목적

`pharmport_medicine.ingredients`와 `터울주성분.성분명`의 성분 순서가 다를 수 있으므로, 정렬 후 임베딩하여 코사인 유사도로 비교.

### 처리 흐름

```
원본 텍스트 (ingredients / 성분명)
  → 콤마로 분리 (괄호 내부 콤마 무시)
  → 알파벳순 정렬
  → sorted_ingredients / sorted_성분명 컬럼에 저장
  → Azure text-embedding-3-large (vector 3072차원)
  → sorted_ingredient_embedding / sorted_성분명_embedding 컬럼에 저장
```

### 추가된 컬럼

| 테이블 | 컬럼 | 타입 | 건수 |
|---|---|---|---|
| `pharmport_medicine` | `sorted_ingredients` | text | 40,836건 |
| `pharmport_medicine` | `sorted_ingredient_embedding` | vector(3072) | 40,836건 |
| `터울주성분` | `sorted_성분명` | text | 19,972건 |
| `터울주성분` | `sorted_성분명_embedding` | vector(3072) | 19,972건 |

### 실행 스크립트

- `sort_and_embed.py` — 정렬 + 임베딩 + DB 저장 (이미 처리된 건은 건너뜀)
- `embedding_service.py` — Azure OpenAI 임베딩 API 호출 + 성분 정렬 로직

---

## 심평원성분코드 매칭 (에러율 0%)

`pharmport_medicine` → `심평원성분코드` 매칭. 결과를 `product_code`, `ingredient_code` 컬럼에 저장.

### 현재 적용: Method 2 (GT-독립, 3중 필터)

코드 체인에 의존하지 않는 자립형 매칭. 3가지 필터 동시 적용:

1. **텍스트 완전 일치 GT**: `medicine_name = ProductInfos.Name`으로 캘리브레이션 (21,706건)
2. **상호 최적 매칭**: A→B Top-1 AND B→A Top-1 (약품명 임베딩)
3. **다중 채널 합의**: 약품명 + 성분 + 제조사 3채널 모두 통과

### 매칭 결과

| 항목 | 건수 | 비율 |
|------|------|------|
| pharmport_medicine 총 | 40,837건 | 100% |
| **매칭 성공** | **29,196건** | **71.5%** |
| 터울주성분 총 | 20,235건 | 100% |
| **커버된 심평원성분코드** | **6,956건** | **34.4%** |
| 텍스트 GT 검증 정확도 | 20,666건 중 | **100%** |

### 실행 스크립트

- `match_ingredient_v2.py` — Method 2 매칭 (현재 적용)
- `match_ingredient.py` — Method 1 매칭 (단일 채널, 코드체인 GT 의존)
- 상세 방법론: `methodology.md` 참조
