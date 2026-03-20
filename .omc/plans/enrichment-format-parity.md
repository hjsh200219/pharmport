# PharmPort Enrichment First + Format Parity 계획

> **RALPLAN-DR Iteration 11** — 호환 뷰 + 이중언어 전략 + field_type 매핑 + Enrichment 프로파일 기반 복약안내 재활용 아키텍처
> 생성일: 2026-03-19
> 최종 수정: 2026-03-20 (Iteration 11 — Critic Re-Review 반영: 호환 뷰 DDL(Principle #8 보장), field_type→section_type 매핑, edb_content_block deprecated, English-first 이중언어 전략)
> 상태: 사용자 확인 대기
> 선행 계획: `ingredient-matching-v2.md` (완료), `unmatched-recovery.md` (진행중/계획 수립 완료)

---

## 목차

| # | 섹션 | 설명 |
|---|------|------|
| — | [RALPLAN-DR 요약](#ralplan-dr-요약) | 설계 원칙, 의사결정 요인, 옵션 비교, ADR |
| 1 | [활용 데이터 소스 인벤토리](#1-활용-데이터-소스-인벤토리) | 내부 DB, 외부 API, 인프라 서비스 전체 목록 |
| 2 | [환경변수 활용 전략](#2-환경변수-활용-전략-env) | .env 기존/신규 환경변수 정리 |
| 3 | [신규 DB 스키마 설계](#3-신규-db-스키마-설계) | 별도 DB(teoul_pharminfo_v2) + 동일 테이블명 아키텍처 |
| 3.1 | [Enrichment 데이터 테이블](#31-enrichment-데이터-테이블-phase-1-기존-db) | edb_ 테이블 9개 DDL (기존 DB에 생성) |
| 3.2 | [프로파일 시스템 테이블](#32-프로파일-시스템-테이블-신규-db) | 터울복약프로파일 + profile_type/constituent_hash/needs_regeneration, 터울복합프로파일구성, 매핑 테이블 DDL |
| 3.3 | [복약안내 테이블](#33-복약안내-테이블-신규-db) | 터울복약안내A4/A5, 터울텍스트그램 DDL |
| 3.4 | [터울주성분 확장 테이블](#34-터울주성분-확장-테이블-신규-db) | 기존 컬럼 + enrichment + 프로파일 연결 (신규 DB의 `터울주성분`) |
| 3.5 | [DB 분리 아키텍처 + 테이블 관계](#35-db-분리-아키텍처--테이블-관계) | 기존 DB ↔ 신규 DB 구조 + 프로파일 기반 관계 |
| 3.6 | [심평원성분코드 구조와 API 호출 최적화](#36-심평원성분코드-구조와-api-호출-최적화) | 9자리 코드 구조, API 절감 전략 |
| 3.7 | [호환 뷰 정의](#37-호환-뷰-정의-compatibility-views) | Principle #8 보장: 터울주성분A4/A5복약안내매핑 호환 VIEW, 호환 컬럼, 시간제한 |
| 4 | [Phase 1: Enrichment 파이프라인](#4-phase-1-enrichment-파이프라인) | Step 1~8 외부 데이터 수집 |
| 4.9 | [Phase 1.5: 프로파일 클러스터링](#49-phase-15-프로파일-클러스터링) | Enrichment 결과 해싱 → 프로파일 생성 → **단일제(Step A)/복합제 5-tier(Step B)** 분기 → 성분 그룹핑 |
| 5 | [Phase 2: Format Parity](#5-phase-2-format-parity) | 프로파일 단위 LLM 생성 + A4/A5 포맷 + 출력 |
| 5.1 | [커버리지 + 정확도 리포트](#51-enrichment-커버리지--정확도-리포트-phase-2-진입-조건) | Phase 2 게이트 조건 |
| 5.2 | [복약안내 문장 생성 원칙](#52-복약안내-문장-생성-원칙-why--what--who) | "Why + What + Who" 원칙 |
| 5.2.0 | [이중 언어 생성 전략](#520-이중-언어-생성-전략-bilingual-generation-strategy) | English-first → DeepL 한글 번역 → LLM 보정 |
| 5.2.1 | [field_type → section_type 매핑](#521-pharmport-field_type--edb-section_type-매핑) | 기존 3종 → 신규 6종 개념적 매핑 |
| 5.3 | [A5 간략 포맷](#53-a5-간략-포맷-컨텐츠-구조) | badge + [약효설명] + 주의사항 1줄 |
| 5.4 | [A4 상세 포맷](#54-a4-상세-포맷-컨텐츠-구조) | [약효설명] + badge + (병원처방용법) 블록 |
| 5.5 | [분류/정렬/픽토그램](#55-분류정렬픽토그램-매핑-규칙) | 시각 요소 규칙 |
| 6 | [신규 DB 구축 및 데이터 마이그레이션](#6-신규-db-구축-및-데이터-마이그레이션) | 별도 DB 생성 + 기존 컬럼 이관 + enrichment 통합 |
| 7 | [단계별 로드맵](#7-단계별-로드맵) | Phase 0~2B 일정 |
| 8 | [4-Layer Validation Architecture](#8-4-layer-validation-architecture-품질-보증) | 자동/수동 검증 4단계 |
| 9 | [신규 주성분코드 자동 Enrichment](#9-신규-주성분코드-자동-enrichment-flow) | CASE A/B/C 분기 처리 |
| 10 | [파일 구조](#10-파일-구조) | 신규 15개 / 기존 파일 목록 |
| 11 | [예상 수치 요약](#11-예상-수치-요약) | 보수적/낙관적 추정 + LLM 호출 예상 |
| 12 | [Success Criteria](#12-success-criteria-성공-기준) | 성공 기준 27개 |
| 13 | [Guardrails](#13-guardrails) | Must Have / Must NOT Have |
| — | [Changelog](#changelog) | Iteration 2~7 변경 이력 |

---

## RALPLAN-DR 요약

### Principles (설계 원칙)

1. **안전 데이터 무오류 (Safety Data Integrity)**: 부작용, 상호작용, 금기사항, black box warning 등 환자 안전에 직결되는 데이터는 전문가 검증 없이 출력물에 포함하지 않는다. 기존 매칭 시스템의 "Zero Error 불변" 원칙을 enrichment 영역으로 확장한다. Safety 데이터는 severity 기반 risk-tiered 전문가 검증을 거쳐야 하며, 검증 미완료 데이터는 `validation_status = 'draft'`로 유지하고 출력물에서 제외한다.
2. **Enrichment First**: 출력 포맷을 먼저 설계하지 않는다. 외부 소스에서 확보 가능한 데이터의 범위와 품질을 먼저 파악한 뒤, 그 결과가 포맷 설계를 결정한다.
3. **성분 중심 지식 그래프**: `터울주성분.심평원성분코드`를 canonical key로 삼아 모든 외부 데이터를 성분 단위로 집적한다. 의약품(pharmport_medicine)은 성분에 대한 참조일 뿐, enrichment 데이터는 성분 레벨에 축적한다.
4. **점진적 가치 실현**: 20,235개 전체 성분을 한번에 처리하지 않는다. 매칭 완료 6,956개 성분부터 시작하여, 데이터 품질과 파이프라인 안정성을 확인한 뒤 확장한다.
5. **출처 투명성 (Provenance)**: 모든 enrichment 데이터에 출처(source), 조회 일자(fetched_at), 원본 ID(source_id)를 기록한다. 논문 기반 데이터는 PMID/DOI를 필수 보존한다.
6. **포맷은 데이터를 따른다**: A4/A5 출력 포맷의 섹션 구성은 Phase 1 enrichment 결과의 커버리지에 의해 결정된다. 데이터가 없는 섹션은 포맷에 포함하지 않는다.
7. **LLM 기반 복약안내 신규 생성 (기존 DB 참조 없음)**: 모든 복약안내 문구(약효설명, A4/A5 텍스트)를 **오직 enrichment 데이터만을** 기반으로 LLM이 새로 생성한다. 기존 터울약효설명/팜포트 텍스트는 LLM 프롬프트에 **일절 포함하지 않는다**. 외부 소스(ChEMBL, FDA, Open Targets, PubMed 등)에서 수집한 구조화 데이터만을 LLM에 입력하여 자연스러운 한글 복약안내를 작성한다. 결과는 신규 DB(`teoul_pharminfo_v2`)의 `터울주성분` 테이블에 저장한다.
8. **동일 테이블명 별도 DB 아키텍처**: 현재 서비스 중인 DB(`teoul_pharminfo`)의 테이블 구조(터울주성분, 터울약효설명 등)와 **동일한 테이블명**을 신규 DB(`teoul_pharminfo_v2`)에 구성한다. 앱에서는 `DATABASE_NAME` 환경변수만 변경하면 신규 DB로 전환 가능하도록 설계한다.
9. **Enrichment 프로파일 기반 복약안내 재활용**: 동일한 enrichment 수집 결과(작용기전, 부작용, 금기, 상호작용, 모니터링, 특수환자군)를 가진 성분들은 **동일한 복약안내를 공유**한다. Enrichment 결과를 해시하여 프로파일을 생성하고, 프로파일 단위로 LLM 복약안내를 1회 생성한 뒤 해당 프로파일에 속하는 모든 성분에 매핑한다. 이를 통해 (1) LLM 호출을 20,000건→1,000~3,000건으로 축소, (2) 동일 의미의 중복 문장을 구조적으로 제거, (3) 신규 성분 추가 시 기존 프로파일 매칭만으로 0회 LLM 호출 가능하다.
10. **복합제 Compound Profile 전략**: 7,791건(38.5%) 복합제를 5-tier로 분류하여 전체 커버한다. Tier 1(1성분)은 단일제 처리, Tier 2-5(2+성분)는 구성 성분의 단일제 enrichment를 재활용하되, 복합 맥락(상호작용, 복합 목적, 부작용 우선순위)을 tier별 LLM 입력 전략으로 생성한다. 동일 성분 코드 조합은 constituent_hash(성분 코드 직접 해시)로 중복 제거한다. 구성 성분 식별은 3단계 fallback(IngredientCode 파싱 → 성분명 텍스트 매칭 → base+YY 룩업)으로 수행한다.

### Decision Drivers (핵심 의사결정 요인)

| 순위 | 요인 | 이유 |
|------|------|------|
| 1 | **성분명 영문 매핑 정확도** | `터울주성분.성분명`(영문)이 외부 DB 검색의 유일한 키. 이 매핑이 부정확하면 전체 enrichment가 오염됨 |
| 2 | **외부 API 커버리지 vs 비용** | ChEMBL/Open Targets는 무료+구조화, PubMed는 무료+비구조화, 모두 rate limit 존재. 20K 성분 전수 조회의 실현 가능성 |
| 3 | **출력물의 비즈니스 가치** | A4/A5 포맷이 최종적으로 누구에게, 어떤 맥락에서 사용되는지가 포맷 설계의 최상위 제약조건 |

### Viable Options

#### Option A: 성분 단위 Enrichment + 데이터/개념 재활용형 신규 DB (채택)

| 항목 | 내용 |
|------|------|
| **전략** | 터울주성분 성분명(영문) → ChEMBL compound_search로 ChEMBL ID 확보 → get_mechanism, get_admet, drug_search 순차 호출 → Open Targets로 질병-타겟 연관 보강 → PubMed로 핵심 리뷰 논문 수집 → 정규화 테이블에 저장 |
| **장점** | 성분 단위 축적이므로 의약품 수가 늘어도 enrichment 재활용 가능, 구조화 데이터 우선이라 파싱 비용 낮음, 기존 DB 인프라(Azure PostgreSQL) 활용 |
| **단점** | ChEMBL 매핑 실패 시 해당 성분의 enrichment 불가 (fallback으로 PubMed 검색), 초기 파이프라인 구축에 시간 소요 |

#### Option B: 의약품 단위 직접 Enrichment (기각)

| 항목 | 내용 |
|------|------|
| **전략** | pharmport_medicine.medicine_name(한글)을 직접 PubMed/외부 DB에서 검색 |
| **장점** | 성분 매핑 단계 불필요, 의약품 고유 정보(제형별 특성 등) 직접 수집 가능 |
| **단점** | 한글 약품명으로 국제 DB 검색 불가, 40,837건 각각 개별 조회는 비효율적, 같은 성분의 다른 약품이 중복 데이터 생성, 정규화 불가능 |

**Option B 무효화 근거**: 외부 DB(ChEMBL, Open Targets, PubMed)는 모두 영문 성분명/INN 기반이다. 한글 의약품명으로는 검색 자체가 불가능하며, 터울주성분.성분명(영문)을 거쳐야만 외부 DB와 연결된다. 또한 성분 단위 축적이 아닌 의약품 단위 축적은 같은 성분의 40,837개 의약품에 대해 중복 호출을 유발하여 API quota를 낭비한다.

### ADR (Architecture Decision Record)

| 항목 | 내용 |
|------|------|
| **Decision** | Option A 채택. 성분 단위 enrichment + 정규화 DB 구축 후 Format Parity 진행 |
| **Drivers** | 영문 성분명이 유일한 외부 연결 키, 성분 단위 축적의 재활용성, 기존 인프라 활용 |
| **Alternatives Considered** | Option B (의약품 단위 직접 Enrichment) — 한글 약품명의 국제 DB 검색 불가로 기각 |
| **Why Chosen** | 20,235개 성분에 대해 1회 enrichment하면 40,837개 의약품 전체가 혜택. 비용 효율성과 데이터 정규화 모두 우월 |
| **Consequences** | 신규 테이블: enrichment 9개(기존 DB, `edb_content_block`은 deprecated) + 프로파일 5개 + **복합제구성 1개** + 복약안내 3개 + 매핑/메타 + **호환 뷰 2개**(신규 DB). Enrichment 파이프라인 스크립트 8개 + 프로파일 클러스터링 1개(**단일제 Step A + 복합제 5-tier Step B**) + LLM 생성 2개 신규. 4-Layer Validation Architecture 적용. LLM 호출 20,000→**1,000~3,000건** 축소 (단일제 500~1,500 + 복합제 500~1,500, 프로파일 기반). Phase 1 완료까지 2주, Phase 1.5(**+1.5일 복합제 프로파일링**), Phase 2(프로파일+LLM) 1주 예상. **호환 뷰로 Principle #8(DATABASE_NAME 전환) 구조적 보장 (Phase 3 이후 DROP 예정)** |
| **Follow-ups** | Phase 1 enrichment 커버리지 리포트 후 프로파일 클러스터링 → Phase 2 LLM 생성 착수, 비즈니스 요구사항 확인 후 A4/A5 섹션 확정 |

---

## 1. 활용 데이터 소스 인벤토리

### 1.1. 내부 DB 테이블 (기존 — 읽기 전용)

enrichment 과정에서 기존 테이블의 데이터를 **읽기만** 하며, 기존 테이블의 구조나 데이터는 변경하지 않는다.

| 테이블 | 건수 | 활용 목적 | 활용 컬럼 |
|--------|------|----------|----------|
| **터울주성분** | 20,235 | enrichment canonical key, 성분명 영문/한글, 약효분류 | `심평원성분코드`(PK=enrichment key), `성분명`(영문→외부DB 검색키), `성분명한글`(A4/A5 한글명), `약품분류ID`(약효분류), `약효설명ID`(약효설명 연결) |
| **터울약효설명** | 2,670 | 기존 서비스 테이블 (신규 DB에 동일 테이블명으로 재구축 대상) | `터울버전`(한글 약효설명), `EnglishText`(영문 약효설명) — 신규 DB에서는 LLM이 enrichment 데이터로 새로 생성 |
| **약효요약** | — | 약효 분류 체계 | 약품분류ID 기반 분류명 매핑 |
| **ProductInfos** | 48,027 | ATC 코드, 제품 식별정보, 제형/규격 | `ProductCode`, `AtcCode`(WHO ATC 분류), `Name`(제품명), `MasterIngredientCode`, `DosageFormName`, `Standard` |
| **Manufacturers** | 659 | 제조사 정보 | `ManufacturerID`, `Name`(제조사명) |
| **pharmport_medicine** | 40,837 | 의약품 마스터, 매칭 결과 | `medicine_name`(약품명), `ingredient_code`(심평원성분코드 매칭), `product_code`, `ingredients`(성분), `manufacturer`, `storage`(보관방법) |
| **pharmport_extra_text** | 22,964 | 기존 부가정보 (효능, 주의사항 등) | `field_type`(항목유형), `content`(텍스트) — 신규 DB에서는 미사용 (enrichment 데이터로 대체) |
| **pharmport_usage_text** | 9,772 | 기존 용법용량 텍스트 | `content`(용법용량) — 신규 DB에서는 미사용 (enrichment 데이터로 대체) |
| **pharmport_medicine_extra** | 175,046 | 의약품↔부가정보 매핑 | medicine_id ↔ extra_text_id 연결 |
| **pharmport_medicine_usage** | 72,693 | 의약품↔용법 매핑 | medicine_id ↔ usage_text_id 연결 |

### 1.2. 외부 API 데이터 소스

enrichment 파이프라인에서 호출하는 외부 API. 모든 결과는 `edb_` 테이블에 저장되며, 원본 출처(source, source_id, fetched_at)를 반드시 기록한다.

| 소스 | API | 제공 데이터 | 저장 테이블 | Rate Limit | 비용 |
|------|-----|-----------|-----------|-----------|------|
| **ChEMBL** (EMBL-EBI) | REST API (bio-research MCP) | 화합물 ID 매핑, MoA, ADMET, drug-likeness | `edb_ingredient_xref`, `edb_mechanism`, `edb_admet` | public (throttling 가능) | 무료 |
| **Open Targets** | GraphQL API (bio-research MCP) | 약물-질병 연관, therapeutic area, clinical phase, association score | `edb_drug_disease` | public | 무료 |
| **openFDA** | REST API (Drug Labeling + FAERS) | FDA 승인 라벨 (BBW, 금기, 부작용, 상호작용), 이상반응 보고 빈도 | `edb_safety` | 240 req/min (key 없이), 120K req/day (key) | 무료 |
| **PubMed/NCBI** | E-utilities (bio-research MCP) | 근거 문헌 메타데이터, abstract, retraction 상태 | `edb_literature` | 3 req/sec (key 없이), 10 req/sec (key) | 무료 |
| **ClinicalTrials.gov** | API v2 (bio-research MCP) | 임상시험 현황 (phase, status, enrollment, sponsor) | `edb_clinical_trial` | public | 무료 |
| **bioRxiv** | REST API (bio-research MCP) | 최신 약리학/독성학 프리프린트 (보조) | `edb_literature` | public | 무료 |

### 1.3. 인프라 서비스 (기존 .env)

기존 `.env`에 이미 설정된 리소스를 enrichment에 재활용한다.

| 서비스 | 환경변수 | enrichment 활용 |
|--------|---------|----------------|
| **Azure PostgreSQL** | `DATABASE_HOST/PORT/NAME/USER/PASSWORD` | 모든 edb_ 테이블 저장소 (`common.py` get_connection()) |
| **Azure PostgreSQL (dev)** | `DEV_DATABASE_NAME` (teoul_201201) | dry-run 및 파이프라인 테스트 DB |
| **Azure text-embedding-3-large** | `AZURE_EMBEDDING_ENDPOINT/KEY/MODEL` | enrichment 텍스트 임베딩 (MoA/FDA 요약 → 벡터화, 유사 성분 검색) |
| **DeepL** | `DEEPL_API` | 영문 enrichment → 한글 번역 (FDA label, MoA, 질병명 → A4/A5 한글 출력) |

### 1.4. 데이터 우선순위 규칙

enrichment 데이터 수집 시 소스 간 충돌이 발생할 때 적용하는 우선순위. 상위 소스가 하위 소스를 override한다.

```
1. FDA label (규제기관 전문가 검증 데이터)
2. ChEMBL curated data
3. Open Targets computed data
4. PubMed extracted data
5. FAERS reported data
```

**복약안내 문구 생성 규칙 (Principle #7)**:
- 모든 성분(20,235건)에 대해 LLM이 새로운 복약안내 문구를 생성
- **기존 터울약효설명/팜포트 텍스트는 LLM 프롬프트에 일절 포함하지 않는다**
- LLM 입력: enrichment 구조화 데이터(ChEMBL, FDA, Open Targets, PubMed 등) **만** → LLM 출력: 새로운 한글 복약안내
- 결과는 신규 DB(`teoul_pharminfo_v2`)의 `터울주성분` 테이블에 저장
- 기존 DB(`teoul_pharminfo`)는 그대로 유지하며, 앱 전환 시 `DATABASE_NAME`만 변경

---

## 2. 환경변수 활용 전략 (.env)

### 2.1. 기존 활용 가능한 환경변수

| 환경변수 | 용도 | enrichment 활용 |
|----------|------|-----------------|
| `DATABASE_HOST/PORT/NAME/USER/PASSWORD` | 메인 DB (teoul_pharminfo) 접속 | 모든 enrichment 테이블 저장소. `common.py`의 `get_connection()` 그대로 활용 |
| `DEV_DATABASE_NAME` (teoul_201201) | 개발 DB | enrichment dry-run 및 테스트용 DB. 본 DB 오염 방지 |
| `AZURE_EMBEDDING_ENDPOINT/KEY/MODEL` | Azure text-embedding-3-large | enrichment 텍스트 임베딩: FDA label 요약, MoA 설명 → 벡터화하여 유사 성분 검색/클러스터링에 활용 |
| `DEEPL_API` | DeepL 번역 API | enrichment 데이터 한글 번역: FDA label(영문) → 한글 복약안내 텍스트 자동 번역. A4/A5 한글 출력물 생성 핵심 |

### 2.2. 신규 추가 필요 환경변수

```bash
# openFDA API (선택사항 — API key 없이도 240 req/min 가능, key 있으면 120K req/day)
OPENFDA_API_KEY=

# NCBI/PubMed API key (없으면 3 req/sec, 있으면 10 req/sec)
NCBI_API_KEY=
```

### 2.3. 환경변수별 활용 시나리오

**Azure Embedding (기존)**:
- enrichment 결과 텍스트(MoA description, FDA label 요약 등) → `text-embedding-3-large`로 임베딩
- 용도: 유사 성분 클러스터링, 중복 safety 정보 감지, content_block 간 유사도 비교
- `embedding_service.py`의 기존 `get_embedding()` 함수 재활용

**DeepL 번역 (기존)**:
- FDA label 영문 텍스트 → 한글 번역 (A4/A5 한글 출력물용)
- ChEMBL MoA description 영문 → 한글 번역
- Open Targets disease name 영문 → 한글 번역
- 번역 결과는 `터울복약안내A4.content`(한글)/`터울복약안내A4.content_en`(영문) 및 `터울복약안내A5`의 동일 구조에 이중 저장 (`edb_content_block`은 deprecated — Section 3.1 참조)
- 신규 DB 터울약효설명의 `터울버전`(한글) + `EnglishText`(영문) 구조를 유지

**개발 DB (기존)**:
- `enrich_base.py`에 `--dev` 플래그 추가: `DEV_DATABASE_NAME` DB에서 enrichment 파이프라인 테스트
- 본 DB(`teoul_pharminfo`)에 반영 전 반드시 dev DB에서 dry-run 완료 필수

---

## 3. 신규 DB 스키마 설계

> **아키텍처 핵심**: 현재 서비스 DB(`teoul_pharminfo`)는 그대로 유지하고, 별도 DB(`teoul_pharminfo_v2`)를 새로 생성한다. 신규 DB에는 **기존 서비스와 동일한 테이블명**(터울주성분, 터울약효설명 등)을 사용하여, 앱에서 `DATABASE_NAME` 환경변수만 변경하면 전환 가능하도록 설계한다.
>
> - **기존 DB (`teoul_pharminfo`)**: edb_ enrichment 테이블 9개 생성 (Phase 1 데이터 수집용)
> - **신규 DB (`teoul_pharminfo_v2`)**: 서비스 테이블 + **프로파일 시스템 테이블** + 복약안내 테이블 구성
>
> **Iteration 9 핵심 변경 — Enrichment 프로파일 기반 아키텍처 (Principle #9)**:
> - 기존: 성분(20,235)마다 개별 LLM 호출 → 동일 의미의 중복 문장 발생 가능
> - 신규: Enrichment 결과를 해시 → **프로파일**(500~1,500개) 생성 → 프로파일 단위로 LLM 1회 호출 → 모든 성분에 매핑
> - 효과: LLM 호출 93~97% 절감, 구조적 중복 제거, 신규 성분 0-call 매핑 가능

### 3.1. Enrichment 데이터 테이블 (Phase 1 — 기존 DB)

```sql
-- 1. 성분-외부ID 매핑 테이블 (canonical bridge)
CREATE TABLE edb_ingredient_xref (
    xref_id SERIAL PRIMARY KEY,
    심평원성분코드 VARCHAR(450) NOT NULL REFERENCES "터울주성분"("심평원성분코드"),
    source VARCHAR(50) NOT NULL,           -- 'chembl', 'opentargets', 'pubchem', 'unii'
    source_id VARCHAR(200) NOT NULL,       -- 'CHEMBL25', 'ENSG00000169083', etc.
    source_name TEXT,                       -- 외부 DB에서의 성분명
    confidence FLOAT DEFAULT 1.0,          -- 매핑 신뢰도 (1.0 = exact match)
    match_method VARCHAR(50),              -- 'exact_name', 'synonym', 'similarity'
    fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(심평원성분코드, source, source_id)
);

-- 2. 작용 메커니즘 (ChEMBL get_mechanism)
CREATE TABLE edb_mechanism (
    mechanism_id SERIAL PRIMARY KEY,
    심평원성분코드 VARCHAR(450) NOT NULL,
    chembl_id VARCHAR(50),                 -- molecule ChEMBL ID
    action_type VARCHAR(100),              -- 'INHIBITOR', 'AGONIST', etc.
    mechanism_description TEXT,            -- 'Cyclooxygenase inhibitor'
    target_name TEXT,                      -- target protein/receptor name
    target_chembl_id VARCHAR(50),          -- target ChEMBL ID
    target_type VARCHAR(50),              -- 'SINGLE PROTEIN', etc.
    target_organism VARCHAR(50),          -- 'Homo sapiens', 'Mus musculus', etc.
    direct_interaction BOOLEAN,
    disease_efficacy BOOLEAN,
    binding_site_name TEXT,
    source VARCHAR(50) DEFAULT 'chembl',
    source_refs TEXT,                      -- JSON array of literature refs
    fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(심평원성분코드, chembl_id, target_chembl_id)
);

-- 3. ADMET / Drug-likeness 속성 (ChEMBL get_admet)
CREATE TABLE edb_admet (
    admet_id SERIAL PRIMARY KEY,
    심평원성분코드 VARCHAR(450) NOT NULL,
    chembl_id VARCHAR(50),
    molecular_weight FLOAT,
    alogp FLOAT,                          -- lipophilicity
    hba INT,                              -- H-bond acceptors
    hbd INT,                              -- H-bond donors
    psa FLOAT,                            -- polar surface area
    rotatable_bonds INT,
    aromatic_rings INT,
    ro5_violations INT,                   -- Rule-of-5 violations
    qed_weighted FLOAT,                   -- drug-likeness score (0-1)
    source VARCHAR(50) DEFAULT 'chembl',
    fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(심평원성분코드, chembl_id)
);

-- 4. 약물-질병 연관관계 (Open Targets)
CREATE TABLE edb_drug_disease (
    dd_id SERIAL PRIMARY KEY,
    심평원성분코드 VARCHAR(450) NOT NULL,
    chembl_id VARCHAR(50),
    disease_id VARCHAR(100),              -- EFO/MONDO ID
    disease_name TEXT,
    therapeutic_area TEXT,                 -- 'Oncology', 'Cardiology', etc.
    clinical_phase INT,                   -- max_phase (1-4)
    association_score FLOAT,              -- Open Targets association score
    source VARCHAR(50) DEFAULT 'opentargets',
    fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(심평원성분코드, disease_id)
);

-- 5. 약물 상호작용 / 부작용 (PubMed + Open Targets + openFDA 종합)
CREATE TABLE edb_safety (
    safety_id SERIAL PRIMARY KEY,
    심평원성분코드 VARCHAR(450) NOT NULL,
    info_type VARCHAR(50) NOT NULL,       -- 'interaction', 'adverse_effect', 'contraindication', 'black_box_warning'
    description TEXT NOT NULL,
    severity VARCHAR(20),                 -- 'mild', 'moderate', 'severe', 'critical'
    related_ingredient_code VARCHAR(450), -- 상호작용 대상 성분 (있을 경우)
    evidence_level VARCHAR(20),           -- 'clinical_trial', 'case_report', 'in_vitro', 'computational'
    source VARCHAR(50) NOT NULL,
    source_id VARCHAR(200),               -- PMID, ChEMBL ID, etc.
    validation_status VARCHAR(20) DEFAULT 'draft',
    fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 6. 근거 문헌 (PubMed)
CREATE TABLE edb_literature (
    lit_id SERIAL PRIMARY KEY,
    심평원성분코드 VARCHAR(450) NOT NULL,
    pmid VARCHAR(20),
    pmc_id VARCHAR(20),
    doi TEXT,
    title TEXT NOT NULL,
    authors TEXT,                          -- first author et al. or full list
    journal TEXT,
    pub_year INT,
    pub_type VARCHAR(50),                 -- 'review', 'meta_analysis', 'clinical_trial', 'case_report'
    relevance_category VARCHAR(50),       -- 'mechanism', 'efficacy', 'safety', 'pharmacokinetics'
    abstract_summary TEXT,                -- LLM-summarized or truncated abstract
    retraction_status VARCHAR(20) DEFAULT 'active',  -- 'active', 'retracted', 'corrected', 'expression_of_concern'
    retraction_checked_at TIMESTAMPTZ,    -- 마지막 retraction 확인 일시
    fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(심평원성분코드, pmid)
);

-- 7. 임상시험 요약 (ClinicalTrials.gov)
CREATE TABLE edb_clinical_trial (
    trial_id SERIAL PRIMARY KEY,
    심평원성분코드 VARCHAR(450) NOT NULL,
    nct_id VARCHAR(20) NOT NULL,
    title TEXT,
    phase VARCHAR(20),                    -- 'PHASE1', 'PHASE2', etc.
    status VARCHAR(50),                   -- 'RECRUITING', 'COMPLETED', etc.
    condition_name TEXT,
    enrollment INT,
    start_date DATE,
    completion_date DATE,
    sponsor TEXT,
    source VARCHAR(50) DEFAULT 'clinicaltrials',
    fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(심평원성분코드, nct_id)
);

-- 8. 소스 간 데이터 충돌 감지/해소
CREATE TABLE edb_data_conflict (
    conflict_id SERIAL PRIMARY KEY,
    심평원성분코드 VARCHAR(450) NOT NULL,
    field_name VARCHAR(100) NOT NULL,     -- 충돌 발생 필드 (e.g., 'indication', 'mechanism', 'safety')
    source_a VARCHAR(50) NOT NULL,        -- 첫 번째 소스 (e.g., 'chembl')
    value_a TEXT NOT NULL,                -- source_a의 값
    source_b VARCHAR(50) NOT NULL,        -- 두 번째 소스 (e.g., 'opentargets')
    value_b TEXT NOT NULL,                -- source_b의 값
    resolution VARCHAR(20) DEFAULT 'unresolved',  -- 'unresolved', 'source_a_wins', 'source_b_wins', 'merged', 'expert_resolved'
    resolution_note TEXT,                 -- 해소 근거
    resolved_by TEXT,                     -- 해소자
    resolved_at TIMESTAMPTZ,
    detected_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 9. Enrichment 진행 상태 추적
CREATE TABLE edb_enrichment_status (
    status_id SERIAL PRIMARY KEY,
    심평원성분코드 VARCHAR(450) NOT NULL UNIQUE,
    chembl_mapped BOOLEAN DEFAULT FALSE,
    chembl_mapped_at TIMESTAMPTZ,
    mechanism_fetched BOOLEAN DEFAULT FALSE,
    mechanism_fetched_at TIMESTAMPTZ,
    admet_fetched BOOLEAN DEFAULT FALSE,
    admet_fetched_at TIMESTAMPTZ,
    disease_fetched BOOLEAN DEFAULT FALSE,
    disease_fetched_at TIMESTAMPTZ,
    safety_fetched BOOLEAN DEFAULT FALSE,
    safety_fetched_at TIMESTAMPTZ,
    literature_fetched BOOLEAN DEFAULT FALSE,
    literature_fetched_at TIMESTAMPTZ,
    trials_fetched BOOLEAN DEFAULT FALSE,
    trials_fetched_at TIMESTAMPTZ,
    fda_fetched BOOLEAN DEFAULT FALSE,
    fda_fetched_at TIMESTAMPTZ,
    last_error TEXT,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

> **`edb_content_block` 상태: 폐기 예정 (deprecated)**
>
> `create_enrichment_tables.py`에 10번째 테이블로 포함된 `edb_content_block`은, Iteration 9에서 프로파일 기반 아키텍처(`터울복약안내A4`/`터울복약안내A5`)가 도입되면서 역할이 완전히 대체되었다. Phase 0 DDL에서 테이블은 생성되지만, Phase 1~2 파이프라인에서 **데이터를 적재하지 않는다**. Phase 2 완료 후 `DROP TABLE edb_content_block;`으로 정리할 것. 이 테이블에 데이터를 저장하는 코드를 작성하지 말 것.

### 3.2. 프로파일 시스템 테이블 (신규 DB)

> **Principle #9**: 동일한 enrichment 결과를 가진 성분들은 동일한 복약안내를 공유한다. 프로파일 시스템이 이 원칙을 구조적으로 보장한다.

```sql
-- 1. 복약 프로파일 (enrichment 결과 해시 기반 그룹)
-- 동일한 enrichment 결과 → 동일한 profile_hash → 동일한 복약안내
CREATE TABLE "터울복약프로파일" (
    profile_id    SERIAL PRIMARY KEY,
    profile_hash  VARCHAR(64) NOT NULL UNIQUE,   -- SHA-256(정규화된 enrichment 결과)
    -- ===== 프로파일 유형 (단일제/복합제) =====
    profile_type  VARCHAR(20) NOT NULL DEFAULT 'single',  -- 'single' | 'compound'
    constituent_hash VARCHAR(64),                -- compound: 구성 성분 코드 조합 SHA-256. single은 NULL
    needs_regeneration BOOLEAN DEFAULT FALSE,    -- compound: 구성 성분 enrichment 변경 시 TRUE
    -- ===== 프로파일 구성 요소 (해시 입력 — single) =====
    mechanism     TEXT[],                         -- 작용기전 목록 (정렬됨)
    side_effects  TEXT[],                         -- 부작용 목록 (정렬됨)
    contraindications TEXT[],                     -- 금기사항 목록 (정렬됨)
    interactions  TEXT[],                         -- 상호작용 목록 (정렬됨)
    monitoring    TEXT[],                         -- 모니터링 항목 목록 (정렬됨)
    special_pop   TEXT[],                         -- 특수환자군 주의 목록 (정렬됨)
    -- ===== 프로파일 메타데이터 =====
    profile_json  JSONB NOT NULL,                 -- 전체 enrichment 요약 (LLM 입력용). compound는 tier별 구조
    ingredient_count INT DEFAULT 0,               -- 이 프로파일에 속하는 성분 수
    "등록일"       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "수정일"       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_profile_hash ON "터울복약프로파일"(profile_hash);
CREATE INDEX idx_profile_ingredient_count ON "터울복약프로파일"(ingredient_count);
CREATE INDEX idx_profile_type ON "터울복약프로파일"(profile_type);
CREATE INDEX idx_constituent_hash ON "터울복약프로파일"(constituent_hash) WHERE constituent_hash IS NOT NULL;
CREATE INDEX idx_needs_regen ON "터울복약프로파일"(needs_regeneration) WHERE needs_regeneration = TRUE;

-- 2-1. 복합제 프로파일 구성 성분 매핑
-- compound profile → 구성 단일제 성분 코드/프로파일 연결
CREATE TABLE "터울복합프로파일구성" (
    compound_profile_id  INT NOT NULL REFERENCES "터울복약프로파일"(profile_id),
    constituent_code     VARCHAR(450) NOT NULL,   -- 구성 성분 심평원성분코드(단일제)
    constituent_profile_id INT REFERENCES "터울복약프로파일"(profile_id),  -- 해당 성분의 단일제 프로파일 (NULL: enrichment 미완료)
    role_in_compound     TEXT,                    -- 복합제 내 역할 ("해열/진통", "항히스타민" 등)
    sort_order           INT DEFAULT 0,
    PRIMARY KEY (compound_profile_id, constituent_code)
);
CREATE INDEX idx_compound_constituent ON "터울복합프로파일구성"(constituent_code);

-- 2. 성분-프로파일 매핑 (N:1 — 하나의 성분은 하나의 프로파일에 속함)
CREATE TABLE "터울주성분프로파일매핑" (
    "심평원성분코드" VARCHAR(450) NOT NULL,
    profile_id     INT NOT NULL REFERENCES "터울복약프로파일"(profile_id),
    mapped_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("심평원성분코드", profile_id)
);

CREATE INDEX idx_profile_mapping ON "터울주성분프로파일매핑"(profile_id);
```

**프로파일 해시 생성 규칙**:

**A. 단일제 profile_hash (profile_type='single')**:
```
1. enrichment 데이터에서 6개 키 필드 추출:
   - mechanism: edb_mechanism에서 action_type + target_name (정렬)
   - side_effects: edb_safety에서 info_type='adverse_effect' (severity 정렬)
   - contraindications: edb_safety에서 info_type='contraindication' (정렬)
   - interactions: edb_safety에서 info_type='interaction' (정렬)
   - monitoring: edb_safety에서 severity='critical'/'severe' 항목 (정렬)
   - special_pop: edb_safety에서 특수환자군 관련 (정렬)

2. 각 필드를 알파벳순 정렬 + 정규화 (소문자, 공백 제거)

3. JSON 직렬화 → SHA-256 해시 = profile_hash

4. 동일 해시 → 동일 프로파일 → 복약안내 1회 생성 후 공유
```

**B. 복합제 constituent_hash (profile_type='compound')**:
```
1. 복합제의 구성 성분 심평원성분코드(단일제)를 수집
2. 알파벳순 정렬
3. 파이프(|)로 concat: "101301AIJ|120201AIJ|305100ACR"
4. SHA-256(concat 결과) = constituent_hash
5. 동일 성분 코드 조합이면 반드시 동일 해시 — enrichment/profile 버전과 무관 (안정적)
6. compound의 profile_hash는 별도 생성: LLM 생성 결과 기반 (단일제와 동일 로직)
7. needs_regeneration = TRUE일 때 profile_hash와 복약안내를 재생성

needs_regeneration 설정 조건:
  → TRUE: 구성 성분 중 하나의 단일제 enrichment/profile이 변경됨
  → FALSE 리셋: compound profile의 LLM 복약안내가 재생성됨
  → safety-critical 변경 시 즉시 재생성, 그 외 배치 재생성
```

**프로파일 예시**:
```
프로파일 #A — 단일제 (COX 억제제 — 아세트아미노펜, 이부프로펜 등 12개 성분):
  profile_type: "single"
  mechanism: ["COX inhibitor"]
  side_effects: ["간독성", "위장관 출혈"]
  contraindications: ["중증 간장애"]
  interactions: ["와파린", "이소니아지드"]
  → profile_hash: "a3b2c1d4..."
  → LLM 1회 호출로 복약안내 생성 → 12개 성분 모두 공유

프로파일 #B — 단일제 (H1 수용체 차단제 — 클로르페니라민, 디펜히드라민 등 8개 성분):
  profile_type: "single"
  mechanism: ["H1 receptor antagonist"]
  side_effects: ["졸음", "입마름", "변비"]
  contraindications: ["녹내장", "전립선비대증"]
  interactions: ["MAO 억제제", "중추신경 억제제"]
  → profile_hash: "e5f6g7h8..."
  → LLM 1회 호출로 복약안내 생성 → 8개 성분 모두 공유

프로파일 #C — 복합제 (종합감기약 — 아세트아미노펜+클로르페니라민+슈도에페드린+덱스트로메토르판, Tier 3):
  profile_type: "compound"
  constituent_hash: SHA-256("101301AIJ|120201AIJ|305100ACR|410250AIJ") = "c9d8e7f6..."
  profile_json: { compound_context, constituents 전체 enrichment, compound_interactions }
  → LLM 입력: Small tier (4개 단일제 enrichment 전체 + "종합감기 증상 완화 복합제" 맥락)
  → LLM 출력: 복합 맥락 반영 복약안내 (상호작용, 우선순위, 통합 목적)
  → 동일 4성분 코드 조합의 다른 복합제 코드 → 동일 constituent_hash → 재사용 (LLM 0회)
  → 구성 성분 enrichment 변경 시: needs_regeneration = TRUE → 배치 재생성
```

### 3.3. 복약안내 테이블 (신규 DB)

프로파일 단위로 생성된 복약안내를 저장하는 테이블. 기존 서비스의 `터울주성분A4복약안내매핑`/`터울주성분A5복약안내매핑` 구조를 **프로파일 기반으로 재설계**한다.

```sql
-- 3. A4 복약안내 텍스트 블록 (프로파일 단위 생성)
CREATE TABLE "터울복약안내A4" (
    "복약안내A4ID"  SERIAL PRIMARY KEY,
    content        TEXT NOT NULL,                  -- 복약안내 문장 (한글)
    content_en     TEXT,                           -- 영문 원본 (있을 경우)
    section_type   VARCHAR(50) NOT NULL,           -- 'mechanism', 'precaution', 'interaction', 'contraindication', 'monitoring', 'special_pop'
    severity       VARCHAR(20),                    -- 'critical', 'severe', 'moderate', 'mild'
    embedding      VECTOR(3072),                   -- 유사도 검색용 임베딩
    validation_status VARCHAR(20) DEFAULT 'draft', -- Publication Gate
    validated_by   TEXT,
    validated_at   TIMESTAMPTZ,
    "등록일"        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "수정일"        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 4. A5 복약안내 텍스트 블록 (프로파일 단위 생성)
CREATE TABLE "터울복약안내A5" (
    "복약안내A5ID"  SERIAL PRIMARY KEY,
    content        TEXT NOT NULL,                  -- 복약안내 문장 (한글, 간략)
    content_en     TEXT,                           -- 영문 원본
    section_type   VARCHAR(50) NOT NULL,           -- 'mechanism_brief', 'precaution_brief'
    embedding      VECTOR(3072),
    validation_status VARCHAR(20) DEFAULT 'draft',
    validated_by   TEXT,
    validated_at   TIMESTAMPTZ,
    "등록일"        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "수정일"        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 5. 프로파일-A4 복약안내 매핑
CREATE TABLE "터울프로파일A4매핑" (
    profile_id     INT NOT NULL REFERENCES "터울복약프로파일"(profile_id),
    "복약안내A4ID"  INT NOT NULL REFERENCES "터울복약안내A4"("복약안내A4ID"),
    sort_order     INT DEFAULT 0,
    PRIMARY KEY (profile_id, "복약안내A4ID")
);

-- 6. 프로파일-A5 복약안내 매핑
CREATE TABLE "터울프로파일A5매핑" (
    profile_id     INT NOT NULL REFERENCES "터울복약프로파일"(profile_id),
    "복약안내A5ID"  INT NOT NULL REFERENCES "터울복약안내A5"("복약안내A5ID"),
    sort_order     INT DEFAULT 0,
    PRIMARY KEY (profile_id, "복약안내A5ID")
);

-- 7. 텍스트그램 (기존 데이터 유지, 프로파일 기반 매핑 재구성)
CREATE TABLE "터울텍스트그램" (
    "텍스트그램ID"   SERIAL PRIMARY KEY,
    content         TEXT NOT NULL,                 -- 텍스트그램 내용
    category        VARCHAR(50),                   -- 분류
    "등록일"         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 8. 프로파일-텍스트그램 매핑
CREATE TABLE "터울프로파일텍스트그램매핑" (
    profile_id      INT NOT NULL REFERENCES "터울복약프로파일"(profile_id),
    "텍스트그램ID"   INT NOT NULL REFERENCES "터울텍스트그램"("텍스트그램ID"),
    sort_order      INT DEFAULT 0,
    PRIMARY KEY (profile_id, "텍스트그램ID")
);
```

**복약안내 데이터 흐름 (프로파일 기반)**:
```
[조회 흐름]
심평원성분코드
  → 터울주성분프로파일매핑 → profile_id
  → 터울프로파일A4매핑 → 복약안내A4ID → 터울복약안내A4.content (A4 텍스트)
  → 터울프로파일A5매핑 → 복약안내A5ID → 터울복약안내A5.content (A5 텍스트)
  → 터울프로파일텍스트그램매핑 → 텍스트그램ID → 터울텍스트그램.content

[생성 흐름]
Enrichment 완료 → 프로파일 해시 계산 → 기존 프로파일 매칭?
  ├─ YES: 기존 프로파일에 성분 매핑만 추가 (LLM 호출 0회)
  └─ NO:  신규 프로파일 생성 → LLM으로 A4/A5 복약안내 생성 → 매핑
```

> **Publication Gate**: `터울복약안내A4`/`터울복약안내A5`의 `validation_status = 'expert_reviewed'` 또는 `'published'`인 블록만 최종 출력물에 포함. safety 관련 `section_type`('interaction', 'contraindication', 'monitoring')은 반드시 전문가 검증 필수 (Principle #1).

### 3.4. 터울주성분 확장 테이블 (신규 DB)

**신규 DB(`teoul_pharminfo_v2`)에 `터울주성분`이라는 동일 이름**으로 생성한다. 기존 컬럼은 유지하고, enrichment 매핑 + 프로파일 연결 컬럼을 추가한다. **LLM 복약안내는 프로파일 테이블에 저장**하므로 터울주성분에는 비정규화 요약만 둔다.

```sql
-- 신규 DB(teoul_pharminfo_v2)의 터울주성분: 기존 컬럼 + enrichment + 프로파일 연결
CREATE TABLE "터울주성분" (
    -- ===== 기존 터울주성분 컬럼 (그대로 마이그레이션) =====
    "심평원성분코드" VARCHAR(450) PRIMARY KEY,
    "약품분류ID" INT,
    "약효설명ID" INT,
    "성분명" TEXT,                              -- 영문 성분명
    "sorted_성분명" TEXT,                       -- 알파벳순 정렬
    "성분명한글" TEXT,
    "고갈영양소영문" TEXT,
    "성분명_임베딩" VECTOR,
    "sorted_성분명_embedding" VECTOR(3072),
    "IsDeleted" BOOLEAN NOT NULL DEFAULT FALSE,
    "등록일" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "수정일" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "ModifiedBy" TEXT,

    -- ===== Enrichment 매핑 결과 =====
    chembl_id VARCHAR(50),                     -- ChEMBL compound ID (edb_ingredient_xref 대표값)
    chembl_confidence FLOAT,                   -- 매핑 신뢰도
    chembl_match_method VARCHAR(50),           -- 'exact_name', 'synonym', 'similarity'
    chembl_mapped_at TIMESTAMPTZ,

    -- ===== 프로파일 연결 (비정규화 — 빠른 조회용) =====
    profile_id INT,                            -- 터울복약프로파일.profile_id (정규 관계는 터울주성분프로파일매핑)
    profile_hash VARCHAR(64),                  -- 빠른 비교용

    -- ===== 핵심 Enrichment 요약 (JOIN 없이 빠른 조회용) =====
    "약효설명_new" TEXT,                        -- LLM 생성 약효설명 (한글, 1-2문장) — 프로파일에서 복사
    "약효설명_en" TEXT,                         -- LLM 생성 약효설명 (영문)
    "작용기전_요약" TEXT,                        -- MoA 한글 1-2문장
    "주요적응증" TEXT,                           -- 주요 적응증 3개 (콤마 구분)
    "안전성_요약" TEXT,                          -- 핵심 주의사항 (BBW, 주요 상호작용)

    -- ===== Enrichment 상태 추적 =====
    enrichment_status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'enriched', 'profiled', 'llm_generated', 'expert_reviewed', 'published'
    enrichment_completed_at TIMESTAMPTZ,
    profile_mapped_at TIMESTAMPTZ,
    llm_generated_at TIMESTAMPTZ,
    expert_reviewed_at TIMESTAMPTZ,
    expert_reviewed_by TEXT,
    last_error TEXT,

    -- ===== 메타데이터 =====
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스
CREATE INDEX idx_chembl ON "터울주성분"(chembl_id) WHERE chembl_id IS NOT NULL;
CREATE INDEX idx_enrichment_status ON "터울주성분"(enrichment_status);
CREATE INDEX idx_profile ON "터울주성분"(profile_id) WHERE profile_id IS NOT NULL;
CREATE INDEX idx_분류 ON "터울주성분"("약품분류ID") WHERE "약품분류ID" IS NOT NULL;
```

**컬럼 설계 원칙**:
- **기존 컬럼**: 기존 DB의 터울주성분에서 1:1 마이그레이션. 데이터 타입, 제약조건 동일 → **앱 호환성 보장**
- **Enrichment 매핑**: edb_ingredient_xref의 대표 ChEMBL ID를 비정규화하여 저장 (JOIN 비용 절감)
- **프로파일 연결**: 정규 관계는 `터울주성분프로파일매핑` 테이블, 빠른 조회용으로 profile_id/profile_hash 비정규화
- **요약 컬럼**: 프로파일의 LLM 생성 결과에서 핵심 정보만 비정규화 복사 (JOIN 없이 빠른 조회)
- **복약안내 본문**: `터울복약안내A4`/`터울복약안내A5` 테이블에 저장 (프로파일 기반 매핑으로 조회)
- **상태 추적**: pending → enriched → **profiled** → llm_generated → expert_reviewed → published (profiled 단계 신규 추가)
- **테이블명 호환**: 기존 DB의 `터울주성분`과 동일 이름이므로, 앱에서 DB 연결만 변경하면 기존 컬럼은 그대로 접근 가능

### 3.5. DB 분리 아키텍처 + 테이블 관계

```
╔══════════════════════════════════════════════════════════════════╗
║  기존 DB: teoul_pharminfo (현재 서비스 중 — 변경 없음)            ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  터울주성분 (20,235건) — 기존 서비스 테이블 (읽기 전용)             ║
║    ├── 심평원성분코드 ─────→ edb_ingredient_xref (외부 ID 매핑)    ║
║    │                          ├── → edb_mechanism (작용 메커니즘)  ║
║    │                          ├── → edb_admet (ADMET 속성)       ║
║    │                          ├── → edb_drug_disease (질병 연관)  ║
║    │                          ├── → edb_safety (안전성)           ║
║    │                          ├── → edb_literature (근거 문헌)     ║
║    │                          ├── → edb_clinical_trial (임상시험)  ║
║    │                          ├── → edb_data_conflict (충돌 감지)  ║
║    │                          └── → edb_enrichment_status (추적)  ║
║    └── 심평원성분코드 ←── pharmport_medicine.ingredient_code       ║
║                                                                  ║
║  터울약효설명, 약효요약, ProductInfos, Manufacturers 등 — 그대로   ║
║  pharmport_medicine, pharmport_extra_text 등 — 그대로             ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝

        │ enrichment 데이터 읽기 (edb_ 테이블)
        │ 기존 컬럼값 마이그레이션 (터울주성분 → 터울주성분)
        │ 프로파일 해시 계산 → 클러스터링
        ▼

╔══════════════════════════════════════════════════════════════════╗
║  신규 DB: teoul_pharminfo_v2 (동일 테이블명 — DB 전환용)          ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  ┌─── 터울주성분 (20,235건) ── 동일 테이블명, 확장 컬럼 ──────┐   ║
║  │  기존 컬럼 ←────── 기존 DB에서 1:1 복사                     │   ║
║  │  chembl_id ←────── edb_ingredient_xref 대표값               │   ║
║  │  profile_id ←───── 프로파일 매핑 (비정규화)                  │   ║
║  │  약효설명_new ←─── 프로파일 LLM 결과 복사                    │   ║
║  │  enrichment_status: pending→enriched→profiled→llm_generated │   ║
║  │                     →expert_reviewed→published              │   ║
║  └─────────────────────────┬───────────────────────────────────┘   ║
║                            │                                       ║
║              터울주성분프로파일매핑 (N:1)                            ║
║                            │                                       ║
║                            ▼                                       ║
║  ┌─── 터울복약프로파일 (1,000~3,000건) ───────────────────────┐   ║
║  │  ├─ 단일제: profile_hash ← SHA-256(정규화 enrichment)      │   ║
║  │  │  mechanism[], side_effects[], contraindications[]        │   ║
║  │  │  interactions[], monitoring[], special_pop[]             │   ║
║  │  │  profile_type='single'                                  │   ║
║  │  ├─ 복합제: constituent_hash ← SHA-256(성분코드 정렬)       │   ║
║  │  │  profile_type='compound', needs_regeneration             │   ║
║  │  │  profile_json (JSONB) ← tier별 LLM 입력 전략             │   ║
║  │  └─────────────────────────────────────────────────────────│   ║
║  │         │                                                   │   ║
║  │  터울복합프로파일구성 (compound → 구성 단일제 profile 매핑)    │   ║
║  └──────┬──────────────┬──────────────┬────────────────────────┘   ║
║         │              │              │                             ║
║    터울프로파일    터울프로파일    터울프로파일                       ║
║    A4매핑         A5매핑         텍스트그램매핑                      ║
║         │              │              │                             ║
║         ▼              ▼              ▼                             ║
║  터울복약안내A4  터울복약안내A5  터울텍스트그램                       ║
║  (Publication   (Publication   (기존 데이터 유지,                   ║
║   Gate 적용)     Gate 적용)     매핑만 재구성)                      ║
║                                                                    ║
║  터울약효설명 — LLM이 enrichment 데이터로 신규 생성                  ║
║  약효요약, ProductInfos, Manufacturers — 기존 데이터 1:1 복사       ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
```

**신규 DB 테이블 전체 목록**:

| # | 테이블명 | 원본 | 역할 | 건수(예상) |
|---|---------|------|------|-----------|
| 1 | `터울주성분` | 기존 + 확장 | 성분 마스터 + enrichment/프로파일 연결 | 20,235 |
| 2 | `터울약효설명` | LLM 신규 생성 | 약효설명 (한/영) | ~2,700 |
| 3 | `약효요약` | 1:1 복사 | 약효 분류 체계 | 694 |
| 4 | `ProductInfos` | 1:1 복사 | 제품 식별정보 | 48,027 |
| 5 | `Manufacturers` | 1:1 복사 | 제조사 마스터 | 659 |
| 6 | `터울약품분류` | 1:1 복사 | 약품 카테고리 | 612 |
| 7 | `터울복약프로파일` | 신규 | enrichment 해시 기반 프로파일 (단일제+복합제) | 1,000~3,000 (단일제 500~1,500 + 복합제 500~1,500) |
| 8 | `터울주성분프로파일매핑` | 신규 | 성분↔프로파일 N:1 매핑 | 20,235 |
| 9 | `터울복약안내A4` | 신규 (LLM) | A4 복약안내 텍스트 블록 | ~5,000~15,000 |
| 10 | `터울복약안내A5` | 신규 (LLM) | A5 복약안내 텍스트 블록 | ~1,500~4,500 |
| 11 | `터울프로파일A4매핑` | 신규 | 프로파일↔A4 블록 매핑 | ~5,000~15,000 |
| 12 | `터울프로파일A5매핑` | 신규 | 프로파일↔A5 블록 매핑 | ~1,500~4,500 |
| 13 | `터울텍스트그램` | 기존 데이터 유지 | 텍스트그램 내용 | ~17,000 |
| 14 | `터울프로파일텍스트그램매핑` | 신규 | 프로파일↔텍스트그램 매핑 | ~17,000 |
| 15 | `터울주성분픽토그램매핑` | 1:1 복사 | 픽토그램 매핑 | 17,130 |
| 16 | `터울복합프로파일구성` | 신규 | compound profile → 구성 단일제 profile 매핑 | ~6,600 x avg 4.5 = ~29,700 |

**DB 전환 전략**:
- **기존 DB(`teoul_pharminfo`)**: 변경 없이 유지. 현재 서비스 앱이 계속 참조. edb_ 테이블만 추가.
- **신규 DB(`teoul_pharminfo_v2`)**: 동일 테이블명 + 프로파일 시스템으로 복약안내 관리
- **전환 방법**: 신규 DB 완성 + 전문가 검증 완료 후, `.env`의 `DATABASE_NAME=teoul_pharminfo_v2`로 변경만 하면 앱 전환 완료
- **롤백**: 문제 발생 시 `DATABASE_NAME=teoul_pharminfo`로 복원 → 기존 서비스 즉시 복구
- **edb_ 테이블 위치**: Phase 1 enrichment 데이터 수집용 edb_ 테이블은 **기존 DB**에 생성 (기존 터울주성분을 FK 참조). 신규 DB 구축 시 edb_ 데이터를 읽어서 프로파일 생성 + LLM 생성에 활용
- **신규 DB = 유일한 소스**: 전환 후 신규 DB만 업데이트. 기존 DB와의 동기화 불필요 (Principle #9)

### 3.6. 심평원성분코드 구조와 API 호출 최적화

#### 코드 구조 (9자리)

```
XXXX  YY  Z  WW
────  ──  ─  ──
1-4   5-6 7  8-9
주성분 유형 투여 제형
```

| 자리 | 의미 | 예시 |
|------|------|------|
| 1-4 | 주성분 일련번호 | `1013` = acetaminophen |
| 5-6 | `01~`: 단일제(함량 일련번호), `00`: 복합제, `TL`: 터울수집 | `01`, `00`, `TL` |
| 7 | 투여경로: A=내복, B=주사, C=외용, D=기타 | `A`, `B` |
| 8-9 | 제형코드 | `TB`(정제), `IJ`(주사) |

#### 코드 분포 현황

| 구분 | 건수 | 비율 |
|------|------|------|
| 전체 코드 | 20,226 | 100% |
| 고유 주성분(1-4자리) | 10,491종 | 51.9% |
| 단일제 (YY=01~) | 12,429 | 61.5% |
| 복합제 (YY=00) | 7,791 | 38.5% |
| 터울수집 (YY=TL) | 6 | 0.03% |
| 투여경로 2종 이상인 주성분 | 391종 | — |

#### Enrichment 키 결정: 심평원성분코드(9자리) 유지

**근거**: FDA label이 투여경로별로 별도 문서.

| enrichment 데이터 | 투여경로별 차이 | 처리 방식 |
|---|---|---|
| MoA, ADMET, 질병연관 | **동일** | 동일 주성분(1-4자리) 결과 공유 |
| 문헌, 임상시험 | **대부분 동일** | 동일 주성분(1-4자리) 결과 공유 |
| **FDA label** | **다름** (경구제 vs 주사제 Boxed Warning 차이) | **투여경로별 별도 호출** |
| **부작용(FAERS)** | **일부 다름** (주사부위 반응 등) | **투여경로별 별도 호출** |

#### API 호출 최적화 전략

```
약리학 데이터 (MoA, ADMET, 질병연관, 문헌, 임상시험)
  → 동일 주성분(1-4자리)이면 1회 호출 후 해당 주성분의 모든 코드에 결과 공유
  → 10,491종만 호출 (20,226 → 10,491 = 48% API 호출 절감)

투여경로 의존 데이터 (FDA label, FAERS)
  → 주성분(1-4자리) + 투여경로(7자리) 조합 단위로 호출
  → 약 11,000~12,000회 (multi-route 391종 × 추가 route)

결과 저장은 심평원성분코드(9자리) 단위
  → 동일 주성분의 단일제 변형(함량/제형 차이)은 enrichment 결과 동일
  → DB에는 각 9자리 코드별 레코드로 저장 (출력 시 JOIN 단순화)
```

### 3.7. 호환 뷰 정의 (Compatibility Views)

> **문제**: 기존 앱은 `터울주성분A4복약안내매핑` 및 `터울주성분A5복약안내매핑` 테이블을 직접 쿼리한다. 신규 DB에서는 이 테이블이 존재하지 않고, 프로파일 기반 간접 매핑(`터울주성분프로파일매핑` → `터울프로파일A4/A5매핑`)으로 대체되었다. Principle #8(DATABASE_NAME 변경만으로 전환)이 성립하려면, 기존 앱의 쿼리가 변경 없이 동작해야 한다.
>
> **해결**: 신규 DB에 **PostgreSQL 호환 뷰**를 생성하여 기존 테이블명+컬럼명으로 접근 가능하게 한다. 뷰 내부는 프로파일 매핑을 경유하여 데이터를 반환한다. 호환 뷰는 **Phase 3(전환 후 30일) 이후 DROP 예정** — 앱이 네이티브 프로파일 기반 쿼리로 마이그레이션 완료 시점에 제거한다.

#### 3.7.1. 호환 컬럼 (터울복약안내A4/A5에 추가)

기존 앱이 기대하는 컬럼명을 신규 테이블에 추가한다. Section 3.3 DDL에 아래 컬럼을 포함할 것.

```sql
-- 터울복약안내A4에 추가할 호환 컬럼
ALTER TABLE "터울복약안내A4" ADD COLUMN IF NOT EXISTS "터울버전" TEXT;       -- = content (한글 텍스트)
ALTER TABLE "터울복약안내A4" ADD COLUMN IF NOT EXISTS "분류" INT;           -- section_type → int 역매핑
ALTER TABLE "터울복약안내A4" ADD COLUMN IF NOT EXISTS "IsDeleted" BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE "터울복약안내A4" ADD COLUMN IF NOT EXISTS "ModifiedBy" TEXT;
ALTER TABLE "터울복약안내A4" ADD COLUMN IF NOT EXISTS "EnglishText" TEXT;   -- = content_en (영문 텍스트)
ALTER TABLE "터울복약안내A4" ADD COLUMN IF NOT EXISTS "픽토그램Code" TEXT;

-- 터울복약안내A5에 동일 패턴 추가
ALTER TABLE "터울복약안내A5" ADD COLUMN IF NOT EXISTS "터울버전" TEXT;
ALTER TABLE "터울복약안내A5" ADD COLUMN IF NOT EXISTS "분류" INT;
ALTER TABLE "터울복약안내A5" ADD COLUMN IF NOT EXISTS "IsDeleted" BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE "터울복약안내A5" ADD COLUMN IF NOT EXISTS "ModifiedBy" TEXT;
ALTER TABLE "터울복약안내A5" ADD COLUMN IF NOT EXISTS "EnglishText" TEXT;
```

> **실행자 주의**: `터울버전 = content`, `EnglishText = content_en`으로 INSERT 시 명시적 복사. `분류`는 아래 매핑 함수로 `section_type`에서 역변환.

#### 3.7.2. section_type → 분류(int) 역매핑 함수

```sql
CREATE OR REPLACE FUNCTION section_type_to_분류(st VARCHAR)
RETURNS INT AS $$
BEGIN
    RETURN CASE st
        WHEN 'mechanism'        THEN 1
        WHEN 'precaution'       THEN 2
        WHEN 'interaction'      THEN 3
        WHEN 'contraindication' THEN 4
        WHEN 'monitoring'       THEN 5
        WHEN 'special_pop'      THEN 6
        ELSE 0  -- 미분류
    END;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
```

> **기존 분류 0~13 중 7~13 미매핑**: Phase 2-A 착수 전에 기존 DB에서 `SELECT "분류", COUNT(*) FROM "터울복약안내A4" GROUP BY "분류" ORDER BY "분류"` 실행하여 실제 분포를 확인할 것. 7~13 사용 비율이 >10%이면 매핑 함수 확장 필요.

#### 3.7.3. 호환 뷰 DDL

```sql
-- 호환 뷰: 터울주성분A4복약안내매핑 (기존 44,601건에 상응)
-- 기존 앱 쿼리: SELECT * FROM "터울주성분A4복약안내매핑" WHERE "심평원성분코드" = ?
CREATE OR REPLACE VIEW "터울주성분A4복약안내매핑" AS
SELECT
    pm."심평원성분코드",
    a4m."복약안내A4ID",
    pm.mapped_at AS "등록일"
FROM "터울주성분프로파일매핑" pm
JOIN "터울프로파일A4매핑" a4m
    ON pm.profile_id = a4m.profile_id;

-- 호환 뷰: 터울주성분A5복약안내매핑 (기존 9,602건에 상응)
CREATE OR REPLACE VIEW "터울주성분A5복약안내매핑" AS
SELECT
    pm."심평원성분코드",
    a5m."복약안내A5ID",
    pm.mapped_at AS "등록일"
FROM "터울주성분프로파일매핑" pm
JOIN "터울프로파일A5매핑" a5m
    ON pm.profile_id = a5m.profile_id;
```

#### 3.7.4. 호환 뷰 검증 쿼리

```sql
-- 건수 검증
SELECT COUNT(*) FROM "터울주성분A4복약안내매핑";  -- 기존 44,601건 수준 기대
SELECT COUNT(*) FROM "터울주성분A5복약안내매핑";  -- 기존 9,602건 수준 기대

-- 기존 앱의 전형적 쿼리 패턴 동작 확인
SELECT a4."터울버전", a4."EnglishText", a4."분류"
FROM "터울주성분A4복약안내매핑" m
JOIN "터울복약안내A4" a4 ON m."복약안내A4ID" = a4."복약안내A4ID"
WHERE m."심평원성분코드" = '101301ATB';
```

#### 3.7.5. 호환 보장 범위와 한계

| 항목 | 호환 보장 | 비고 |
|------|----------|------|
| `SELECT` 쿼리 (읽기) | **완전 호환** | 뷰 + 호환 컬럼으로 기존 쿼리 그대로 동작 |
| `INSERT/UPDATE/DELETE` (쓰기) | **미보장** | 뷰는 읽기 전용. 신규 DB에서 복약안내 수정은 프로파일 시스템 경유 필수 |
| `분류` 값 범위 | **부분 호환** | 기존 0~13 → 신규 1~6. 7~13 미매핑 (분포 확인 후 확장) |
| `픽토그램Code` | **호환** | 터울주성분픽토그램매핑은 1:1 복사이므로 기존과 동일 |
| **시간 제한** | Phase 3(전환 후 30일) 이후 DROP 예정 | 앱이 네이티브 프로파일 쿼리로 전환 완료 시 |

---

## 4. Phase 1: Enrichment 파이프라인

### 4.1. Step 1 — ChEMBL ID 매핑 (핵심 브릿지)

**목표**: 터울주성분.성분명(영문) → ChEMBL compound ID 매핑

**MCP 도구**: `mcp__plugin_bio-research_chembl__compound_search`

**전략**:
1. `터울주성분.성분명`에서 개별 성분을 파싱 (콤마로 분리, 함량 제거)
2. **고유 주성분(1-4자리) 단위로 deduplicate** — 동일 화합물 중복 호출 방지
3. 각 고유 성분에 대해 `compound_search(name=성분명)` 호출
4. 결과의 `pref_name` 또는 `synonyms`와 원본 성분명 비교하여 confidence 산출
5. `max_phase >= 4`인 approved drug 우선 매핑
6. 결과를 `edb_ingredient_xref`에 저장 — **해당 주성분의 모든 9자리 코드에 공유**

**성분명 전처리 규칙**:
```
원본: "Acetaminophen 500mg, Tramadol hydrochloride 37.5mg"
→ 분리: ["Acetaminophen", "Tramadol hydrochloride"]
→ 정규화: 함량(숫자+단위) 제거, hydrochloride/sodium/calcium 등 염 표기 보존
→ 검색: compound_search(name="Acetaminophen"), compound_search(name="Tramadol")
```

**예상 커버리지**: 고유 주성분 10,491종 기준으로 API 호출. ChEMBL에는 approved drug 위주로 ~4,000-6,000개 매핑 예상. 복합제(7,791건)는 개별 성분 분리 후 기존 단일제 enrichment 결과 재활용.

**Rate Limit 대응**: ChEMBL API는 public이나 대량 호출 시 throttling 가능. 배치 크기 50건, 호출 간 500ms sleep, 실패 시 exponential backoff.

**수락 기준**:
- [ ] 매핑 완료 성분 수 >= 3,000 (고유 성분 기준)
- [ ] exact name match confidence >= 0.95인 건이 전체의 60% 이상
- [ ] `edb_ingredient_xref` 테이블에 source='chembl' 건 저장 확인
- [ ] `edb_enrichment_status.chembl_mapped = TRUE` 업데이트 확인

### 4.2. Step 2 — 작용 메커니즘 수집

**목표**: 매핑된 ChEMBL ID에 대해 MoA(Mechanism of Action) 데이터 수집

**MCP 도구**: `mcp__plugin_bio-research_chembl__get_mechanism`

**전략**:
1. `edb_ingredient_xref`에서 `source='chembl'`인 ChEMBL ID 목록 추출
2. 각 ID에 대해 `get_mechanism(molecule_chembl_id=ID)` 호출
3. 결과 필드 매핑:
   - `action_type` → edb_mechanism.action_type
   - `molecular_mechanism` → mechanism_description
   - `target_name`, `target_chembl_id` → target 정보
   - `target_organism` → target_organism (ChEMBL target의 organism 필드)
   - `direct_interaction`, `disease_efficacy` → boolean 필드
   - `binding_site_name` → binding_site_name
   - `mechanism_refs` → source_refs (JSON)
4. 동일 molecule에 대해 복수 target/mechanism 가능 → 모두 저장
5. **A4/A5 출력 필터**: 출력물 생성 시 `target_organism = 'Homo sapiens'`인 MoA만 포함. 비인간 target은 DB에 저장하되 출력물에서 제외하여 임상적 관련성을 보장

**예상 결과**: ChEMBL의 curated MoA 데이터는 approved drug에 집중. 매핑된 3,000-6,000 성분 중 MoA 데이터 보유율 약 60-80%.

**수락 기준**:
- [ ] mechanism 레코드 수 >= 2,000
- [ ] action_type 분포 리포트 출력 (INHIBITOR, AGONIST 등)
- [ ] target_chembl_id가 NULL이 아닌 건 >= 80%

### 4.3. Step 3 — ADMET 속성 수집

**목표**: 약물 유사성(drug-likeness) 및 약동학 관련 분자 속성 수집

**MCP 도구**: `mcp__plugin_bio-research_chembl__get_admet`

**전략**:
1. ChEMBL 매핑 성공 건에 대해 `get_admet(molecule_chembl_id=ID)` 호출
2. Lipinski Rule-of-5, QED score 등 저장
3. A4 포맷의 "약동학 특성" 섹션 원본 데이터

**예상 결과**: ChEMBL에 구조 데이터가 있는 compound는 대부분 calculated properties 보유. 커버리지 ~90% of mapped compounds.

**수락 기준**:
- [ ] admet 레코드 수 >= ChEMBL 매핑 건의 85%
- [ ] qed_weighted가 NULL이 아닌 건 >= 70%
- [ ] molecular_weight, alogp 기본 필드 완전성 >= 95%

### 4.4. Step 4 — 질병-타겟 연관관계 (Open Targets)

**목표**: 성분이 관여하는 질병과 치료 영역, 임상 단계 정보 수집

**MCP 도구**: `mcp__plugin_bio-research_ot__search_entities` → `mcp__plugin_bio-research_ot__query_open_targets_graphql` 또는 `batch_query_open_targets_graphql`

**전략**:
1. ChEMBL ID를 Open Targets의 drug identifier로 사용 (동일 체계)
2. GraphQL 쿼리로 drug → indications, mechanisms, knownDrugs 조회
3. 질병별 therapeutic area, clinical phase, association score 저장
4. batch_query를 활용하여 동일 쿼리를 복수 drug에 대해 일괄 실행
5. **최소 임계값**: `association_score >= 0.3`인 연관관계만 저장. 0.3 미만은 노이즈 비율이 높아 출력물 품질을 저하시킴. 임계값 근거: Open Targets 문서에서 score 0.3 이상을 "moderate evidence" 이상으로 분류

**GraphQL 쿼리 패턴**:
```graphql
query DrugIndications($chemblId: String!) {
  drug(chemblId: $chemblId) {
    name
    mechanismsOfAction { rows { mechanismOfAction, targets { approvedName, id } } }
    indications { rows { disease { id, name, therapeuticAreas { id, name } }, maxPhaseForIndication } }
    knownDrugs { rows { disease { name }, phase, status, urls { url, name } } }
  }
}
```

**예상 결과**: Open Targets는 ChEMBL 기반이므로 ChEMBL에 있는 drug은 대부분 커버. indication 데이터는 approved drug에 풍부, preclinical은 제한적.

**수락 기준**:
- [ ] drug_disease 레코드 수 >= 5,000 (성분-질병 쌍 기준)
- [ ] therapeutic_area 분류가 있는 건 >= 80%
- [ ] clinical_phase 정보가 있는 건 >= 70%

### 4.5. Step 5 — FDA 공식 라벨 + 이상반응 데이터 (openFDA)

**목표**: FDA 승인 의약품 라벨(SPL)에서 공식 safety 데이터 수집 — **Safety Ground Truth 역할**

**API**: openFDA Drug Labeling API (`/drug/label`), Adverse Events API (`/drug/event`)

**전략**:
1. `edb_ingredient_xref`에서 매핑된 성분명(영문) 또는 ChEMBL `pref_name`으로 openFDA 검색
   - 검색 필드: `openfda.generic_name`, `openfda.substance_name`
   - INN vs USAN 차이 대응: "paracetamol" → "acetaminophen" 등 synonym 매핑
2. Drug Labeling에서 추출할 SPL 섹션:
   - `boxed_warning` → `edb_safety` (info_type='black_box_warning', source='fda_label')
   - `contraindications` → `edb_safety` (info_type='contraindication', source='fda_label')
   - `warnings_and_cautions` → `edb_safety` (info_type='warning', source='fda_label')
   - `adverse_reactions` → `edb_safety` (info_type='adverse_effect', source='fda_label')
   - `drug_interactions` → `edb_safety` (info_type='interaction', source='fda_label')
   - `indications_and_usage` → `edb_drug_disease` 교차검증용
3. FAERS Adverse Events에서 추출:
   - 성분별 이상반응 보고 빈도 상위 10건
   - `edb_safety` (info_type='adverse_effect', source='faers', evidence_level='post_marketing_surveillance')
4. **FDA 데이터 검증 등급**: FDA label 데이터는 규제기관 전문가가 검증한 데이터이므로:
   - `source='fda_label'`인 safety 레코드 → `validation_status = 'auto_validated'` (추가 전문가 검증 불필요)
   - `source='faers'`인 레코드 → `validation_status = 'draft'` (전문가 검증 필요)

**Rate Limit**: API key 없이 240 req/min (4 req/sec), API key로 120,000 req/day.

**INN/USAN Synonym 처리**:
```
터울주성분.성분명 (INN 기반) → openFDA generic_name (USAN 기반)
  - 1차: 직접 검색
  - 2차: ChEMBL synonym 목록 활용 (Step 1에서 확보)
  - 3차: 수동 매핑 테이블 (주요 차이 30-50건 예상)
```

**수락 기준**:
- [ ] FDA label 매핑 성공 성분 수 >= 2,000
- [ ] boxed_warning 수집 건수 리포트
- [ ] FDA label 기반 safety 레코드의 source='fda_label' 태깅 100%
- [ ] FAERS 이상반응 수집 성분 수 >= 1,500

### 4.6. Step 6 — 근거 문헌 수집 (PubMed)

**목표**: 각 성분에 대한 핵심 리뷰 논문 및 임상 근거 수집

**MCP 도구**: `mcp__plugin_bio-research_pubmed__search_articles` → `mcp__plugin_bio-research_pubmed__get_article_metadata`

**전략**:
1. 성분명 + 카테고리별 검색 쿼리 생성:
   - 약효: `"{성분명}" AND (efficacy OR therapeutic effect) AND Review[Publication Type]`
   - 안전성: `"{성분명}" AND (adverse effect OR side effect OR safety) AND Review[Publication Type]`
   - 상호작용: `"{성분명}" AND drug interaction`
2. 각 쿼리에서 상위 3-5건 메타데이터 수집 (sort=relevance)
3. PMC ID가 있는 경우 abstract 확보, 없으면 title + MeSH terms 기반 요약
4. `pub_type` 분류: Review > Meta-analysis > Clinical Trial > Case Report
5. **Retracted article 필터**: 수집된 논문에 대해 retraction 여부를 확인한다.
   - PubMed 메타데이터의 `publication_type`에 "Retracted Publication"이 포함되면 `retraction_status = 'retracted'`로 설정
   - "Expression of Concern"이 포함되면 `retraction_status = 'expression_of_concern'`으로 설정
   - `retraction_status = 'retracted'`인 논문은 출력물에서 **자동 제외**
   - `retraction_status = 'expression_of_concern'`인 논문은 출력물에 경고 표시와 함께 포함 여부를 전문가가 결정

**Rate Limit 대응**: NCBI E-utilities는 API key 없이 3 req/sec, API key로 10 req/sec. 배치 크기 조절 필요.

**우선순위**: mechanism이 확인된 성분부터 문헌 수집 (Step 2 결과 활용).

**수락 기준**:
- [ ] 문헌 레코드 수 >= 10,000 (성분당 평균 2-3건)
- [ ] PMID가 있는 건 = 100%
- [ ] pub_type 분류 완료율 >= 90%

### 4.7. Step 7 — 임상시험 요약 (ClinicalTrials.gov)

**목표**: 성분별 주요 임상시험 현황 수집

**MCP 도구**: `mcp__plugin_bio-research_c-trials__search_trials`

**전략**:
1. 성분 영문명으로 `search_trials(intervention=성분명)` 호출
2. Phase 2 이상 + COMPLETED 또는 RECRUITING 우선 수집
3. 성분당 상위 5건 저장 (phase 높은 순)
4. nct_id, title, phase, status, condition, enrollment 저장

**예상 결과**: major drug은 수십-수백건의 trial이 존재하나, 상위 5건으로 제한하면 성분당 관리 가능한 규모.

**수락 기준**:
- [ ] trial 레코드가 있는 성분 수 >= 1,500
- [ ] Phase 3/4 trial이 포함된 성분 >= 500
- [ ] nct_id 유일성 보장

### 4.8. Step 8 (보조) — 최신 연구 동향 (bioRxiv)

**목표**: 최근 6개월 이내 약리학/독성학 프리프린트 수집

**MCP 도구**: `mcp__plugin_bio-research_biorxiv__search_preprints`

**전략**:
1. `category='pharmacology and toxicology'`, `recent_days=180` 으로 전체 동향 파악
2. 특정 성분 검색은 bioRxiv API 한계(keyword search 미지원)로 불가
3. 대신 category 기반 수집 후, 제목/abstract에서 매핑된 성분명 매칭
4. 이 단계는 선택적 — Phase 1 핵심이 아닌 보강 데이터

**수락 기준**:
- [ ] pharmacology and toxicology 카테고리 프리프린트 수집 >= 100건
- [ ] 기존 성분과 매칭되는 프리프린트 수 리포트

### 4.9. Phase 1.5: 프로파일 클러스터링

> **Principle #9 + #10 구현**: Enrichment 수집 완료 후, LLM 생성 전에 프로파일 클러스터링을 수행한다. **Step A(단일제)**: 동일한 enrichment 결과를 가진 성분들을 하나의 프로파일로 그룹핑. **Step B(복합제)**: 7,791건 복합제를 5-tier로 분류하고 구성 성분 기반 compound profile 생성. LLM 호출을 프로파일 수(1,000~3,000)로 축소한다.

**목표**: enrichment 완료 성분들의 결과를 해시 → 프로파일 생성 → 성분-프로파일 매핑 (단일제 + 복합제)

**스크립트**: `build_profiles.py`

**순서 제약 (SF-3)**: Step B(복합제 프로파일링)는 반드시 Step A(단일제 프로파일링) 완료 후 실행한다. 이유: compound profile의 구성 성분이 단일제 프로파일에 이미 배정되어 있어야 constituent_profile_id를 기록할 수 있고, LLM 입력에 단일제 enrichment를 포함할 수 있다.

#### Step A: 단일제 프로파일링

```
[1] Enrichment 완료 성분 추출
    └─ edb_enrichment_status에서 주요 단계 완료 건 필터
    └─ mechanism_fetched=TRUE AND safety_fetched=TRUE (최소 조건)

[2] 성분별 프로파일 키 추출
    └─ edb_mechanism → action_type + target_name 리스트 (정렬)
    └─ edb_safety(adverse_effect) → 부작용 리스트 (severity 정렬)
    └─ edb_safety(contraindication) → 금기 리스트 (정렬)
    └─ edb_safety(interaction) → 상호작용 리스트 (정렬)
    └─ edb_safety(severity=critical/severe) → 모니터링 항목 (정렬)
    └─ edb_safety(special_population) → 특수환자군 주의 (정렬)

[3] 정규화 + 해시
    └─ 각 필드: 소문자 변환, 공백 정규화, 알파벳순 정렬
    └─ JSON 직렬화: {"mechanism":[],"side_effects":[],...}
    └─ SHA-256(JSON) = profile_hash

[4] 프로파일 생성/매핑
    └─ profile_hash가 터울복약프로파일에 이미 존재?
        ├─ YES: 기존 profile_id에 성분 매핑만 추가
        └─ NO:  신규 프로파일 INSERT (profile_type='single') + profile_json 저장 + 성분 매핑

[5] 프로파일 통계 리포트
    └─ 총 프로파일 수, 성분 분포 (최대/최소/평균/중앙값)
    └─ Top 10 프로파일 (가장 많은 성분을 포함하는)
    └─ 단독 프로파일 수 (성분 1개만 포함)
```

**enrichment 미완료 성분 처리**:
- enrichment 데이터가 없거나 불완전한 성분 → 별도 "minimal" 프로파일로 분류
- mechanism만 있고 safety 없는 경우 → safety 필드가 빈 프로파일 (해시에 빈 배열 포함)
- 완전히 enrichment 실패한 성분 → `enrichment_status = 'pending'` 유지, 프로파일 미배정

#### Step B: 복합제 프로파일링 (Step A 완료 후 실행 — SF-3)

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

**예상 결과**:
```
단일제: ~12,429건 → 500~1,500 profiles (Step A)
복합제: ~7,791건 (Step B)
  - Tier 1 (~1,200건) → 단일제 프로파일 공유 (추가 profile 0개)
  - Tier 2-5 (~6,591건) → 500~1,500 compound profiles
합계 프로파일: 1,000~3,000
LLM 호출 총계: 1,000~3,000 (기존 20,000 대비 85~95% 절감)
```

**수락 기준**:
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

---

## 5. Phase 2: Format Parity

> **게이트**: Phase 1 enrichment 커버리지 리포트 + Phase 1.5 프로파일 클러스터링(**단일제 Step A + 복합제 Step B**) 완료 후 착수
> **핵심 변경 (Iteration 9+10)**: LLM 복약안내를 **프로파일 단위**로 생성. 프로파일(1,000~3,000)마다 1회 호출. 단일제 프로파일은 기존 방식, **compound 프로파일은 tier별 LLM 입력 전략(Small/Medium/Large)으로 복합 맥락 전달**.

### 5.1. Enrichment 커버리지 + 정확도 리포트 (Phase 2 진입 조건)

Phase 1 완료 시 아래 리포트를 생성하고, 그 결과가 Phase 2 포맷 설계를 결정한다. Phase 2 진입에는 **커버리지 기준과 정확도 기준 모두** 충족해야 한다.

#### 커버리지 리포트

```
성분별 데이터 커버리지:
  - ChEMBL 매핑 성공: X / 20,235 (X%)
  - MoA 데이터 보유: X / mapped (X%)
  - ADMET 데이터 보유: X / mapped (X%)
  - 질병 연관 데이터: X / mapped (X%)
  - 문헌 데이터: X / mapped (X%)
  - 임상시험 데이터: X / mapped (X%)

섹션별 A4/A5 포함 여부 결정:
  - 커버리지 >= 50%: A4 + A5 모두 포함
  - 커버리지 30-50%: A4에만 포함
  - 커버리지 < 30%: 포함하지 않음 (Phase 3에서 재검토)
```

#### 정확도 검증 리포트 (Phase 2 진입 필수 조건)

| 검증 항목 | 방법 | Pass 기준 | Fail 시 조치 |
|----------|------|----------|-------------|
| **ChEMBL 매핑 precision** | exact_name match 100건 수동 검토 | >= 95% | 매핑 로직 재검토, synonym fallback 조정 |
| **MoA 정확도** | 매핑된 MoA 50건 수동 검토 (성분명-target-action_type 일치 확인) | >= 90% | ChEMBL 결과 필터 조건 강화 |
| **Safety 정확도** | critical/severe 전수 + 나머지 50건 샘플 | >= 95% | Safety 데이터 수집 로직 재설계 |
| **문헌 PMID 유효성** | 전수 자동 검증 (PubMed API로 PMID 존재 확인) | = 100% | 무효 PMID 제거 후 재수집 |
| **Retracted article 비율** | 전수 자동 확인 | retracted 건 출력물 포함 = 0건 | retraction 필터 점검 |
| **소스 간 충돌 해소율** | edb_data_conflict 테이블 집계 | unresolved 건 <= 5% | 충돌 해소 우선순위 재설정 |

> **Phase 2 진입 조건**: 위 정확도 지표 **전부** 충족 **AND** 커버리지 기준 충족. 하나라도 Fail이면 해당 항목을 해결한 후 재검증.

### 5.2. 복약안내 문장 생성 원칙: "Why + What + Who"

기존 PharmPort 복약안내는 **"what"(무엇에 주의)만** 안내한다. 신규 EDB는 **"why(왜) + what(무엇) + who(누구)"**를 모두 포함하는 문장을 LLM이 생성한다.

**원칙 비교:**

| | 기존 PharmPort (what only) | 신규 EDB (why + what + who) |
|---|---|---|
| 졸음 | "졸음, 진정, 입마름에 주의하세요" | "H1 수용체 차단으로 중추신경 억제 작용이 있어 졸음이 나타날 수 있습니다" |
| 금주 | "졸릴 수 있으므로 가급적 금주하고" | "알코올은 진정 작용을 증강시키므로 병용을 삼가십시오" |
| 입마름 | "입안이 건조하면 얼음조각을 물고 있거나" | "항콜린 작용으로 입마름, 변비, 배뇨곤란이 생길 수 있습니다" |
| 금기 | (없음) | "녹내장·전립선비대증 환자는 증상이 악화될 수 있으므로 반드시 의사에게 알려주십시오" |
| 상호작용 | (없음) | "MAO 억제제와 병용 시 항콜린 작용이 증강될 수 있습니다" |

**LLM 프롬프트 가이드라인:**
1. 모든 주의사항 문장에 **원인(기전)**을 포함할 것 (예: "~작용으로 인해", "~를 억제하므로")
2. 기존 PharmPort에 없는 **상호작용, 금기, 특정 환자군 경고**를 enrichment 데이터에서 추출하여 추가
3. 문체는 기존 curated 텍스트의 환자 친화적 톤 유지 ("~하세요", "~하십시오", "~바랍니다")
4. 전문 용어 사용 시 괄호 내 부연 (예: "시클로옥시게나제(COX)")
5. **복합제의 경우, 복합 목적(종합감기, 비타민 보충 등)을 첫 문장에 명시할 것**
6. **구성 성분 간 상호작용/상승효과를 우선적으로 언급할 것**
7. **부작용은 빈도/심각도 기준으로 상위 5개 이내로 요약할 것 (A5 공간 제약)**
8. **Tier 4-5(10+성분)의 경우**: 개별 성분 나열보다 카테고리 기반 설명 사용 (예: "비타민 B군", "미네랄류")
9. **Tier에 관계없이**: 환자안전 관련 critical 경고(BBW, 심각한 상호작용)는 반드시 포함

#### 5.2.0. 이중 언어 생성 전략 (Bilingual Generation Strategy)

`터울복약안내A4`/`터울복약안내A5`의 `content`(한글)와 `content_en`(영문), 그리고 호환 컬럼 `터울버전`(한글)/`EnglishText`(영문)의 생성 순서.

**생성 순서: 영문 우선 → 한글 번역 (English-first)**

```
[1] LLM 호출 (영문 생성)
    └─ 입력: enrichment 구조화 데이터 (ChEMBL, FDA, Open Targets — 원본 모두 영문)
    └─ 출력: 영문 복약안내 텍스트
    └─ 저장: content_en / EnglishText

[2] 한글 번역 (DeepL API)
    └─ 입력: [1]의 영문 텍스트
    └─ 출력: 한글 복약안내 텍스트
    └─ 저장: content / 터울버전

[3] 한글 후처리 (LLM 보정 — 안전 관련 section_type은 필수)
    └─ 입력: [2]의 한글 번역 + 의약 용어 일관성 가이드
    └─ 출력: 환자 친화적 톤으로 보정된 한글 텍스트
    └─ 필수: contraindication, interaction, monitoring (안전 관련)
    └─ 선택: mechanism, precaution, special_pop (파일럿 후 판단)
```

**English-first 선택 근거**:
1. Enrichment 소스가 모두 영문이므로 영문 생성 시 소스 데이터와의 fact-checking 용이
2. 전문가 검증 시 영문 원문과 한글 번역을 동시 확인 가능
3. DeepL 영→한 번역 품질이 의약 도메인에서 우수 (기존 `DEEPL_API` 환경변수 활용)
4. 기존 `터울복약안내A4`의 `EnglishText` + `터울버전` 이중 저장 패턴 계승

**비용 예상**: 프로파일 1,000~3,000건 × 2(A4+A5) = 2,000~6,000건 DeepL 번역 호출. 무료 한도(500K chars/month) 내 처리 가능 여부는 Phase 2-B 파일럿에서 확인.

#### 5.2.1. PharmPort field_type → EDB section_type 매핑

기존 PharmPort `pharmport_extra_text.field_type`은 3종으로 복약안내 텍스트를 분류했다. 신규 EDB는 enrichment 데이터 기반으로 6종의 `section_type`을 새로 정의한다. 이 6종은 기존 3종의 "세분화된 재분류"가 **아니라**, enrichment 데이터 구조에서 도출된 **신규 분류 체계**이다.

**기존 PharmPort field_type 분포 (22,964건)**:

| field_type | 건수 | 내용 |
|------------|------|------|
| `precautions` | 10,485 | 일반 주의사항 (부작용+상호작용+모니터링 혼재) |
| `red_box_text` | 9,693 | 경고/금기 텍스트 (금기+특수환자군 혼재) |
| `dosage` | 2,786 | 용법용량 |

**신규 EDB section_type 6종 (enrichment 데이터 기반)**:

| section_type | 정의 | enrichment 소스 | 기존 field_type 개념적 대응 |
|-------------|------|----------------|---------------------------|
| `mechanism` | 작용기전 설명 | edb_mechanism (ChEMBL) | **해당 없음** (완전 신규) |
| `precaution` | 일반 주의사항/부작용 | edb_safety (info_type='adverse_effect') | `precautions` 부분 대응 |
| `interaction` | 약물 상호작용 | edb_safety (info_type='interaction') | `precautions`/`red_box_text` 혼재 |
| `contraindication` | 금기사항/BBW | edb_safety (info_type='contraindication') + FDA BBW | `red_box_text` 부분 대응 |
| `monitoring` | 모니터링 항목 | edb_safety (severity='critical'/'severe') | `precautions` 부분 대응 |
| `special_pop` | 특수환자군 (임부/소아/고령자) | edb_safety + FDA label | `red_box_text` 부분 대응 |

**시각적 매핑**:

```
기존 PharmPort                    신규 EDB section_type
─────────────                    ──────────────────────
precautions (10,485)  ──┬──→  precaution    (부작용/일반 주의)
                        ├──→  interaction   (약물 상호작용)
                        └──→  monitoring    (모니터링 항목)

red_box_text (9,693)  ──┬──→  contraindication (금기사항/BBW)
                        └──→  special_pop      (특수환자군)

dosage (2,786)        ──────  (section_type 미포함 — 의약품/제형 수준 정보)

(없음)                ──────→  mechanism     (작용기전 — 완전 신규)
```

**핵심 차이점**:
1. 기존 `precautions`는 부작용, 상호작용, 모니터링이 혼재된 단일 카테고리 → 신규 3종(`precaution`, `interaction`, `monitoring`)으로 분리
2. 기존 `red_box_text`는 금기와 특수환자군 경고가 혼재 → 신규 2종(`contraindication`, `special_pop`)으로 분리
3. `mechanism`은 기존 PharmPort에 없던 **완전 신규** 카테고리 (ChEMBL MoA enrichment 데이터에서만 도출)
4. 기존 `dosage`는 `section_type`에 미포함 — 용법용량은 개별 의약품/제형 수준 정보이므로 enrichment 프로파일 대상 아님

> **주의**: 이 매핑은 **개념적 대응**이다. 기존 텍스트를 자동으로 신규 section_type에 재분류하지 않는다. 모든 section_type 텍스트는 enrichment 데이터만을 기반으로 LLM이 **새로 생성**한다 (Principle #7).

### 5.3. A5 간략 포맷 컨텐츠 구조

A5 포맷은 처방전과 함께 환자에게 제공되는 **간략 복약안내 용지**. 약품별 1행으로 구성.

**실제 레이아웃 (현행 A5):**
```
┌──────────┬───────────────────────┬──────────────────────────────────────────┬────────────┐
│ 약품이미지 │ 약품명/성분             │ 복약안내                                   │ 투약량/횟수/일수 │
├──────────┼───────────────────────┼──────────────────────────────────────────┼────────────┤
│  [사진]   │ 페니라민정              │ 알코올 주의  물을 많이 드세요                  │  1 / 1 / 1  │
│          │ 클로르페니라민말레산염 2mg │ [알러지질환 치료제] 졸음, 진정, 입마름에         │            │
│          │ [앞]노랑,YH [뒤]노랑    │ 주의하세요.                                │            │
└──────────┴───────────────────────┴──────────────────────────────────────────┴────────────┘
```

**구성 요소:**
- **태그 badge**: `알코올 주의`, `물을 많이 드세요`, `운전·기계조작 주의`, `흡연·알코올 주의` 등
- **[약효설명]**: 대괄호 안 약효 분류명 (예: [알러지질환 치료제], [기침가래 치료제])
- **주의사항**: 핵심 부작용 + 주의 1문장

**신규 EDB A5 변경점:**
```
기존: [알러지질환 치료제] 졸음, 진정, 입마름에 주의하세요.
신규: [알러지질환 치료제] 히스타민 H1 수용체를 차단하여 알레르기 증상을
      완화합니다. 졸음, 입마름에 주의하세요.
```
→ **약효설명에 작용기전 1문장 추가**, 나머지 구조(badge, 이미지, 투약량) 동일 유지

**A5 JSONB 구조 (복약안내_a5 — 단일제):**
```json
{
  "badges": ["알코올 주의", "물을 많이 드세요"],
  "약효분류": "알러지질환 치료제",
  "약효설명": "히스타민 H1 수용체를 차단하여 알레르기 증상을 완화합니다. 졸음, 입마름에 주의하세요.",
  "source": "llm_generated",
  "version": 1
}
```

**복합제 A5 예시 (Tier별):**
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

**A5 JSONB 구조 (복약안내_a5 — 복합제):**
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

### 5.4. A4 상세 포맷 컨텐츠 구조

A4 포맷은 약품별 블록으로 구성된 **상세 복약안내 용지**. 환자 + 약사 겸용.

**실제 레이아웃 (현행 A4):**
```
┌──────────┬──────────────────────────────────────────────────────────────────┐
│          │ 페니라민정                                                        │
│  [사진]   │ [알러지질환 치료제] 클로르페니라민말레산염 2mg                         │
│          │ 알레르기 반응에 관여하는 히스타민수용체를 억제하여 알레르기 비염,          │
│          │ 결막염, 두드러기, 가려움성 피부질환, 혈관운동성 부종에 사용합니다.        │
│          │                                                                │
│          │ [앞]노랑, YH | 마크|SD [뒤]하양, 마크|SD                             │
├──────────┴──────────────────────────────────────────────────────────────────┤
│ 알코올 주의  물을 많이 드세요  운전·기계조작 주의                                 │
│                                                                           │
│ (병원처방용법)                                                               │
│ 졸음, 어지러움, 시야장애가 나타날 수 있으니, 운전이나 위험한 기계조작 시 안전에     │
│ 주의하세요.                                                                 │
│ 졸릴 수 있으므로 가급적 금주하고, 임의로 졸린 약 복용하지 마세요.                  │
│ 입안이 건조하면 얼음조각을 물고 있거나, 무가당 껌, 사탕을 섭취하세요.              │
└───────────────────────────────────────────────────────────────────────────┘
```

**구성 요소:**
- **상단 블록**: 약품이미지 + 약품명 + [약효분류] + 성분/함량 + 약효설명(2-3문장) + 식별정보
- **태그 badge**: 알코올/운전/흡연 등 경고 태그
- **(병원처방용법)**: 복약 주의사항 여러 줄

**신규 EDB A4 변경점:**
```
기존 (what only):
  졸음, 어지러움, 시야장애가 나타날 수 있으니, 운전이나 위험한 기계조작 시
  안전에 주의하세요.
  졸릴 수 있으므로 가급적 금주하고, 임의로 졸린 약 복용하지 마세요.
  입안이 건조하면 얼음조각을 물고 있거나, 무가당 껌, 사탕을 섭취하세요.

신규 (why + what + who):
  H1 수용체 차단으로 중추신경 억제 작용이 있어 졸음, 어지러움이 나타날 수
  있습니다. 복용 중에는 운전 및 위험한 기계 조작을 피하시기 바랍니다.
  알코올은 진정 작용을 증강시키므로 병용을 삼가십시오.
  항콜린 작용으로 입마름, 변비, 배뇨곤란이 생길 수 있으며,
  입이 마를 때는 물을 자주 마시거나 무가당 껌을 씹으면 도움이 됩니다.

추가 (기존에 없던 정보):
  ⚠ 상호작용: MAO 억제제와 병용 시 항콜린 작용이 증강될 수 있습니다.
  ⚠ 금기: 녹내장, 전립선비대증 환자는 복용 전 의사와 상담하십시오.
  📋 근거: FDA Label, ChEMBL CHEMBL509
```

**A4 JSONB 구조 (복약안내_a4):**
```json
{
  "version": 1,
  "generated_at": "2026-03-20T10:00:00Z",
  "sections": {
    "header": {
      "성분명_한글": "클로르페니라민말레산염",
      "성분명_영문": "Chlorpheniramine maleate",
      "심평원성분코드": "100201ATB",
      "약효분류": "알러지질환 치료제"
    },
    "약효설명": "알레르기 반응을 일으키는 히스타민 H1 수용체를 경쟁적으로 차단하여 비염, 결막염, 두드러기, 가려움성 피부질환, 혈관운동성 부종을 완화합니다.",
    "badges": ["알코올 주의", "물을 많이 드세요", "운전·기계조작 주의"],
    "병원처방용법": [
      "H1 수용체 차단으로 중추신경 억제 작용이 있어 졸음, 어지러움이 나타날 수 있습니다. 복용 중에는 운전 및 위험한 기계 조작을 피하시기 바랍니다.",
      "알코올은 진정 작용을 증강시키므로 병용을 삼가십시오.",
      "항콜린 작용으로 입마름, 변비, 배뇨곤란이 생길 수 있으며, 입이 마를 때는 물을 자주 마시거나 무가당 껌을 씹으면 도움이 됩니다."
    ],
    "상호작용": [
      "MAO 억제제와 병용 시 항콜린 작용이 증강될 수 있습니다.",
      "다른 중추신경 억제제(수면제, 진정제)와 병용 시 졸음이 심해질 수 있습니다."
    ],
    "금기": [
      "녹내장 환자는 안압이 상승할 수 있으므로 복용 전 의사와 상담하십시오.",
      "전립선비대증 환자는 배뇨곤란이 악화될 수 있습니다."
    ],
    "근거": ["FDA Label", "ChEMBL CHEMBL509"]
  },
  "sources": ["chembl", "fda_label"],
  "llm_model": "claude-sonnet-4-6"
}
```

**A4 데이터 출처 매핑:**

| A4 섹션 | 데이터 출처 | 비고 |
|---|---|---|
| 약효설명 | edb_mechanism + LLM 생성 | 기전 기반 문장형 |
| badges | edb_safety(info_type) → 규칙 매핑 | 알코올/운전/흡연 자동 판별 |
| 병원처방용법 | edb_safety + edb_admet + LLM 생성 | **why+what** 원칙 적용 |
| 상호작용 | edb_safety(info_type='interaction') | 기존에 없던 신규 정보 |
| 금기 | edb_safety(info_type='contraindication') | 기존에 없던 신규 정보 |
| 근거 | edb_literature + edb_ingredient_xref | PMID, FDA Label 출처 |

**LLM 복약안내 생성 데이터 흐름 (프로파일 기반 — Iteration 9)**:
```
[Phase 1.5에서 완료된 프로파일 단위로 처리]

터울복약프로파일.profile_json → LLM 입력 (프로파일 단위)
  ├── mechanism[]     → 작용기전 (MoA, target, action_type)
  ├── side_effects[]  → 부작용 목록
  ├── contraindications[] → 금기사항
  ├── interactions[]  → 상호작용
  ├── monitoring[]    → 모니터링 항목
  └── special_pop[]   → 특수환자군 주의

  ※ 기존 텍스트(터울약효설명, pharmport_extra/usage)는 일절 참조하지 않음
  ※ LLM 입력은 오직 enrichment 구조화 데이터(profile_json)만으로 구성
  ※ 프로파일 1개당 LLM 1회 호출 (총 500~1,500회)

  → LLM (Claude API) 입력: 프로파일별 enrichment 데이터
  → 출력: A4 복약안내 블록 + A5 간략 블록 + 텍스트그램 매핑
  → 신규 DB 터울복약안내A4/A5 테이블에 저장
  → 터울프로파일A4매핑/A5매핑으로 프로파일에 연결
  → 터울주성분프로파일매핑으로 모든 해당 성분에 자동 적용
  → 전문가 검증 후 validation_status = 'expert_reviewed' 승격

[성분별 개별 처리 (프로파일 공유 불가 항목)]
  - 약효설명_new: 프로파일의 약효설명을 성분별로 비정규화 복사
  - 약효분류: 터울주성분.약품분류ID 기반 (성분 고유)
  - 성분명_한글/영문: 성분 고유 정보 (프로파일과 무관)
```

### 5.5. 분류/정렬/픽토그램 매핑 규칙

| 요소 | 규칙 | 데이터 출처 |
|------|------|-----------|
| **약효 분류** | 터울주성분.약품분류ID → 분류명 매핑 테이블 필요 | 터울주성분 + 별도 매핑 |
| **ATC 코드** | ProductInfos.AtcCode → WHO ATC 분류 체계 | ProductInfos 경유 |
| **심각도 아이콘** | safety.severity → 색상 코드 (critical=red, severe=orange, moderate=yellow, mild=green) | edb_safety |
| **임상 단계 뱃지** | Phase 1-4 → 단계별 아이콘 | edb_drug_disease, edb_clinical_trial |
| **정렬 기본값** | A4: 심평원성분코드 오름차순, A5: 약효 분류 → 성분명 알파벳순 | 기존 컬럼 |

---

## 6. 신규 DB 구축 및 데이터 마이그레이션

### 6.1. 신규 DB 생성 (`teoul_pharminfo_v2`)

```sql
-- Azure PostgreSQL에 신규 DB 생성
CREATE DATABASE teoul_pharminfo_v2;

-- pgvector 확장 활성화 (기존 DB와 동일)
CREATE EXTENSION IF NOT EXISTS vector;
```

**신규 DB에 생성할 테이블** (Section 3.5 전체 목록 참조):

| 구분 | 테이블명 | 원본 | 역할 |
|------|---------|------|------|
| **데이터 복사** | `터울주성분` | 기존 + 확장 | 기존 컬럼 1:1 복사 + enrichment/프로파일 컬럼 추가 (Section 3.4) |
| | `터울약효설명` | LLM 신규 생성 | enrichment 데이터 기반 LLM 신규 생성 |
| | `약효요약` | 1:1 복사 | 기존 분류 체계 유지 |
| | `ProductInfos` | 1:1 복사 | 제품 식별정보 |
| | `Manufacturers` | 1:1 복사 | 제조사 마스터 |
| | `터울약품분류` | 1:1 복사 | 약품 카테고리 |
| | `터울텍스트그램` | 기존 데이터 유지 | 텍스트그램 내용 (매핑만 재구성) |
| | `터울주성분픽토그램매핑` | 1:1 복사 | 픽토그램 매핑 |
| **프로파일 시스템** | `터울복약프로파일` | 신규 | enrichment 해시 기반 프로파일 (500~1,500건) |
| | `터울주성분프로파일매핑` | 신규 | 성분↔프로파일 N:1 매핑 |
| **복약안내 (LLM)** | `터울복약안내A4` | 신규 (LLM) | A4 복약안내 텍스트 블록 + Publication Gate |
| | `터울복약안내A5` | 신규 (LLM) | A5 복약안내 텍스트 블록 + Publication Gate |
| | `터울프로파일A4매핑` | 신규 | 프로파일↔A4 블록 매핑 |
| | `터울프로파일A5매핑` | 신규 | 프로파일↔A5 블록 매핑 |
| | `터울프로파일텍스트그램매핑` | 신규 | 프로파일↔텍스트그램 매핑 |

### 6.2. 기존 컬럼 마이그레이션

| 원본 (기존 DB) | 대상 (신규 DB) | 변환 |
|---------------|---------------|------|
| `터울주성분.*` (전체 컬럼) | `터울주성분.*` (기존 컬럼 부분) | 1:1 INSERT (20,235건), 데이터 타입 동일 |
| `터울주성분.성분명` (영문) | ChEMBL 검색 키 | 전처리 후 compound_search 입력 |
| `edb_ingredient_xref` (대표 ChEMBL ID) | `터울주성분.chembl_id` | 비정규화 (source='chembl', 최고 confidence 1건) |
| `edb_enrichment_status` | `터울주성분.enrichment_status` | 상태 통합 (enriched/profiled/llm_generated/expert_reviewed) |
| `build_profiles.py` 결과 | `터울복약프로파일` + `터울주성분프로파일매핑` | 프로파일 해시 → profile_id 매핑 (Phase 1.5) |
| `build_profiles.py` 결과 | `터울주성분.profile_id`, `profile_hash` | 비정규화 복사 (빠른 조회용) |
| `ProductInfos.*` (전체) | `ProductInfos.*` | 1:1 복사 (48,027건) |
| `Manufacturers.*` (전체) | `Manufacturers.*` | 1:1 복사 (659건) |
| `약효요약.*` (전체) | `약효요약.*` | 1:1 복사 |
| `터울약품분류.*` (전체) | `터울약품분류.*` | 1:1 복사 (612건) |
| 기존 텍스트그램 데이터 | `터울텍스트그램` | 기존 데이터 이관 (매핑은 프로파일 기반으로 재구성) |
| 기존 픽토그램매핑 | `터울주성분픽토그램매핑` | 1:1 복사 (17,130건) |

### 6.3. LLM 생성 데이터 (기존 텍스트 미참조)

LLM 복약안내 생성 시 **기존 터울약효설명/팜포트 텍스트는 일절 참조하지 않는다**. 오직 enrichment 데이터(프로파일)만으로 생성한다.

| 신규 DB 대상 | 데이터 원본 | 생성 방법 |
|-------------|-----------|----------|
| `터울복약안내A4` | `터울복약프로파일.profile_json` | **프로파일 단위** LLM 생성 (500~1,500회). A4 상세 블록 |
| `터울복약안내A5` | `터울복약프로파일.profile_json` | **프로파일 단위** LLM 생성. A5 간략 블록 |
| `터울프로파일A4매핑` | LLM 생성 결과 | 프로파일↔A4 블록 매핑 |
| `터울프로파일A5매핑` | LLM 생성 결과 | 프로파일↔A5 블록 매핑 |
| `터울프로파일텍스트그램매핑` | 프로파일 → 텍스트그램 규칙 매핑 | 기존 텍스트그램을 프로파일 기반으로 재매핑 |
| `터울약효설명` (전체 재구축) | edb_mechanism + edb_drug_disease | LLM이 enrichment 데이터만으로 약효설명 테이블 전체를 신규 생성 |
| `터울주성분.약효설명_new` | 프로파일 LLM 결과 → 비정규화 복사 | 프로파일의 약효설명을 각 성분에 복사 |
| `터울주성분.요약 컬럼들` | 프로파일 LLM 결과 → 비정규화 복사 | 작용기전, 적응증, 안전성 요약을 각 성분에 복사 |

### 6.4. 데이터 처리 규칙

1. **기존 DB 무변경**: `teoul_pharminfo`의 모든 테이블은 일체 변경하지 않는다. edb_ 테이블만 추가.
2. **신규 DB = 동일 테이블명**: `teoul_pharminfo_v2`에 기존과 동일한 테이블명으로 생성. 앱 호환성 보장.
3. **사실 데이터는 복사**: ProductInfos, Manufacturers, 약효요약, 터울약품분류, 텍스트그램, 픽토그램매핑 등 사실/매핑 데이터는 기존 DB에서 1:1 복사.
4. **텍스트 데이터는 프로파일 단위 신규 생성**: 복약안내(A4/A5)는 **프로파일 단위**로 LLM이 enrichment 데이터만으로 생성. 터울약효설명도 LLM 신규 생성. 기존 텍스트 미참조.
5. **프로파일 기반 매핑**: 기존 `터울주성분A4복약안내매핑`/`터울주성분A5복약안내매핑` → 프로파일을 경유하는 간접 매핑(`터울주성분프로파일매핑` → `터울프로파일A4/A5매핑`)으로 대체. 동일 프로파일의 성분들은 자동으로 동일 복약안내를 공유.
6. **edb_ 테이블**: enrichment 원본 데이터는 기존 DB에 보관. 신규 DB의 프로파일에 요약, 터울주성분에는 대표값만 비정규화.
7. **신규 DB = 유일한 소스**: 전환 후 신규 DB만 업데이트. 기존 DB와의 양방향 동기화 불필요.
8. **충돌 시 우선순위**: Section 1.4의 enrichment 데이터 우선순위 규칙 적용.

### 6.5. DB 전환 절차

```
[1] 신규 DB 준비 완료 확인
    └─ 터울주성분 20,235건 존재
    └─ enrichment_status = 'published' 건수 >= 3,000
    └─ Safety 전문가 검증 완료
    └─ A4/A5 샘플 승인 완료

[2] 환경변수 전환
    └─ .env: DATABASE_NAME=teoul_pharminfo → teoul_pharminfo_v2
    └─ 앱 재시작

[3] 검증
    └─ 기존 기능 정상 동작 확인 (기존 컬럼 접근)
    └─ 신규 복약안내 데이터 표시 확인

[4] 롤백 (문제 발생 시)
    └─ .env: DATABASE_NAME=teoul_pharminfo_v2 → teoul_pharminfo
    └─ 앱 재시작 → 기존 서비스 즉시 복구
```

---

## 7. 단계별 로드맵

### Phase 0: 인프라 준비 (Day 1-2)

- [ ] **신규 DB 생성**: Azure PostgreSQL에 `teoul_pharminfo_v2` DB 생성 + pgvector 확장 활성화
- [ ] **기존 DB에 edb_ 테이블 9개 DDL 실행** (Section 3.1 — enrichment 데이터 수집용)
- [ ] `edb_enrichment_status`에 터울주성분 전체 20,235건 초기화
- [ ] `enrich_base.py` 스켈레톤 작성: DB 연결, rate limit 관리, 상태 업데이트, Layer 1 자동 검증 공통 모듈
- [ ] `.env`에 환경변수 추가:
  ```bash
  # 신규 DB (동일 테이블명 아키텍처)
  V2_DATABASE_NAME=teoul_pharminfo_v2
  # openFDA / PubMed API
  NCBI_API_KEY=
  OPENFDA_API_KEY=
  ```
- [ ] `common.py`에 `get_v2_connection()` 함수 추가 (V2_DATABASE_NAME 사용)
- [ ] `enrich_base.py`에서 기존 환경변수 활용 설정:
  - `DATABASE_*` → `common.py` get_connection() (기존 DB — enrichment 수집용)
  - `V2_DATABASE_NAME` → `common.py` get_v2_connection() (신규 DB — LLM 결과 저장용)
  - `DEV_DATABASE_NAME` → `--dev` 플래그로 dev DB 테스트
  - `AZURE_EMBEDDING_*` → `embedding_service.py` get_embedding() (enrichment 텍스트 임베딩)
  - `DEEPL_API` → 영문 enrichment → 한글 번역 (A4/A5 한글 출력용)
- [ ] dry-run 모드 기본 지원 (dev DB에서 먼저 실행)

**수락 기준**: 기존 DB에 edb_ 9개 테이블 생성 확인, 신규 DB(teoul_pharminfo_v2) 생성 확인, enrichment_status에 20,235건 존재, dry-run으로 ChEMBL 1건 테스트 성공

### Phase 1-A: ChEMBL 매핑 + MoA + ADMET (Day 3-7)

- [ ] `enrich_chembl.py` 작성: Step 1-3 통합 실행
  - 성분명 전처리 (함량 제거, 염 표기 처리)
  - compound_search → xref 저장
  - get_mechanism → mechanism 저장
  - get_admet → admet 저장
- [ ] 매핑 완료 6,956 성분(매칭 완료분) 우선 처리
- [ ] 중간 리포트: 매핑률, MoA 커버리지, ADMET 커버리지
- [ ] 매핑 실패 건 프로파일링 (성분명 형태 분석)

**수락 기준**: ChEMBL 매핑 >= 3,000건, MoA >= 2,000건, ADMET >= 2,500건

### Phase 1-B: FDA + Open Targets + PubMed + ClinicalTrials (Day 8-14)

- [ ] `enrich_fda.py` 작성: Step 5 실행 (**FDA를 PubMed보다 먼저 실행 — Safety Ground Truth 확보**)
  - openFDA Drug Labeling → boxed_warning, contraindications, adverse_reactions, drug_interactions 수집
  - openFDA FAERS → 이상반응 보고 빈도 상위 10건 수집
  - FDA label 영문 텍스트 → DeepL API로 한글 번역 (`DEEPL_API` 환경변수 활용)
  - source='fda_label' 레코드는 `validation_status = 'auto_validated'` 자동 설정
- [ ] `enrich_opentargets.py` 작성: Step 4 실행
  - GraphQL batch query 활용
  - indication + therapeutic area 저장
- [ ] `enrich_pubmed.py` 작성: Step 6 실행
  - 성분별 3가지 카테고리 검색
  - 메타데이터 수집 + 분류
  - FDA label과 교차검증: FDA에 있는 safety 정보와 PubMed 추출 정보 비교 → 불일치 시 `edb_data_conflict`에 기록
- [ ] `enrich_trials.py` 작성: Step 7 실행
  - 성분별 상위 5건 trial 수집
- [ ] enrichment 텍스트 임베딩: MoA/FDA 요약 → Azure text-embedding-3-large (`AZURE_EMBEDDING_*` 환경변수 활용)
- [ ] 전체 커버리지 리포트 생성

**수락 기준**: FDA label 매핑 >= 2,000건, drug_disease >= 5,000건, literature >= 10,000건, trial 보유 성분 >= 1,500

### Phase 1-C: 커버리지 + 정확도 리포트 + Phase 2 게이트 (Day 13-14)

- [ ] `enrichment_report.py` 작성: Section 5.1의 커버리지 + 정확도 리포트 생성
- [ ] **정확도 검증 실행** (Layer 2):
  - ChEMBL 매핑 precision: exact 100건 + synonym 50건 수동 검토
  - MoA 정확도: 50건 수동 검토
  - Safety 정확도: Tier 1+2 전수 집계 + Tier 3 50건 샘플
  - PMID 유효성: 전수 자동 확인
  - Retracted article: 전수 자동 확인
- [ ] **소스 간 충돌 감지**: ChEMBL ↔ Open Targets 교차 비교, 기존 팜포트 ↔ enrichment 교차 비교 → `edb_data_conflict`에 기록
- [ ] 소스 충돌 해소율 집계 (`unresolved <= 5%` 확인)
- [ ] 섹션별 A4/A5 포함 여부 결정 (커버리지 기반)
- [ ] 비즈니스 요구사항 확인: A4/A5 최종 사용자, 배포 채널, 언어
- [ ] Phase 2 착수 여부 결정 (커버리지 + 정확도 기준 모두 충족 필수)

**수락 기준**: 커버리지 리포트 완성, 정확도 지표 전부 Pass, 소스 충돌 unresolved <= 5%, 섹션별 포함/제외 결정 문서화

### Phase 1.5: 프로파일 클러스터링 (Day 14-16.5)

#### Step A: 단일제 프로파일링 (Day 14-15)

- [ ] `build_profiles.py` 작성: Section 4.9 Step A 단일제 프로파일 클러스터링 실행
  - enrichment 완료 성분에서 6개 키 필드 추출 (mechanism, side_effects, contraindications, interactions, monitoring, special_pop)
  - 정규화 → SHA-256 해시 → 프로파일 생성
  - 성분-프로파일 매핑 생성
- [ ] 프로파일 통계 리포트 생성
  - 총 프로파일 수, 성분 분포 (최대/최소/평균/중앙값)
  - Top 10 대형 프로파일 + 단독 프로파일 수
- [ ] 프로파일 품질 검토: 대형 프로파일(50+ 성분) 내의 성분들이 실제로 동일한 복약안내를 공유할 수 있는지 약사 샘플 검토

#### Step B: 복합제 프로파일링 (Day 15-16.5 — Step A 완료 후, SF-3)

- [ ] `build_profiles.py`에 compound profiling 로직 추가
  - [B0] 복합제 7,791건 Tier 분포 계측
  - [B1] Tier 1 처리 (단일제 프로파일 매핑)
  - [B2] 구성 성분 식별 (3단계 fallback)
  - [B3] constituent_hash 생성 + 중복 제거
  - [B4] compound profile 생성 + 터울복합프로파일구성 데이터 생성
  - [B5] 통계 리포트
- [ ] compound 프로파일 통계 리포트 (Tier별 집계)

**수락 기준**: enrichment 완료 성분 100% 프로파일 배정, 단일제 프로파일 수가 성분 수의 3~25%, 복합제 7,791건 전체 Tier 분류 완료, 구성 성분 식별 성공률 >= 95%, compound profile 수 500~1,500, 통계 리포트 생성

### Phase 2-A: 신규 DB 테이블 생성 + 데이터 마이그레이션 (Day 17-18.5)

- [ ] `create_v2_tables.py` 작성: 신규 DB(teoul_pharminfo_v2)에 전체 테이블 DDL 실행
  - `터울주성분` (Section 3.4 확장 스키마)
  - `터울약효설명` (동일 구조, 데이터는 Phase 2-B에서 LLM 생성)
  - `약효요약`, `ProductInfos`, `Manufacturers`, `터울약품분류` (동일 구조)
  - **프로파일 시스템**: `터울복약프로파일`, `터울주성분프로파일매핑`, `터울복합프로파일구성` (Section 3.2)
  - **복약안내**: `터울복약안내A4`, `터울복약안내A5`, 매핑 테이블 4개 (Section 3.3)
  - `터울복약프로파일`에 `profile_type`, `constituent_hash`, `needs_regeneration` 컬럼 DDL 포함
  - `터울텍스트그램`, `터울주성분픽토그램매핑`
  - **[Iteration 11] 호환 뷰 + 호환 컬럼 DDL (Section 3.7)**:
    - `section_type_to_분류()` 함수 생성
    - `터울복약안내A4`/`터울복약안내A5`에 호환 컬럼 추가 (`터울버전`, `분류`, `IsDeleted`, `ModifiedBy`, `EnglishText`, `픽토그램Code`)
    - `터울주성분A4복약안내매핑` 호환 뷰 생성
    - `터울주성분A5복약안내매핑` 호환 뷰 생성
- [ ] 사실 데이터 1:1 복사: 기존 DB → 신규 DB
  - `터울주성분` 기존 컬럼 (20,235건)
  - `약효요약`, `ProductInfos` (48,027건), `Manufacturers` (659건)
  - `터울약품분류` (612건), 텍스트그램 데이터, 픽토그램매핑 (17,130건)
- [ ] edb_ingredient_xref의 대표 ChEMBL ID → 신규 DB 터울주성분.chembl_id 비정규화 저장
- [ ] 프로파일 데이터 이관: `build_profiles.py` 결과를 신규 DB에 저장
  - `터울복약프로파일` (1,000~3,000건 — 단일제 500~1,500 + compound 500~1,500)
  - `터울주성분프로파일매핑` (enrichment 완료 성분 + 복합제 전체)
  - `터울복합프로파일구성` (compound → 구성 단일제 profile 매핑)
  - `터울주성분.profile_id`, `profile_hash` 비정규화
- [ ] enrichment_status = 'profiled'로 업데이트 (프로파일 배정 완료 건)

**수락 기준**: 신규 DB 터울주성분 20,235건 존재, 기존 컬럼 데이터 일치 검증, ProductInfos/Manufacturers 건수 일치, 프로파일 테이블 데이터 이관 완료, chembl_id/profile_id 비정규화 건수 확인, **호환 뷰 2개(`터울주성분A4/A5복약안내매핑`) 생성 확인, 기존 앱 핵심 쿼리 5종 호환 테스트 통과**

### Phase 2-B: 프로파일 단위 LLM 복약안내 생성 (Day 19.5-24)

- [ ] `generate_medication_guide.py` 작성: **프로파일 단위** LLM 복약안내 생성 엔진
  - **입력 준비**: `터울복약프로파일.profile_json`에서 enrichment 데이터 추출
    - mechanism[], side_effects[], contraindications[], interactions[] → 구조화 프롬프트
    - **기존 텍스트(터울약효설명, pharmport_extra/usage)는 프롬프트에 포함하지 않음**
  - **LLM 호출**: Claude API로 **프로파일당 1회** 한글 복약안내 생성 (총 1,000~3,000회 — 단일제 500~1,500 + compound 500~1,500)
    - A4 상세: 작용기전, 적응증, 약동학, 안전성 프로필, 임상근거, 용법 → `터울복약안내A4`에 저장
    - A5 간략: 약효설명(1-2문장), 핵심 주의사항 → `터울복약안내A5`에 저장
    - 매핑: `터울프로파일A4매핑`, `터울프로파일A5매핑` 생성
  - **필터 적용** (프로파일 생성 시 이미 적용됨):
    - `target_organism = 'Homo sapiens'` 필터 (MoA)
    - `retraction_status = 'retracted'` 필터 (문헌)
    - `association_score >= 0.3` 필터 (질병 연관)
    - `edb_data_conflict`에서 `resolution = 'unresolved'`인 데이터 제외
  - **비정규화**: 프로파일 LLM 결과 → `터울주성분.약효설명_new`, 요약 컬럼들에 복사
  - **상태 업데이트**: enrichment_status = 'llm_generated'
- [ ] `generate_yakho_desc.py` 작성: 신규 DB의 `터울약효설명` 테이블을 LLM으로 신규 생성
  - 기존 터울약효설명 구조(터울버전, EnglishText 등)를 유지하되 내용은 enrichment 데이터 기반 신규 작성
  - 기존 11,100건 + enrichment로 추가 커버 가능 건 → 최대 커버리지 목표
- [ ] LLM 프롬프트 템플릿 설계 (A4용, A5용 각각 + **compound 전용 3-tier 템플릿**)
  - 프롬프트에 출력 형식 명시 (A4: section_type별 블록, A5: 간략 1-2문장)
  - **프롬프트에 기존 텍스트 미포함 — enrichment 구조화 데이터만 입력**
  - safety 섹션은 FDA label 원문 기반으로 정확성 강조
  - 한글 의약 용어 일관성 가이드 포함
  - **compound 프롬프트 tier별 입력 전략**:
    - Small (Tier 2-3, 2-9성분): 전체 enrichment, 4-8K tokens
    - Medium (Tier 4, 10-15성분): 요약 enrichment, 6-10K tokens
    - Large (Tier 5, 16+성분): 카테고리 기반, 4-8K tokens
- [ ] 파일럿: 대표 **프로파일 15건**(단일제 + 5-tier별 각 1건)으로 LLM 생성 품질 검증 (SF-4)
  - 단일제: 대형(50+ 성분) 2건 + 중형(10-50) 5건 + 소형(1-10) 3건
  - **Tier 1**: 1성분 복합제 코드 → 단일제 프로파일 매핑 검증
  - **Tier 2**: 2-3성분 복합 진통제 (예: acetaminophen+codeine)
  - **Tier 3**: 4-6성분 종합감기약
  - **Tier 4**: 10-12성분 종합비타민
  - **Tier 5**: 16+성분 대형 비타민/TPN
  - 전문가 약사 검토 → 프롬프트 튜닝
- [ ] 텍스트그램 프로파일 매핑: `터울프로파일텍스트그램매핑` 생성
  - 기존 텍스트그램 데이터를 프로파일 기반으로 재매핑
- [ ] Safety 전문가 검증 (Layer 3): Tier 1+2 전수, Tier 3 샘플 50건+
  - safety `section_type`('interaction', 'contraindication', 'monitoring') → `validation_status = 'draft'`
  - 검증 완료 시 `validation_status = 'expert_reviewed'`
- [ ] 검증 완료 건 `enrichment_status = 'expert_reviewed'`로 승격
- [ ] 전체 프로파일 대상 일괄 LLM 생성
- [ ] A4/A5 출력 템플릿 구현 (HTML/PDF)

**수락 기준**:
- 파일럿 10개 프로파일 출력물 전문가 승인
- LLM 생성 복약안내의 의학적 정확성 >= 95% (전문가 샘플 검토)
- Safety Tier 1+2 전수 검증 완료, Tier 3 precision >= 90%
- Publication Gate 위반 건수 = 0
- 프로파일 100% LLM 생성 완료
- 신규 DB 터울주성분의 enrichment_status = 'expert_reviewed' 이상인 건 >= 3,000
- 신규 DB 터울약효설명 테이블 신규 생성 완료
- **LLM 총 호출 수 <= 3,000 (단일제 <= 1,500 + 복합제 <= 1,500)**
- **Tier 2-5 compound profile 100% LLM 생성 완료**

---

## 8. 4-Layer Validation Architecture (품질 보증)

> Architect 제안에 따라 4단계 검증 아키텍처로 재설계. Safety 데이터는 Principle #1(안전 데이터 무오류)에 따라 risk-tiered 전문가 검증 적용.

### Layer 1: 자동 무결성 검증 (Automated Integrity)

모든 enrichment 데이터에 대해 파이프라인 실행 시 자동으로 수행.

| 검증 항목 | 방법 | 기준 | 실패 시 |
|----------|------|------|---------|
| **FK 정합성** | 모든 enrichment 테이블의 심평원성분코드가 터울주성분에 존재 | 100% | INSERT 거부 |
| **중복 방지** | UNIQUE constraint 위반 건수 | 0건 | ON CONFLICT 처리 |
| **NULL 비율** | 핵심 필드(action_type, disease_name, pmid 등)의 NULL 비율 | <= 10% | 경고 로그 + 리포트 |
| **출처 추적** | source, source_id, fetched_at 모두 채워진 건 | >= 99% | INSERT 거부 |
| **PMID 유효성** | PubMed API로 전수 PMID 존재 확인 | = 100% | 무효 PMID 제거 |
| **Retraction 필터** | `retraction_status = 'retracted'`인 문헌이 content_block에 미포함 | 0건 포함 | 자동 제외 |
| **OT Score 필터** | `association_score < 0.3`인 drug_disease 레코드 미저장 | 0건 저장 | INSERT 차단 |
| **MoA 출력 필터** | content_block의 mechanism 섹션에 `target_organism != 'Homo sapiens'` 미포함 | 0건 포함 | 자동 제외 |

**자동 검증 통과 시**: `validation_status = 'auto_validated'`로 승격.

### Layer 2: 매핑 정확도 검증 (Mapping Accuracy)

ChEMBL 매핑과 enrichment 데이터의 정확성을 수동 샘플링으로 검증.

| 검증 항목 | 방법 | 기준 | 실패 시 |
|----------|------|------|---------|
| **ChEMBL 매핑 (exact)** | exact_name match 건 100건 수동 검토 | precision >= 95% | 매핑 로직 재검토 |
| **ChEMBL 매핑 (synonym)** | confidence < 0.95인 건 50건 수동 검토 | precision >= 85% | synonym 로직 강화 |
| **MoA 정확도** | 매핑된 MoA 50건 수동 검토 (성분명-target-action_type 일치) | precision >= 90% | 필터 조건 강화 |
| **미매핑 건** | 미매핑 성분의 패턴 분석 (복합제, 한방제, 생약 등) | 원인 분류 리포트 | fallback 전략 수립 |

### Layer 3: Safety 데이터 Risk-Tiered 전문가 검증

> **Principle #1 적용**: 환자 안전 직결 데이터는 severity 기반 차등 검증. 전문가 검증 미완료 safety 데이터는 출력물에 포함 불가.

| Risk Tier | 대상 | 검증 방법 | 기준 |
|-----------|------|----------|------|
| **Tier 1 (Critical)** | `severity = 'critical'` **또는** `info_type = 'black_box_warning'` | **전수 전문가 검토** | 100% 정확 (오류 0건) |
| **Tier 2 (Severe)** | `severity = 'severe'` **AND** `info_type IN ('contraindication', 'interaction')` | **전수 전문가 검토** | 100% 정확 (오류 0건) |
| **Tier 3 (Standard)** | 그 외 모든 safety 레코드 (`severity IN ('moderate', 'mild')` 또는 `info_type = 'adverse_effect'`) | **50건 이상 Stratified 샘플** | precision >= 90% |

**검증 절차**:
1. Tier 1+2: 전수 목록을 CSV로 추출하여 약사/의사 전문가에게 제공
2. 전문가는 각 건에 대해 `correct` / `incorrect` / `uncertain` 판정
3. `incorrect` 건은 즉시 삭제 또는 수정, `uncertain` 건은 2차 검토
4. Tier 3: Stratified sampling — severity별, info_type별 균등 배분으로 50건 이상 추출
5. Tier 3 precision < 90%이면 해당 source의 전체 safety 데이터 재검토

**검증 통과 시**: 해당 성분의 safety content_block을 `validation_status = 'expert_reviewed'`로 승격.

**검증 미완료 시**: `validation_status = 'draft'` 유지 → 출력물에서 safety 섹션 제외 (다른 섹션은 포함 가능).

### Layer 4: 출력물 검증 + Cross-validation (Phase 2)

| 검증 항목 | 방법 | 기준 |
|----------|------|------|
| **A4 완전성** | 전문가 약사 3인 검토 (샘플 20건) | 핵심 정보 누락 0건 |
| **A5 가독성** | 비전문가 5인 검토 (샘플 10건) | 이해 가능성 >= 80% |
| **데이터-포맷 일치** | enrichment 테이블 ↔ 출력물 대조 (자동화) | 100% 일치 |
| **빈 섹션 처리** | 데이터 없는 섹션이 올바르게 생략되는지 | 빈 섹션 0개 노출 |
| **Publication Gate 준수** | `validation_status != 'expert_reviewed'`인 safety 블록이 출력물에 미포함 | 0건 위반 |
| **소스 충돌 해소** | `edb_data_conflict`에서 `resolution = 'unresolved'`인 건이 출력물에 미포함 | 0건 위반 |
| **LLM 복약안내 정확성** | LLM 생성 문구의 의학적 정확성 (전문가 샘플 50건) | precision >= 95% |

#### Cross-validation (소스 간 교차 검증)

1. **ChEMBL ↔ Open Targets**: 동일 성분에 대해 두 소스의 MoA/indication 비교. 불일치 시 `edb_data_conflict`에 기록하고, curated data(ChEMBL) 우선 원칙 적용.
2. **ChEMBL ↔ FDA label**: MoA/indication 정보가 FDA label의 indications_and_usage와 일치하는지 교차 확인. FDA label 우선.
3. **문헌 ↔ Safety**: safety 레코드의 근거 PMID가 edb_literature에 존재하는지 확인. 근거 문헌 없는 safety 건은 `evidence_level` 하향 조정.
4. **LLM 생성 ↔ Enrichment 원본**: LLM 생성 복약안내가 enrichment 데이터의 핵심 정보(BBW, critical 상호작용 등)를 누락하지 않았는지 샘플 50건 비교. (**주의**: 기존 터울약효설명/팜포트 텍스트와의 비교는 하지 않음 — LLM은 enrichment 데이터만으로 독립 생성)

---

## 9. 신규 주성분코드 자동 Enrichment Flow

### 9.1. 트리거 조건

`터울주성분` 테이블에 신규 심평원성분코드가 추가될 때, 해당 코드에 대해 enrichment 파이프라인이 자동 실행되어야 한다.

**감지 방법**: `edb_enrichment_status` 테이블에 없는 심평원성분코드를 주기적으로 탐지

```
터울주성분 (전체) - edb_enrichment_status (등록된) = 미등록 신규 코드
```

### 9.2. 신규 코드 처리 Flow (프로파일 기반 — Iteration 9)

```
[1] 신규 코드 감지
    └─ enrich_new_ingredient.py --detect
    └─ 터울주성분 LEFT JOIN edb_enrichment_status → NULL인 건 = 신규

[2] 코드 구조 분석
    └─ 5-6자리(YY) 확인: 단일제(01~) / 복합제(00) / 터울수집(TL)
    └─ 7자리(Z) 확인: 투여경로 (A/B/C/D)
    └─ 1-4자리 확인: 동일 주성분의 기존 enrichment 존재 여부

[3] 기존 enrichment 재활용 판단
    ├─ CASE A: 동일 주성분(1-4자리)의 enrichment가 이미 존재
    │   └─ 약리학 데이터(MoA, ADMET, 질병, 문헌, 임상시험) → 기존 결과 복사
    │   └─ FDA label → 투여경로가 동일하면 복사, 다르면 신규 호출
    │   └─ FAERS → 투여경로 확인 후 복사 또는 신규 호출
    │
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
    │
    └─ CASE C: 완전 신규 주성분 (1-4자리 자체가 새로움)
        └─ 전체 enrichment 파이프라인 실행 (Step 1~8)

[4] Enrichment 실행
    └─ enrich_new_ingredient.py --run
    └─ CASE별 최적화된 파이프라인 실행
    └─ edb_enrichment_status에 등록 + 진행 상태 추적

[5] ★ 프로파일 매칭 (Principle #9 + #10 — 핵심 변경)
    └─ 단일제 코드 → 기존 단일제 프로파일 매칭 (변경 없음):
    │   └─ enrichment 결과에서 6개 키 필드 추출 → 정규화 → SHA-256 = profile_hash
    │   └─ 기존 터울복약프로파일에서 동일 profile_hash 검색
    │
    └─ 복합제 코드 Tier 1 → 단일제 프로파일 매칭 (신규)
    └─ 복합제 코드 Tier 2-5 → compound profile 매칭 (신규):
    │   └─ 구성 성분 식별 (3단계 fallback) → 코드 정렬 → SHA-256 = constituent_hash
    │   └─ 기존 터울복약프로파일에서 동일 constituent_hash 검색
    │
    ├─ MATCH (기존 프로파일 존재): ★ LLM 호출 0회 ★
    │   └─ 터울주성분프로파일매핑에 신규 성분 추가
    │   └─ 기존 프로파일의 복약안내(A4/A5/텍스트그램) 자동 적용
    │   └─ 터울주성분 비정규화 컬럼(약효설명_new, 요약) 복사
    │   └─ enrichment_status = 'llm_generated' (이미 검증된 프로파일이면 'expert_reviewed')
    │
    └─ NO MATCH (신규 프로파일 필요): LLM 호출 1회
        └─ 터울복약프로파일에 신규 프로파일 INSERT (profile_type에 따라 single/compound)
        └─ LLM으로 A4/A5 복약안내 생성 → 터울복약안내A4/A5에 저장
        │   (compound인 경우 tier별 입력 전략: Small/Medium/Large)
        └─ 터울프로파일A4/A5매핑 생성
        └─ 터울주성분프로파일매핑에 성분 추가
        └─ compound인 경우 터울복합프로파일구성에 구성 관계 기록
        └─ enrichment_status = 'llm_generated'

[6] 검증
    └─ Layer 1 자동 무결성 검증 (즉시)
    └─ 프로파일 매칭된 경우: 기존 검증 결과 자동 계승 (추가 검증 불필요)
    └─ 신규 프로파일인 경우:
        └─ Safety 데이터 → validation_status = 'draft' (전문가 검증 대기)
        └─ 비-Safety 데이터 → Layer 1 통과 시 'auto_validated'

[7] 알림
    └─ 신규 성분 enrichment + 프로파일 매칭 결과 리포트 출력
    └─ 기존 프로파일 매칭 시: "프로파일 #X에 매핑됨 (LLM 호출 불필요)"
    └─ 신규 프로파일 시: Safety 전문가 검증 대기 목록에 추가
```

> **프로파일 매칭의 효과**: 신규 성분의 enrichment 결과가 기존 성분과 동일한 경우(같은 약효군의 변형 — 함량/제형 차이, 동일 계열 신약 등), LLM 호출 없이 즉시 복약안내를 적용할 수 있다. 실제로 심평원성분코드의 구조상 동일 주성분(1-4자리)의 단일제 변형은 enrichment 결과가 동일할 가능성이 매우 높다.

### 9.3. 실행 모드

| 모드 | 명령 | 설명 |
|------|------|------|
| **감지만** | `python enrich_new_ingredient.py --detect` | 미등록 코드 목록 출력 |
| **단건 실행** | `python enrich_new_ingredient.py --run --code 101340BIJ` | 특정 코드 1건 enrichment |
| **전체 신규** | `python enrich_new_ingredient.py --run --all-new` | 미등록 전체 일괄 처리 |
| **dry-run** | `python enrich_new_ingredient.py --run --all-new --dev` | dev DB에서 테스트 |
| **cron** | `0 2 * * * python enrich_new_ingredient.py --run --all-new` | 매일 새벽 2시 자동 실행 |

---

## 10. 파일 구조

```
pharmport/
├── common.py                       # (기존) DB 연결
├── embedding_service.py            # (기존) 임베딩 서비스
├── sort_and_embed.py               # (기존) 정렬+임베딩
├── match_ingredient.py             # (기존) Method 1
├── match_ingredient_v2.py          # (기존) Method 2
├── analysis.py                     # (기존) 분석
├── enrich_base.py                  # [신규] enrichment 공통 모듈 (rate limit, 상태 관리, Layer 1 자동 검증)
├── enrich_chembl.py                # [신규] Phase 1-A: ChEMBL 매핑 + MoA + ADMET
├── enrich_fda.py                   # [신규] Phase 1-B: openFDA 라벨+FAERS (Safety Ground Truth)
├── enrich_opentargets.py           # [신규] Phase 1-B: Open Targets 질병-타겟 (score >= 0.3 필터)
├── enrich_pubmed.py                # [신규] Phase 1-B: PubMed 문헌 수집 (retraction 필터 포함)
├── enrich_trials.py                # [신규] Phase 1-B: ClinicalTrials.gov
├── enrichment_report.py            # [신규] Phase 1-C: 커버리지 + 정확도 리포트 + 충돌 감지
├── build_profiles.py               # [신규] Phase 1.5: Enrichment 프로파일 해싱 + 클러스터링 + 단일제(Step A)/복합제 5-tier(Step B) + 매핑
├── generate_content.py             # [신규] Phase 2: content_block 생성 (Publication Gate 적용)
├── create_enrichment_tables.py     # [신규] Phase 0: DDL 실행 (9개 edb_ 테이블, 기존 DB)
├── create_v2_tables.py             # [신규] Phase 2-A: 신규 DB(teoul_pharminfo_v2) 테이블 생성 + 마이그레이션
├── generate_medication_guide.py    # [신규] Phase 2-B: 프로파일 단위 LLM 복약안내 생성 (enrichment only)
├── generate_yakho_desc.py          # [신규] Phase 2-B: 신규 DB 터울약효설명 LLM 신규 생성
├── enrich_new_ingredient.py        # [신규] 신규 주성분코드 자동 감지 + enrichment + 프로파일 매칭 (Section 9)
└── docs/
    ├── methodology.md              # (기존)
    ├── unmatched-recovery.md       # (기존)
    ├── enrichment-methodology.md   # [신규] enrichment 방법론 문서
    └── llm-prompt-templates.md     # [신규] LLM 복약안내 프롬프트 템플릿 (A4/A5, 단일제/복합제 3-tier(Small/Medium/Large))
```

신규 파일 **15개**, 기존 파일 수정 **1개** (`common.py`에 `get_v2_connection()` 추가, `.env`에 환경변수 3개 추가)

---

## 11. 예상 수치 요약

| 항목 | 보수적 | 낙관적 | 근거 |
|------|--------|--------|------|
| ChEMBL 매핑 성분 수 | 3,000 | 6,000 | approved drug 비율, 성분명 매칭률 |
| MoA 보유 성분 | 2,000 | 5,000 | ChEMBL curated MoA 커버리지 |
| ADMET 보유 성분 | 2,500 | 5,500 | 구조 데이터 기반 계산 속성 |
| **FDA label 매핑 성분** | **2,000** | **4,000** | **US 승인약 기준, INN/USAN 매핑률** |
| **FDA BBW 보유 성분** | **200** | **500** | **boxed warning 대상 약물 비율** |
| 질병 연관 쌍 | 5,000 | 15,000 | 성분당 평균 2-3개 적응증 |
| 문헌 레코드 | 10,000 | 30,000 | 성분당 평균 3-5건 |
| 임상시험 보유 성분 | 1,500 | 3,000 | major drug 위주 |
| A4 출력 가능 성분 | 2,000 | 5,000 | 2개 이상 섹션 enrichment 보유 기준 |
| A5 출력 가능 성분 | 3,000 | 6,000 | 1개 이상 섹션 enrichment 보유 기준 |
| **복합제 코드 수 (전체 YY='00')** | **7,791** | **7,791** | **전체 복합제. 기존 20,226건의 38.5%** |
| **Tier 1 (1성분 복합제)** | **~1,000** | **~1,400** | **단일제 프로파일 공유 → 추가 profile 0개** |
| **Tier 2-5 (2+성분 복합제)** | **~6,391** | **~6,791** | **compound profile 대상** |
| **구성 성분 단일제 코드 존재율** | **93%** | **97%** | **96% 평균. "코드 존재"이며 enrichment 완료와 별개 (SF-1)** |
| **구성 성분 식별 성공률** | **95%** | **98%** | **3단계 fallback 알고리즘** |
| **Compound profile 수 (추정)** | **500** | **1,500** | **동일 성분 코드 조합 중복 제거** |
| **단일제 profile 수** | **500** | **1,500** | **동일 enrichment 결과 그룹 수 (기존)** |
| **총 프로파일 수** | **1,000** | **3,000** | **단일제 + 복합제** |
| **LLM 복약안내 생성 대상** | **1,000** | **3,000** | **프로파일 단위 생성 — 프로파일당 1회 호출 (A4+A5 동시)** |
| **LLM API 호출 예상** | **~1,000** | **~3,000** | **기존 20,000→1,000~3,000으로 축소 (프로파일 기반 재활용)** |
| **프로파일당 평균 매핑 성분 수 (단일제)** | **~8** | **~24** | **12,429 ÷ 단일제 프로파일 수** |
| **프로파일당 평균 매핑 성분 수 (복합제)** | **~4** | **~13** | **6,591 ÷ compound 프로파일 수** |
| **신규 DB 터울주성분 완성 건수** | **3,000** | **6,000** | **enrichment 데이터 보유 성분 = LLM 품질 보장 가능 건** |

---

## 12. Success Criteria (성공 기준)

1. Phase 1 완료 시 ChEMBL 매핑 성분 >= 3,000개
2. 매핑된 성분의 80% 이상이 MoA 또는 indication 데이터 보유
3. 모든 enrichment 데이터에 출처(source + source_id + fetched_at) 기록
4. Phase 2 진입 시 커버리지 + 정확도 리포트 기반 섹션 포함/제외 결정 완료
5. **Safety Tier 1+2 전수 전문가 검증 완료, Tier 3 precision >= 90%**
6. **최종 출력물에 `validation_status = 'expert_reviewed'`인 safety 블록만 포함 (Publication Gate 준수)**
7. **Retracted article이 출력물에 포함된 건수 = 0**
8. **소스 간 충돌 미해소(`unresolved`) 건이 출력물에 포함된 건수 = 0**
9. A4/A5 샘플 출력물 사용자 승인
10. 기존 팜포트 데이터(40,837건) 무변경 보존
11. 기존 매칭 시스템(v2/v3)과 독립적으로 동작 (파이프라인 간 의존성 없음)
12. **신규 DB(teoul_pharminfo_v2)의 터울주성분에 20,235건 마이그레이션 + enrichment 통합 완료**
13. **LLM 생성 복약안내의 의학적 정확성 >= 95% (전문가 샘플 검토 기준)**
14. **기존 DB(teoul_pharminfo) 무변경 유지 (edb_ 테이블 추가만)**
15. **신규 DB 터울약효설명 테이블 LLM 신규 생성 완료**
16. **DATABASE_NAME 변경만으로 앱 전환 + 즉시 롤백 가능 검증 — 호환 뷰(`터울주성분A4/A5복약안내매핑`) 경유 시 기존 앱 쿼리 결과셋 동일 확인. `터울복약안내A4`/`A5`의 호환 컬럼(`터울버전`, `분류`, `EnglishText`) 정상 반환 검증**
17. **Enrichment 프로파일 생성 완료 — 전체 enriched 성분(단일제 + 복합제 7,791건 전체)이 프로파일에 매핑 (누락 0건)**
18. **동일 프로파일 내 성분들의 복약안내 텍스트 일치율 = 100% (구조적 보장)**
19. **LLM 호출 수 <= 3,000회 (단일제 <= 1,500 + 복합제 <= 1,500, 기존 20,000 대비 85~95% 절감)**
20. **신규 성분 추가 시 기존 프로파일 매칭 → 0회 LLM 호출로 복약안내 자동 매핑 검증**
21. **복합제 7,791건 전체가 Tier 분류 완료 (누락 0건)**
22. **Tier 1 복합제 100% 단일제 프로파일에 매핑**
23. **Tier 2-5 복합제 100% compound profile에 매핑 (누락 0건)**
24. **compound profile LLM 생성 복약안내에 복합 맥락(목적, 성분 간 상호작용) 포함 확인 (5-tier 파일럿 전문가 검토)**
25. **동일 성분 코드 조합 복합제의 constituent_hash 일치율 = 100% (구조적 보장)**
26. **구성 성분 식별 성공률 >= 95%**
27. **constituent_hash는 성분 코드만으로 생성 — enrichment/profile 버전 변경으로 hash가 변하지 않음을 검증**

---

## 13. Guardrails

### Must Have
- 모든 enrichment 레코드에 provenance (source, source_id, fetched_at)
- API rate limit 준수 (ChEMBL, NCBI, ClinicalTrials.gov, openFDA)
- dry-run 모드 우선 실행
- enrichment_status로 진행 상태 추적 (재시작 가능)
- 기존 DB(teoul_pharminfo) 테이블 구조 무변경 (edb_ 테이블 추가만)
- **Safety 데이터 risk-tiered 전문가 검증 (Tier 1+2 전수, Tier 3 n>=50)**
- **Publication Gate: `validation_status = 'expert_reviewed'`인 safety 블록만 출력물 포함**
- **Retracted article 자동 필터링 (출력물 포함 0건)**
- **Open Targets `association_score >= 0.3` 최소 임계값**
- **MoA 출력 시 `target_organism = 'Homo sapiens'` 필터**
- **소스 간 충돌 감지 → `edb_data_conflict`에 기록 → 해소 후 출력물 포함**
- **Phase 2 진입에 정확도 지표 전부 Pass 필수**
- **신규 DB(teoul_pharminfo_v2) 터울주성분에 기존 컬럼 완전 마이그레이션 (데이터 일치 검증)**
- **LLM 생성 복약안내는 반드시 전문가 검증 후 published (Principle #7)**
- **LLM 프롬프트에 기존 텍스트 일절 미포함 — enrichment 데이터만 입력 (Principle #7)**
- **신규 DB는 기존 서비스와 동일 테이블명 사용 — DATABASE_NAME 변경만으로 전환 가능 (Principle #8)**
- **프로파일 해시는 6개 필드(mechanism, side_effects, contraindications, interactions, monitoring, special_pop) 정규화 후 SHA-256 생성 (Principle #9)**
- **프로파일 단위 LLM 생성 — 동일 프로파일 성분은 반드시 동일 복약안내 텍스트 공유 (Principle #9)**
- **신규 성분 등록 시 기존 프로파일 매칭 우선 시도 → 불일치 시에만 신규 LLM 호출 (Principle #9)**
- **복합제 7,791건 전체를 5-tier로 분류하여 처리 (4+성분만 다루지 않음) (Principle #10)**
- **compound constituent_hash는 구성 성분 심평원성분코드 정렬+concat+SHA-256으로 생성 (enrichment/profile 버전 무관) (MF-2)**
- **구성 성분 식별에 3단계 fallback 알고리즘 적용 (ProductInfos → 텍스트 파싱 → base 룩업) (MF-3)**
- **compound profile LLM 프롬프트에 tier별 입력 전략 적용 (Small/Medium/Large) (MF-4)**
- **Step B(복합제 프로파일링)는 Step A(단일제 프로파일링) 완료 후에만 착수 (SF-3)**
- **구성 성분 중 단일제 enrichment 미완료 건은 해당 성분 Phase 1 enrichment 완료 후 compound profiling 진행**
- **`needs_regeneration` 플래그로 구성 성분 enrichment 변경 시 compound profile 재생성 추적**

### Must NOT Have
- 기존 DB(teoul_pharminfo)의 pharmport_medicine, 터울주성분 등 기존 테이블에 컬럼 추가 또는 데이터 변경 (edb_ 신규 테이블 추가만 허용)
- 기존 29,196건 매칭 결과 변경
- API key/credential의 코드 하드코딩 (모든 키는 `.env`에서 로드, `common.py` 패턴 준수)
- enrichment 데이터를 기존 서비스 테이블에 직접 저장
- Phase 1 커버리지 + 정확도 리포트 없이 Phase 2 착수
- **전문가 검증 미완료 safety 데이터의 출력물 포함**
- **`retraction_status = 'retracted'`인 문헌의 출력물 포함**
- **`resolution = 'unresolved'`인 충돌 데이터의 출력물 포함**
- **LLM 생성 복약안내를 전문가 검증 없이 published 상태로 전환**
- **기존 DB(teoul_pharminfo) DROP 또는 구조 변경**
- **LLM 프롬프트에 기존 터울약효설명/팜포트 텍스트 포함 (enrichment 데이터만 입력)**
- **프로파일 무시한 성분 단위 개별 LLM 호출 (프로파일 시스템 우회 금지)**
- **프로파일 해시 생성 시 정규화 미적용 (정렬+소문자+strip 필수)**
- **복합제에 대해 구성 성분 단일제 프로파일의 기계적 합산(union)으로 복약안내 생성 (compound 전용 LLM 호출 필수)**
- **복합제 구성 성분 파싱 없이 복합제 심평원성분코드를 단일제와 동일하게 처리**
- **compound hash를 구성 성분의 profile_hash에 의존하여 생성 (cascade invalidation 위험) (MF-2)**
- **Tier 4-5(10+성분)에 전체 enrichment를 LLM에 전달 (토큰 예산 초과 위험) (MF-4)**

---

## Changelog

### Iteration 10 (2026-03-20) — 복합제(Compound Drug) Profile 전략

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

### Iteration 11 (2026-03-20) — Critic Re-Review: 호환 뷰, 매핑 테이블, edb_content_block 폐기, 이중언어 전략

| # | 피드백 | 변경 내용 | 영향 범위 |
|---|--------|----------|----------|
| **53** | [필수] Critic MUST-FIX 1: Principle #8 호환 뷰 누락 | Section 3.7 "호환 뷰 정의" 신규 추가. `터울주성분A4/A5복약안내매핑` 호환 VIEW DDL, `터울복약안내A4/A5`에 호환 컬럼(`터울버전`, `분류`, `IsDeleted`, `ModifiedBy`, `EnglishText`, `픽토그램Code`) 추가. `section_type_to_분류()` 함수. Phase 2-A에 호환 뷰 DDL 태스크 추가. Success Criteria #16 업데이트. 시간제한(Phase 3 이후 DROP) 명시 | Section 3.7(신규), 7(Phase 2-A), 12(#16), ADR |
| **54** | [필수] Critic MUST-FIX 2: field_type→section_type 매핑 없음 | Section 5.2.1 "PharmPort field_type → EDB section_type 매핑" 신규 추가. 기존 3종(precautions, red_box_text, dosage) → 신규 6종의 개념적 대응 + 시각적 매핑 + 핵심 차이점 4가지 | Section 5.2.1(신규) |
| **55** | [권장] Critic SHOULD-FIX 3: edb_content_block 역할 미정의 | edb_content_block deprecated 선언. Section 3.1 폐기 주석, Section 2.3 참조 수정. Phase 0 DDL 실행하되 데이터 미적재, Phase 2 완료 후 DROP | Section 3.1(주석), 2.3(참조), ADR |
| **56** | [권장] Critic SHOULD-FIX 4: 이중언어 생성 전략 미정의 | Section 5.2.0 "이중 언어 생성 전략" 신규. English-first → DeepL 한글 번역 → 안전 관련 section_type은 LLM 한글 보정 필수 | Section 5.2.0(신규) |
| **57** | Architect: Option A 라벨 부정확 | "정규화 DB" → "데이터/개념 재활용형 신규 DB"로 변경 | RALPLAN-DR Option A 제목 |
| **58** | Architect: 시간제한 호환 뷰 | 호환 뷰를 Phase 3(전환 후 30일) 이후 DROP 예정으로 시간 제한. 앱이 네이티브 프로파일 쿼리로 전환 완료 시 제거 | Section 3.7.5 |

### Iteration 9 (2026-03-20) — Enrichment 프로파일 기반 복약안내 재활용 아키텍처

| # | 피드백 | 변경 내용 | 영향 범위 |
|---|--------|----------|----------|
| **38** | 사용자: 동일 Enrichment 결과 재활용 | 동일한 enrichment 수집 결과(작용기전, 부작용, 금기, 상호작용, 모니터링, 특수환자군)를 가진 성분들은 동일 복약안내를 공유. SHA-256 프로파일 해시 기반 그룹핑. Principle #9 신규 추가 | Principle #9, ADR, Section 3.2, 3.3, 3.4, 3.5, 4.9, 5, 6, 7, 9, 10, 11, 12, 13 전면 |
| **39** | 프로파일 시스템 테이블 DDL | `터울복약프로파일`(profile_hash + 6개 배열 필드 + JSONB), `터울주성분프로파일매핑`(심평원성분코드↔profile_id) DDL 추가. 복약안내 테이블(`터울복약안내A4/A5`)과 프로파일 매핑 테이블(`터울프로파일A4매핑/A5매핑`) 분리 설계 | Section 3.2, 3.3 신규 |
| **40** | Phase 1.5 프로파일 클러스터링 | Phase 1-C(리포트)와 Phase 2-A(신규 DB) 사이에 Phase 1.5 삽입. `build_profiles.py`로 enrichment 결과 정규화 → SHA-256 해싱 → 프로파일 생성 → 성분 매핑. 로드맵 Day 14-15 할당 | Section 4.9 신규, Section 7 로드맵, Section 10 파일 구조 |
| **41** | LLM 호출 20,000→500~1,500 축소 | 성분 단위 → 프로파일 단위 LLM 생성으로 전환. 프로파일당 1회 호출(A4+A5 동시), 동일 프로파일 성분은 0회 추가 호출. 예상 수치 전면 업데이트 | Section 5, 11 예상 수치 |
| **42** | 신규 성분 프로파일 매칭 | Section 9 신규 주성분 Flow에 Step 5(프로파일 매칭) 추가. MATCH(기존 프로파일 발견 → 0회 LLM) / NO MATCH(신규 프로파일 → 1회 LLM) 분기 | Section 9.2 Step 5-7 |
| **43** | 터울주성분 DDL 간소화 | JSONB 복약안내_a4/a5 컬럼을 별도 테이블로 분리(터울복약안내A4/A5). 터울주성분에는 profile_id, profile_hash(denormalized), enrichment_status에 'profiled' 상태 추가만 유지 | Section 3.4 |

### Iteration 8 (2026-03-19) — 기존 DB 참조 완전 제거 + 동일 테이블명 별도 DB 아키텍처

| # | 피드백 | 변경 내용 | 영향 범위 |
|---|--------|----------|----------|
| **33** | 사용자: 기존 DB 참조 완전 제거 | LLM 복약안내 생성 시 기존 터울약효설명/팜포트 텍스트를 **일절 참조하지 않음**. enrichment 구조화 데이터(ChEMBL, FDA, Open Targets, PubMed 등)만으로 LLM에 입력. Principle #7 강화, Section 1.4/5.4/6/7/8/13 전면 수정 | Principle #7, Section 1.1, 1.4, 5.4, 6.2→6.3, 7 Phase 2-B, 8 Layer 4, 13 Guardrails |
| **34** | 사용자: 동일 테이블명 별도 DB | 별도 DB(`teoul_pharminfo_v2`)에 **기존 서비스와 동일 테이블명**(터울주성분, 터울약효설명 등)으로 생성. 앱에서 `DATABASE_NAME` 환경변수만 변경하면 전환 가능. 롤백도 환경변수 복원으로 즉시. Principle #8 신규 추가 | Principle #8 신규, Section 3 전체, 3.2, 3.4, 6 전면 재작성, 7 Phase 0/2-A, 10, 12, 13 |
| **35** | `터울주성분_new` → `터울주성분` (신규 DB) | 기존 `터울주성분_new`를 폐기. 대신 신규 DB에 `터울주성분`(동일 이름)을 생성하여 앱 호환성 보장. DDL, 인덱스명, 파일명(`create_v2_tables.py`) 변경 | Section 3.2 DDL, 인덱스명, 파일 구조 (14개), Success Criteria (16개) |
| **36** | 터울약효설명 신규 생성 | 신규 DB의 `터울약효설명` 테이블을 LLM이 enrichment 데이터로 완전 신규 생성 (기존 2,670건 텍스트 미복사). `generate_yakho_desc.py` 신규 파일 추가 | Section 6.1, 6.3, Phase 2-B, 파일 구조, Success Criteria #15 |
| **37** | 환경변수 + common.py | `V2_DATABASE_NAME=teoul_pharminfo_v2` 환경변수 추가, `common.py`에 `get_v2_connection()` 함수 추가. edb_는 기존 DB, LLM 결과는 신규 DB에 저장 | Section 2, 7 Phase 0, 파일 구조 |

### Iteration 7 (2026-03-19) — 실제 레이아웃 반영 + "Why+What+Who" 원칙 + JSONB 문장형

| # | 피드백 | 변경 내용 | 영향 범위 |
|---|--------|----------|----------|
| **28** | 사용자: 복약안내 퀄리티 비교 | 기존 PharmPort vs 신규 EDB 복약안내 텍스트 퀄리티 분석 수행. 기존의 강점(환자 친화 문체, 100% 커버리지)과 한계(텍스트 재활용, 작용기전 부재, 근거 없음, A5 54.9%) 정량 확인 | 분석 결과 → Section 5.2~5.4 설계에 반영 |
| **29** | 사용자: JSONB 예시가 키워드 나열형 | 복약안내_a4 JSONB 예시를 키워드 나열에서 **환자용 문장형**으로 전면 재작성. "간독성 주의. 1일 최대 4g 초과 금지" → "간에서 대사되는 약이므로 1일 최대 4g을 초과하지 마십시오. 과량 복용 시 간 손상이 발생할 수 있습니다." | Section 3.2 JSONB 예시 |
| **30** | 사용자: 실제 A5/A4 이미지 기반 레이아웃 | A5(badge+[약효설명]+주의사항 1줄)와 A4([약효설명]+badge+(병원처방용법) 블록)의 실제 레이아웃을 ASCII 다이어그램으로 문서화. 기존→신규 변경점을 구체적 예시로 비교 | Section 5.3 (A5), 5.4 (A4) 신규 작성 |
| **31** | "Why+What+Who" 문장 생성 원칙 | LLM이 생성하는 모든 복약안내에 **원인(기전)+증상+대상 환자군**을 포함하는 원칙 정의. 기존 "what only"와 신규 "why+what+who" 비교표 포함. LLM 프롬프트 가이드라인 4조항 | Section 5.2 신규 |
| **32** | TOC + 섹션 번호 업데이트 | 5.2→문장생성원칙, 5.3→A5, 5.4→A4, 5.5→분류/픽토그램으로 재배정. TOC 및 앵커 링크 업데이트 | TOC, Section 5 전체 |

### Iteration 6 (2026-03-19) — 터울주성분_new 통합 테이블 + LLM 복약안내 생성

| # | 피드백 | 변경 내용 | 영향 범위 |
|---|--------|----------|----------|
| **23** | 사용자: 복약안내 문구 새로 생성 | 기존 텍스트 재활용 → LLM(AI) 기반 신규 생성으로 전환. enrichment 데이터를 LLM에 입력하여 자연스러운 한글 복약안내 작성. 기존 텍스트는 참고자료로만 활용 | Principle #7, Section 1.4, 5.3, 7 Phase 2, Guardrails |
| **24** | 사용자: 터울주성분_new 테이블 | 기존 터울주성분 컬럼 + enrichment 매핑 + LLM 복약안내(JSONB) + 요약 컬럼을 통합한 `터울주성분_new` DDL 추가. JSONB 구조 예시 포함 | Section 3.2 신규, 3.4 다이어그램, 6 마이그레이션 |
| **25** | 사용자: 기존 DB 병행 운영 | 기존 터울주성분 무변경 유지, 터울주성분_new와 병행 운영 후 점진적 전환 | Section 3.4, 6.3, Guardrails, Success Criteria |
| **26** | LLM 파이프라인 설계 | `generate_medication_guide.py` 신규. Claude API 호출, 프롬프트 템플릿(A4/A5), 파일럿 검증, 전문가 리뷰 워크플로 | Phase 2-A/2-B, 파일 구조 (12개) |
| **27** | 예상 수치 업데이트 | A5 터울약효설명 활용 → LLM 전체 생성(20,235건)으로 변경. LLM 호출 예상 추가 | Section 11 |

### Iteration 5 (2026-03-19) — 목차 구조화 + 데이터 소스 인벤토리 + 터울약효설명 우선순위

| # | 피드백 | 변경 내용 | 영향 범위 |
|---|--------|----------|----------|
| **20** | 사용자: 목차 및 넘버링 추가 | 전체 문서에 목차(TOC) 추가, 섹션 번호 1~13으로 재구성. 기존 `## 0.` ~ 미번호 섹션들을 일관된 넘버링으로 통일 | 문서 전체 구조 |
| **21** | 사용자: 활용 데이터 소스 별도 섹션 | Section 1 "활용 데이터 소스 인벤토리" 신설. 내부 DB 10개 테이블, 외부 API 6개, 인프라 3개를 체계적으로 정리. 데이터 우선순위 규칙 포함 | Section 1 신규 |
| **22** | 사용자: 기준 데이터/팜포트 데이터 활용 여부 | 터울약효설명(2,670건, 11,100 성분 커버)의 A5 우선 사용 규칙 명시. Principle #7 "기존 curated 데이터 우선" 추가. A5 데이터 흐름도 추가 | Principles, Section 1.4, Section 5.3, Section 8 Layer 4, Guardrails, Success Criteria |

### Iteration 4 (2026-03-19) — 코드 구조 분석 + edb_ 리네이밍 + 신규 코드 자동 enrichment

| # | 피드백 | 변경 내용 | 영향 범위 |
|---|--------|----------|----------|
| **16** | 사용자: `edb_` 접두사 사용 | 신규 enrichment 테이블 10개를 `pharmport_` → `edb_` 접두사로 변경. 기존 테이블(pharmport_medicine 등)은 유지 | DDL 전체, 계획 전문, 파일 구조 |
| **17** | 심평원성분코드 구조 분석 | 9자리 코드 구조(1-4:주성분, 5-6:단일/복합, 7:투여경로, 8-9:제형) 분석. 고유 주성분 10,491종, 복합제 38.5%, multi-route 391종 발견 | Section 3.4 |
| **18** | 사용자: 주성분코드(9자리) 유지 결정 | FDA label이 투여경로별 별도 문서(경구제 BBW 없음 vs 주사제 BBW 있음). enrichment 키를 9자리로 유지하되 API 호출은 주성분 단위로 최적화 (48% 절감) | Section 3.4, Step 1 전략 |
| **19** | 사용자: 신규 코드 자동 enrichment | 신규 심평원성분코드 등록 시 자동 감지+enrichment Flow 설계. CASE A(기존 주성분 재활용)/B(복합제)/C(완전 신규) 분기. `enrich_new_ingredient.py` 추가 | Section 9, 파일 구조 |

### Iteration 3 (2026-03-19) — FDA API + 환경변수 활용 반영

| # | 피드백 | 변경 내용 | 영향 범위 |
|---|--------|----------|----------|
| **11** | 사용자: FDA API 활용 | openFDA Drug Labeling + FAERS를 Step 5로 추가. Safety Ground Truth 역할. FDA label 데이터는 `auto_validated` 등급 부여 (규제기관 검증 데이터). INN/USAN synonym 매핑 전략 포함. | Step 5 신규, Phase 1-B, 충돌 우선순위, 예상 수치 |
| **12** | 사용자: .env 환경변수 활용 | Section 2 "환경변수 활용 전략" 추가. `AZURE_EMBEDDING_*` → enrichment 텍스트 임베딩, `DEEPL_API` → 영문→한글 번역, `DEV_DATABASE_NAME` → dry-run DB, 신규 `NCBI_API_KEY`/`OPENFDA_API_KEY` 추가 | Section 2, Phase 0 태스크, Phase 1-B |
| **13** | Critic 권고: FDA를 Safety 우선순위 최상위로 | 충돌 시 우선순위를 `FDA label > 터울약효설명 > 팜포트 > ChEMBL > Open Targets > PubMed > FAERS`로 재설정 | Section 1.4 |
| **14** | 사용자: DeepL 번역 활용 | FDA label/MoA/질병명 영문 텍스트를 DeepL API로 한글 번역하여 A4/A5 한글 출력물 생성. 기존 터울약효설명의 한글/영문 이중 패턴 계승 | Phase 1-B, Phase 2 |
| **15** | 파일 구조 업데이트 | `enrich_fda.py` 추가 (9개 신규 파일). Step 번호 조정 (5→FDA, 6→PubMed, 7→Trials, 8→bioRxiv) | 파일 구조, Step 전체 |

### Iteration 2 (2026-03-19) — Architect+Critic 피드백 반영

| # | 피드백 | 변경 내용 | 영향 범위 |
|---|--------|----------|----------|
| **1** | [필수] Safety Data Integrity 원칙 추가 | Principle #1로 "안전 데이터 무오류" 추가. 전문가 검증 없는 safety 데이터 출력 금지. 기존 원칙 #1-5를 #2-6으로 재번호. | Principles, Guardrails, Success Criteria, Phase 2 수락 기준 |
| **2** | [필수] Publication Gate | `edb_content_block`에 `validation_status`, `validated_by`, `validated_at` 컬럼 추가. `'expert_reviewed'`인 블록만 출력물 포함. safety 섹션은 반드시 전문가 검증 필수. | Section 3.2 DDL, Phase 2 수락 기준, Guardrails |
| **3** | [필수] Safety risk-tiered 전문가 검증 | Section 8을 4-Layer Validation Architecture로 전면 재설계. Tier 1(critical/BBW): 전수, Tier 2(severe+contraindication): 전수, Tier 3(나머지): n>=50 샘플 precision>=90%. | Section 8 전체, Phase 1-C, Phase 2 Task Flow |
| **4** | [중요] `target_organism` 컬럼 추가 | `edb_mechanism`에 `target_organism VARCHAR(50)` 추가. A4/A5 출력 시 `Homo sapiens`만 포함. | Section 3.1 DDL, Step 2 전략, Guardrails |
| **5** | [중요] Phase 2 진입 게이트 정확도 지표 | Section 5.1에 정확도 검증 리포트 추가: ChEMBL precision>=95%, MoA>=90%, Safety>=95%, PMID=100%, retracted=0, 충돌 unresolved<=5%. 모두 Pass 필수. | Section 5.1, Phase 1-C Task Flow |
| **6** | Architect: `edb_data_conflict` 테이블 | 소스 간 충돌 감지/해소용 테이블 추가. resolution 필드로 상태 추적. unresolved 건 출력물 제외. | Section 3.1 DDL, Layer 4 Cross-validation, Guardrails |
| **7** | Architect: 4-Layer Validation Architecture | Layer 1(자동 무결성) → Layer 2(매핑 정확도) → Layer 3(Safety risk-tiered) → Layer 4(출력물+Cross-validation) 구조로 재설계. | Section 8 전체 |
| **8** | Retracted article 필터 | `edb_literature`에 `retraction_status`, `retraction_checked_at` 컬럼 추가. PubMed 메타데이터 기반 자동 감지. retracted 건 출력물 자동 제외. | Section 3.1 DDL, Step 6 전략, Layer 1, Guardrails |
| **9** | Open Targets score 임계값 | `association_score >= 0.3` 최소 임계값 설정. 0.3 미만 연관관계 저장 차단. | Step 4 전략, Layer 1, Guardrails |
| **10** | 테이블 수 업데이트 | 신규 테이블 8개 → 10개 (data_conflict, content_block 포함). Phase 0 수락 기준 업데이트. | Phase 0, ADR Consequences, 관계 다이어그램 |
