import logging
from common import get_cursor

logger = logging.getLogger(__name__)

TABLE_NAMES = [
    "pharmport_extra_text",
    "pharmport_medicine",
    "pharmport_medicine_extra",
    "pharmport_medicine_usage",
    "pharmport_usage_text",
    "pharmport_비교",
    "ProductInfos",
    "터울주성분",
    "Manufacturers",
]


def fetch_table(table_name: str, limit: int | None = None) -> list[dict]:
    """지정 테이블의 전체 데이터를 조회한다."""
    if table_name not in TABLE_NAMES:
        raise ValueError(f"허용되지 않은 테이블: {table_name}")

    query = f'SELECT * FROM "{table_name}"'
    if limit:
        query += f" LIMIT {int(limit)}"

    with get_cursor(dict_cursor=True) as cur:
        cur.execute(query)
        return cur.fetchall()


def fetch_extra_text(limit: int | None = None) -> list[dict]:
    """pharmport_extra_text 테이블 조회."""
    return fetch_table("pharmport_extra_text", limit)


def fetch_medicine(limit: int | None = None) -> list[dict]:
    """pharmport_medicine 테이블 조회."""
    return fetch_table("pharmport_medicine", limit)


def fetch_medicine_extra(limit: int | None = None) -> list[dict]:
    """pharmport_medicine_extra 테이블 조회."""
    return fetch_table("pharmport_medicine_extra", limit)


def fetch_medicine_usage(limit: int | None = None) -> list[dict]:
    """pharmport_medicine_usage 테이블 조회."""
    return fetch_table("pharmport_medicine_usage", limit)


def fetch_usage_text(limit: int | None = None) -> list[dict]:
    """pharmport_usage_text 테이블 조회."""
    return fetch_table("pharmport_usage_text", limit)


def fetch_comparison(limit: int | None = None) -> list[dict]:
    """pharmport_비교 테이블 조회."""
    return fetch_table("pharmport_비교", limit)


def fetch_product_infos(limit: int | None = None) -> list[dict]:
    """ProductInfos 테이블 조회."""
    return fetch_table("ProductInfos", limit)


def fetch_teoul_ingredients(limit: int | None = None) -> list[dict]:
    """터울주성분 테이블 조회."""
    return fetch_table("터울주성분", limit)


def fetch_manufacturers(limit: int | None = None) -> list[dict]:
    """Manufacturers 테이블 조회."""
    return fetch_table("Manufacturers", limit)


def fetch_all_tables(limit: int | None = None) -> dict[str, list[dict]]:
    """모든 pharmport 테이블을 한번에 조회한다."""
    return {name: fetch_table(name, limit) for name in TABLE_NAMES}
