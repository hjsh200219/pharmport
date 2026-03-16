import os
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_BATCH_SIZE = 100
MAX_RETRIES = 3
RETRY_DELAY_SEC = 5
MAX_WORKERS = 8

_client: AzureOpenAI | None = None


def _get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_EMBEDDING_ENDPOINT"),
            api_key=os.getenv("AZURE_EMBEDDING_KEY"),
            api_version="2024-02-01",
        )
    return _client


def _get_model() -> str:
    return os.getenv("AZURE_EMBEDDING_MODEL", "text-embedding-3-large")


def get_embedding(text: str) -> list[float]:
    """단일 텍스트의 임베딩 벡터를 반환한다."""
    response = _get_client().embeddings.create(input=[text], model=_get_model())
    return response.data[0].embedding


def get_embeddings_parallel(texts: list[str], workers: int = MAX_WORKERS) -> list[list[float]]:
    """여러 텍스트를 병렬로 임베딩한다.

    API_BATCH_SIZE(100)개씩 나눈 뒤 workers 수만큼 동시 호출.
    """
    chunks = [
        (i, texts[i : i + API_BATCH_SIZE])
        for i in range(0, len(texts), API_BATCH_SIZE)
    ]

    results: dict[int, list[list[float]]] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_embed_chunk, chunk_texts): chunk_idx
            for chunk_idx, chunk_texts in chunks
        }

        done_count = 0
        for future in as_completed(futures):
            chunk_idx = futures[future]
            results[chunk_idx] = future.result()
            done_count += 1
            if done_count % 10 == 0 or done_count == len(chunks):
                logger.info(
                    "임베딩 진행: %d / %d 배치 (%d / %d건)",
                    done_count, len(chunks),
                    min(done_count * API_BATCH_SIZE, len(texts)), len(texts),
                )

    all_embeddings: list[list[float]] = []
    for idx in sorted(results.keys()):
        all_embeddings.extend(results[idx])

    return all_embeddings


def _embed_chunk(texts: list[str]) -> list[list[float]]:
    client = _get_client()
    model = _get_model()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.embeddings.create(input=texts, model=model)
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.warning("임베딩 API 실패 (시도 %d/%d): %s", attempt, MAX_RETRIES, e)
            if attempt == MAX_RETRIES:
                raise
            time.sleep(RETRY_DELAY_SEC * attempt)
    return []


def sort_ingredients(text: str) -> str:
    """콤마로 구분된 성분을 알파벳순 정렬하여 반환한다.

    괄호 안의 콤마는 구분자로 취급하지 않는다.
    예: "Telmisartan 40mg, Rosuvastatin 10mg (Rosuvastatin calcium 10.4mg)"
    → "Rosuvastatin 10mg (Rosuvastatin calcium 10.4mg), Telmisartan 40mg"
    """
    if not text:
        return ""

    parts = _split_respecting_parens(text)
    sorted_parts = sorted(parts, key=lambda s: s.strip().lower())
    return ", ".join(p.strip() for p in sorted_parts)


def _split_respecting_parens(text: str) -> list[str]:
    """괄호 깊이를 추적하며 콤마로 분리한다."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []

    for char in text:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)

    if current:
        parts.append("".join(current))

    return parts
