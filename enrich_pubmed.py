"""
PubMed 문헌 enrichment — Phase 1-B

각 심평원성분코드에 대해 PubMed E-utilities API로 3가지 카테고리 문헌을 수집한다.
  - safety:      "{name} AND (adverse effect OR side effect OR toxicity)"
  - efficacy:    "{name} AND (efficacy OR clinical trial OR randomized)"
  - interaction: "{name} AND (drug interaction OR pharmacokinetic)"

각 카테고리별 최신 5건 수집 → edb_literature 저장 → edb_enrichment_status.literature_fetched = TRUE

Usage:
    python enrich_pubmed.py                      # 전체 미완료
    python enrich_pubmed.py --code 101301AIJ     # 단건
    python enrich_pubmed.py --limit 100          # 100건
    python enrich_pubmed.py --dev                # dev DB
    python enrich_pubmed.py --dry-run            # 테스트 (DB 저장 안 함)
"""

import argparse
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

import requests

from common import get_connection
from enrich_base import (
    ProgressTracker,
    _safe_tracker_update,
    api_call_with_retry,
    batch_insert,
    get_pending_codes,
    get_thread_connection,
    preprocess_ingredient_name,
    update_status,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
SOURCE = "pubmed"
TABLE = "edb_literature"
ARTICLES_PER_CATEGORY = 5

SEARCH_CATEGORIES = {
    "safety": "({name}) AND (adverse effect OR side effect OR toxicity)",
    "efficacy": "({name}) AND (efficacy OR clinical trial OR randomized)",
    "interaction": "({name}) AND (drug interaction OR pharmacokinetic)",
}

# ---------------------------------------------------------------------------
# HTTP 세션 초기화
# ---------------------------------------------------------------------------

_session: Optional[requests.Session] = None


def get_session() -> requests.Session:
    """requests.Session 싱글턴을 반환한다."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": "PharmPort/1.0 (pharmport@teoul.com)"})
    return _session


def _build_api_params(extra: dict) -> dict:
    """NCBI API 공통 파라미터를 반환한다."""
    params: dict = {}
    api_key = os.getenv("NCBI_API_KEY")
    if api_key:
        params["api_key"] = api_key
    params.update(extra)
    return params


# ---------------------------------------------------------------------------
# ESearch — PMID 목록 조회
# ---------------------------------------------------------------------------

def esearch(query: str, retmax: int = ARTICLES_PER_CATEGORY) -> list[str]:
    """PubMed에서 query로 검색하여 PMID 목록을 반환한다.

    Args:
        query: PubMed 검색어
        retmax: 최대 반환 건수

    Returns:
        PMID 문자열 목록
    """
    params = _build_api_params({
        "db": "pubmed",
        "term": query,
        "retmax": retmax,
        "sort": "date",
        "retmode": "json",
    })

    def _call():
        resp = get_session().get(
            f"{EUTILS_BASE}/esearch.fcgi",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    data = api_call_with_retry(SOURCE, _call)
    id_list = data.get("esearchresult", {}).get("idlist", [])
    return id_list


# ---------------------------------------------------------------------------
# EFetch — 메타데이터 XML 조회
# ---------------------------------------------------------------------------

def efetch_xml(pmid_list: list[str]) -> str:
    """PMID 목록의 메타데이터를 XML 문자열로 반환한다.

    최대 200개 PMID를 한 번에 요청할 수 있다.
    """
    if not pmid_list:
        return ""

    params = _build_api_params({
        "db": "pubmed",
        "id": ",".join(pmid_list),
        "rettype": "abstract",
        "retmode": "xml",
    })

    def _call():
        resp = get_session().get(
            f"{EUTILS_BASE}/efetch.fcgi",
            params=params,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.text

    return api_call_with_retry(SOURCE, _call)


# ---------------------------------------------------------------------------
# XML 파싱
# ---------------------------------------------------------------------------

def _get_text(element: ET.Element, path: str, default: str = "") -> str:
    """ElementTree에서 텍스트를 안전하게 추출한다."""
    node = element.find(path)
    if node is not None and node.text:
        return node.text.strip()
    return default


def _get_all_text(element: ET.Element, path: str) -> list[str]:
    """ElementTree에서 모든 매칭 텍스트를 목록으로 반환한다."""
    return [n.text.strip() for n in element.findall(path) if n is not None and n.text]


def parse_article(article_elem: ET.Element) -> dict:
    """PubMedArticle XML 요소를 파싱하여 dict를 반환한다."""
    medline = article_elem.find("MedlineCitation")
    if medline is None:
        return {}

    art = medline.find("Article")
    if art is None:
        return {}

    # PMID
    pmid_elem = medline.find("PMID")
    pmid = pmid_elem.text.strip() if pmid_elem is not None and pmid_elem.text else None
    if not pmid:
        return {}

    # 제목
    title = _get_text(art, "ArticleTitle")

    # 저자 (최대 5명, Last FM 형식)
    authors = []
    author_list = art.find("AuthorList")
    if author_list is not None:
        for author_elem in author_list.findall("Author"):
            last = _get_text(author_elem, "LastName")
            fore = _get_text(author_elem, "ForeName")
            collective = _get_text(author_elem, "CollectiveName")
            if collective:
                authors.append(collective)
            elif last:
                authors.append(f"{last} {fore}".strip())
            if len(authors) >= 5:
                break

    # 저널명
    journal = _get_text(art, "Journal/Title")
    if not journal:
        journal = _get_text(art, "Journal/ISOAbbreviation")

    # 발행연도
    pub_year_str = _get_text(art, "Journal/JournalIssue/PubDate/Year")
    if not pub_year_str:
        # MedlineDate fallback (e.g. "2021 Jan-Feb")
        medline_date = _get_text(art, "Journal/JournalIssue/PubDate/MedlineDate")
        pub_year_str = medline_date[:4] if medline_date else None
    pub_year = int(pub_year_str) if pub_year_str and pub_year_str.isdigit() else None

    # 출판 유형
    pub_types = _get_all_text(art, "PublicationTypeList/PublicationType")
    pub_type = "; ".join(pub_types[:3]) if pub_types else None

    # DOI
    doi = None
    for id_elem in art.findall("ELocationID"):
        if id_elem.get("EIdType") == "doi" and id_elem.text:
            doi = id_elem.text.strip()
            break
    # ArticleIdList에서도 시도
    if not doi:
        article_id_list = article_elem.find("PubmedData/ArticleIdList")
        if article_id_list is not None:
            for aid in article_id_list.findall("ArticleId"):
                if aid.get("IdType") == "doi" and aid.text:
                    doi = aid.text.strip()
                    break

    # PMC ID
    pmc_id = None
    article_id_list = article_elem.find("PubmedData/ArticleIdList")
    if article_id_list is not None:
        for aid in article_id_list.findall("ArticleId"):
            if aid.get("IdType") == "pmc" and aid.text:
                pmc_id = aid.text.strip()
                break

    # Abstract (최대 500자)
    abstract_parts = []
    abstract_elem = art.find("Abstract")
    if abstract_elem is not None:
        for text_elem in abstract_elem.findall("AbstractText"):
            label = text_elem.get("Label", "")
            text = text_elem.text or ""
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
    abstract_full = " ".join(abstract_parts).strip()
    abstract_summary = abstract_full[:500] if abstract_full else None

    # Retraction 상태 확인
    retraction_status = None
    pub_status = _get_text(article_elem, "PubmedData/PublicationStatus")
    if pub_status and "retract" in pub_status.lower():
        retraction_status = "retracted"
    # CommentsCorrectionsList에서 RetractedIn/RetractionOf 확인
    comments = medline.find("CommentsCorrectionsList")
    if comments is not None:
        for comment in comments.findall("CommentsCorrections"):
            ref_type = comment.get("RefType", "")
            if ref_type in ("RetractionIn", "RetractionOf"):
                retraction_status = "retracted"
                break

    return {
        "pmid": pmid,
        "pmc_id": pmc_id,
        "doi": doi,
        "title": title,
        "authors": ", ".join(authors) if authors else None,
        "journal": journal if journal else None,
        "pub_year": pub_year,
        "pub_type": pub_type,
        "abstract_summary": abstract_summary,
        "retraction_status": retraction_status,
    }


def parse_efetch_xml(xml_text: str) -> dict[str, dict]:
    """EFetch XML 응답을 파싱하여 {pmid: 메타데이터} 딕셔너리를 반환한다."""
    if not xml_text:
        return {}

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error("EFetch XML 파싱 오류: %s", e)
        return {}

    result = {}
    for article_elem in root.findall("PubmedArticle"):
        parsed = parse_article(article_elem)
        if parsed and parsed.get("pmid"):
            result[parsed["pmid"]] = parsed

    return result


# ---------------------------------------------------------------------------
# PMID 유효성 검증 (Layer 1)
# ---------------------------------------------------------------------------

def validate_pmids(pmid_list: list[str], metadata: dict[str, dict]) -> tuple[list[str], list[str]]:
    """EFetch 결과로 PMID 유효성을 검증한다.

    Returns:
        (valid_pmids, invalid_pmids)
    """
    valid = [p for p in pmid_list if p in metadata]
    invalid = [p for p in pmid_list if p not in metadata]
    if invalid:
        logger.warning("PMID 유효성 검증 실패: %d건 — %s", len(invalid), invalid[:5])
    return valid, invalid


# ---------------------------------------------------------------------------
# FDA 교차 검증
# ---------------------------------------------------------------------------

def check_fda_conflict(conn, code: str, safety_pmids: list[str]) -> None:
    """FDA edb_safety 레코드와 PubMed safety 문헌을 교차 검증한다.

    edb_safety에 FDA 데이터가 있는 성분에 대해 PubMed safety 정보가
    수집되면 간단한 coverage 로그를 남긴다. 실제 의미 있는 불일치는
    edb_data_conflict에 기록한다.
    """
    if not safety_pmids:
        return

    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM edb_safety
            WHERE "심평원성분코드" = %s
              AND source IN ('fda_label', 'faers')
        """, (code,))
        fda_count = cur.fetchone()[0]

    if fda_count == 0:
        return  # FDA 데이터 없음 — 충돌 없음

    # PubMed safety 문헌이 있는데 FDA 데이터도 있는 경우: coverage log 기록
    # 실질적 의미 불일치는 NLP 없이 감지 불가하므로 meta-conflict만 기록
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO edb_data_conflict (
                    "심평원성분코드",
                    conflict_type,
                    source_a,
                    source_b,
                    description,
                    detected_at
                ) VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT DO NOTHING
            """, (
                code,
                "literature_coverage",
                "pubmed",
                "fda_label",
                f"FDA 데이터 {fda_count}건 존재, PubMed safety 문헌 {len(safety_pmids)}건 수집 — 상세 검토 필요",
            ))
        conn.commit()
    except Exception as e:
        # edb_data_conflict 테이블이 없거나 컬럼 불일치 시 무시
        logger.debug("edb_data_conflict 기록 실패 (무시): %s", e)
        conn.rollback()


# ---------------------------------------------------------------------------
# 동일 주성분(1-4자리) 공유 최적화
# ---------------------------------------------------------------------------

def get_base_code(code: str) -> str:
    """심평원성분코드에서 주성분 1-4자리를 반환한다."""
    return code[:4] if len(code) >= 4 else code


def get_existing_literature_pmids(conn, base_code: str) -> set[str]:
    """동일 주성분(1-4)으로 이미 수집된 PMID 집합을 반환한다."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT pmid FROM edb_literature
            WHERE SUBSTRING("심평원성분코드", 1, 4) = %s
              AND pmid IS NOT NULL
        """, (base_code,))
        return {row[0] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# 단일 성분 enrichment
# ---------------------------------------------------------------------------

def enrich_one(conn, code_info: dict, dry_run: bool = False) -> bool:
    """단일 심평원성분코드에 대한 PubMed 문헌 enrichment를 수행한다.

    Args:
        conn: psycopg2 connection
        code_info: {"심평원성분코드": ..., "성분명": ..., "성분명한글": ...}
        dry_run: True면 DB 저장을 건너뜀

    Returns:
        성공 여부
    """
    code = code_info["심평원성분코드"]
    raw_name = code_info.get("성분명", "") or ""
    name_kr = code_info.get("성분명한글", "") or ""

    # 성분명 전처리
    name = preprocess_ingredient_name(raw_name)
    if not name:
        # 한글명으로 fallback하되 영문 검색에 적합하지 않으므로 경고
        logger.warning("[%s] 영문 성분명 없음 (한글: %s) — 건너뜀", code, name_kr[:30])
        update_status(conn, code, "literature", success=False,
                      error="영문 성분명 없음")
        return False

    logger.info("[%s] PubMed 검색 시작: %s", code, name[:60])

    base_code = get_base_code(code)
    existing_pmids = get_existing_literature_pmids(conn, base_code)

    # 카테고리별 PMID 수집
    category_pmids: dict[str, list[str]] = {}
    all_pmids: list[str] = []

    for category, query_template in SEARCH_CATEGORIES.items():
        query = query_template.format(name=name)
        try:
            pmids = esearch(query, retmax=ARTICLES_PER_CATEGORY)
            # 이미 동일 주성분으로 수집된 PMID는 건너뜀 (중복 방지)
            new_pmids = [p for p in pmids if p not in existing_pmids]
            category_pmids[category] = new_pmids
            all_pmids.extend(new_pmids)
            logger.debug("  [%s] %s: %d건 (신규 %d건)", code, category, len(pmids), len(new_pmids))
        except Exception as e:
            logger.warning("  [%s] ESearch 실패 [%s]: %s", code, category, e)
            category_pmids[category] = []

    if not all_pmids:
        logger.info("  [%s] 수집할 신규 PMID 없음", code)
        if not dry_run:
            update_status(conn, code, "literature")
        return True

    # 중복 제거 (카테고리 간 동일 PMID 가능)
    unique_pmids = list(dict.fromkeys(all_pmids))

    # EFetch: 배치 200개 단위로 메타데이터 수집
    metadata: dict[str, dict] = {}
    batch_size = 200
    for i in range(0, len(unique_pmids), batch_size):
        batch = unique_pmids[i:i + batch_size]
        try:
            xml_text = efetch_xml(batch)
            batch_meta = parse_efetch_xml(xml_text)
            metadata.update(batch_meta)
        except Exception as e:
            logger.warning("  [%s] EFetch 실패 (배치 %d): %s", code, i // batch_size + 1, e)

    # PMID 유효성 검증 (Layer 1 — 100% 유효성)
    valid_pmids, invalid_pmids = validate_pmids(unique_pmids, metadata)
    if invalid_pmids:
        logger.warning("  [%s] 무효 PMID %d건 제외: %s", code, len(invalid_pmids), invalid_pmids[:3])

    if not valid_pmids:
        logger.info("  [%s] 유효 PMID 없음", code)
        if not dry_run:
            update_status(conn, code, "literature")
        return True

    # Retraction 체크 로그
    retracted = [p for p in valid_pmids
                 if metadata[p].get("retraction_status") == "retracted"]
    if retracted:
        logger.warning("  [%s] 철회 논문 %d건 포함 — retraction_status='retracted' 저장",
                       code, len(retracted))

    # records 생성 — PMID가 여러 카테고리에 걸칠 경우 첫 번째 카테고리만 사용
    pmid_to_category: dict[str, str] = {}
    for category, pmids in category_pmids.items():
        for pmid in pmids:
            if pmid not in pmid_to_category:
                pmid_to_category[pmid] = category

    now = datetime.now(timezone.utc)
    records = []
    for pmid in valid_pmids:
        meta = metadata[pmid]
        records.append({
            "심평원성분코드": code,
            "pmid": pmid,
            "pmc_id": meta.get("pmc_id"),
            "doi": meta.get("doi"),
            "title": meta.get("title") or "",
            "authors": meta.get("authors"),
            "journal": meta.get("journal"),
            "pub_year": meta.get("pub_year"),
            "pub_type": meta.get("pub_type"),
            "relevance_category": pmid_to_category.get(pmid, "safety"),
            "abstract_summary": meta.get("abstract_summary"),
            "retraction_status": meta.get("retraction_status"),
            "retraction_checked_at": now if meta.get("retraction_status") is not None else None,
            "source": SOURCE,
            "fetched_at": now,
        })

    if dry_run:
        logger.info("  [dry-run] %s: %d건 저장 예정 (카테고리별: safety=%d, efficacy=%d, interaction=%d)",
                    code, len(records),
                    len(category_pmids.get("safety", [])),
                    len(category_pmids.get("efficacy", [])),
                    len(category_pmids.get("interaction", [])))
        for r in records[:2]:
            logger.info("    PMID=%s, title=%s...", r["pmid"], (r["title"] or "")[:60])
        return True

    # DB 저장
    inserted = batch_insert(conn, TABLE, records, conflict_action="DO NOTHING")
    logger.info("  [%s] %d건 저장 완료 (카테고리별: safety=%d, efficacy=%d, interaction=%d)",
                code, inserted,
                len(category_pmids.get("safety", [])),
                len(category_pmids.get("efficacy", [])),
                len(category_pmids.get("interaction", [])))

    # FDA 교차 검증
    safety_pmids = [p for p in category_pmids.get("safety", []) if p in metadata]
    check_fda_conflict(conn, code, safety_pmids)

    # 상태 업데이트
    update_status(conn, code, "literature")
    return True


# ---------------------------------------------------------------------------
# 병렬 처리 워커
# ---------------------------------------------------------------------------

def _enrich_one_worker(code_info: dict, db_name: str | None, dry_run: bool) -> tuple[str, bool]:
    """스레드풀에서 호출되는 워커. 자체 DB 연결을 생성하여 단건 처리한다."""
    code = code_info.get("심평원성분코드", "?")
    conn = get_thread_connection(db_name)
    try:
        success = enrich_one(conn, code_info, dry_run=dry_run)
        return (code, success)
    except Exception:
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="PubMed 문헌 enrichment (Phase 1-B)")
    parser.add_argument("--code", help="단건 처리: 심평원성분코드")
    parser.add_argument("--limit", type=int, default=0, help="처리 건수 제한 (0=전체)")
    parser.add_argument("--dev", action="store_true", help="dev DB 사용")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="DB 저장 없이 테스트만 수행")
    parser.add_argument("--workers", type=int, default=1,
                        help="병렬 워커 수 (기본 1=순차처리)")
    args = parser.parse_args()

    # NCBI API 키 안내
    api_key = os.getenv("NCBI_API_KEY")
    if api_key:
        logger.info("NCBI_API_KEY 감지 — rate limit: 10 req/sec")
        # rate limit 업데이트 (기본 3/sec → 10/sec)
        from enrich_base import DEFAULT_RATE_LIMITS, RateLimitConfig
        DEFAULT_RATE_LIMITS["pubmed"] = RateLimitConfig(
            requests_per_second=10.0, burst_size=10, retry_max=3,
        )
    else:
        logger.info("NCBI_API_KEY 미설정 — rate limit: 3 req/sec")

    db_name = os.getenv("DEV_DATABASE_NAME") if args.dev else None
    conn = get_connection(db_name)

    try:
        if args.code:
            # 단건 처리
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT "심평원성분코드", "성분명", "성분명한글"
                    FROM "터울주성분"
                    WHERE "심평원성분코드" = %s AND "IsDeleted" = FALSE
                """, (args.code,))
                row = cur.fetchone()
                if not row:
                    logger.error("코드를 찾을 수 없음: %s", args.code)
                    sys.exit(1)
                code_info = {
                    "심평원성분코드": row[0],
                    "성분명": row[1],
                    "성분명한글": row[2],
                }

            success = enrich_one(conn, code_info, dry_run=args.dry_run)
            sys.exit(0 if success else 1)

        else:
            # 전체 미완료 처리
            pending = get_pending_codes(conn, "literature", limit=args.limit)
            total = len(pending)

            if total == 0:
                logger.info("미완료 성분 없음 — literature_fetched 전체 완료 상태")
                return

            logger.info("PubMed 문헌 enrichment 시작: %d건%s",
                        total, " [dry-run]" if args.dry_run else "")

            tracker = ProgressTracker(total=total, source=SOURCE, log_interval=10)

            if args.workers > 1:
                # Parallel processing
                logger.info("병렬 처리 모드: workers=%d", args.workers)
                with ThreadPoolExecutor(max_workers=args.workers) as executor:
                    futures = {
                        executor.submit(_enrich_one_worker, ci, db_name, args.dry_run): ci
                        for ci in pending
                    }
                    for future in as_completed(futures):
                        ci = futures[future]
                        code = ci.get("심평원성분코드", "?")
                        try:
                            _, success = future.result()
                            _safe_tracker_update(tracker, success=success)
                        except Exception as e:
                            logger.error("[%s] 처리 실패: %s", code, e)
                            _safe_tracker_update(tracker, success=False)
            else:
                # Original sequential processing
                for code_info in pending:
                    code = code_info["심평원성분코드"]
                    try:
                        success = enrich_one(conn, code_info, dry_run=args.dry_run)
                        tracker.update(success=success)
                    except Exception as e:
                        logger.error("[%s] 처리 실패: %s", code, e)
                        if not args.dry_run:
                            update_status(conn, code, "literature", success=False, error=str(e))
                        tracker.update(success=False)

            summary = tracker.summary()
            logger.info(
                "완료 — 처리: %d, 성공: %d, 실패: %d, 건너뜀: %d, 소요: %.1f초",
                summary["processed"], summary["success"],
                summary["failed"], summary["skipped"],
                summary["elapsed_seconds"],
            )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
