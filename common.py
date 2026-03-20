import os
import logging
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _build_connection_params(db_name: str | None = None) -> dict:
    params = {
        "host": os.getenv("DATABASE_HOST"),
        "port": int(os.getenv("DATABASE_PORT", "5432")),
        "user": os.getenv("DATABASE_USER"),
        "password": os.getenv("DATABASE_PASSWORD"),
        "dbname": db_name or os.getenv("DATABASE_NAME"),
        "sslmode": "require",
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }

    missing = [k for k, v in params.items() if v is None and k != "sslmode"]
    if missing:
        raise ValueError(f"환경변수 누락: {', '.join(missing)}")

    return params


def get_connection(db_name: str | None = None):
    """PostgreSQL 커넥션을 반환한다.

    Args:
        db_name: 접속할 DB명. None이면 DATABASE_NAME 사용.

    Returns:
        psycopg2 connection 객체
    """
    params = _build_connection_params(db_name)
    try:
        conn = psycopg2.connect(**params)
        logger.info("DB 연결 성공: %s", params["dbname"])
        return conn
    except psycopg2.Error as e:
        logger.error("DB 연결 실패: %s", e)
        raise


@contextmanager
def get_cursor(db_name: str | None = None, dict_cursor: bool = False):
    """커넥션과 커서를 자동 관리하는 컨텍스트 매니저.

    Args:
        db_name: 접속할 DB명. None이면 DATABASE_NAME 사용.
        dict_cursor: True면 결과를 dict로 반환.

    Yields:
        psycopg2 cursor 객체

    Example:
        with get_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM users")
            rows = cur.fetchall()
    """
    conn = get_connection(db_name)
    cursor_factory = RealDictCursor if dict_cursor else None
    try:
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            yield cur
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_pharminfo_connection():
    """teoul_pharminfo DB 커넥션을 반환한다."""
    return get_connection(os.getenv("DATABASE_NAME", "teoul_pharminfo"))


def get_vector_connection():
    """벡터 데이터 저장 DB(postgres) 커넥션을 반환한다."""
    return get_connection(os.getenv("VECTOR_DATABASE_NAME", "postgres"))


def get_dev_connection():
    """개발 DB(teoul_201201) 커넥션을 반환한다."""
    return get_connection(os.getenv("DEV_DATABASE_NAME", "teoul_201201"))


def get_v2_connection():
    """신규 DB(teoul_pharminfo_v2) 커넥션을 반환한다.

    LLM 생성 결과 및 프로파일 데이터 저장용.
    """
    return get_connection(os.getenv("V2_DATABASE_NAME", "teoul_pharminfo_v2"))
