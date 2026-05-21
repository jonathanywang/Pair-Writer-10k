"""Embedding-based retrieval over a parsed filing.

Pinned chunks are always included regardless of similarity score.
"""

from __future__ import annotations

import ssl_patch  # ← line 1 of every file

import json
import os
from typing import Optional

import numpy as np
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

from ingest import Filing, Chunk, CACHE_DIR, _cache_key

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
EMBED_BATCH = 100


def _get_client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        api_version=os.getenv("OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("OPENAI_API_BASE_URL"),
    )


def _embed_cache_path(url: str) -> str:
    return os.path.join(CACHE_DIR, f"{_cache_key(url)}_embed.json")


def _embed_texts(client: AzureOpenAI, texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts."""
    truncated = [t[:8000] for t in texts]
    resp = client.embeddings.create(model=EMBED_MODEL, input=truncated)
    return [d.embedding for d in resp.data]


def build_embeddings(
    filing: Filing,
    client: Optional[AzureOpenAI] = None,
    progress_callback=None,
) -> dict[str, list[float]]:
    """Embed every chunk in the filing. Returns dict of chunk_id -> embedding."""
    if client is None:
        client = _get_client()

    cache_path = _embed_cache_path(filing.url)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                return json.load(f)
        except Exception:
            pass

    embeddings: dict[str, list[float]] = {}
    chunks = filing.chunks
    total = len(chunks)
    done = 0

    for i in range(0, total, EMBED_BATCH):
        batch = chunks[i:i + EMBED_BATCH]
        texts = [c.text[:6000] for c in batch]
        try:
            vecs = _embed_texts(client, texts)
            for chunk, vec in zip(batch, vecs):
                embeddings[chunk.chunk_id] = vec
        except Exception as e:
            print(f"Embed batch failed: {e}")
            for chunk in batch:
                embeddings[chunk.chunk_id] = [0.0] * EMBED_DIM
        done += len(batch)
        if progress_callback:
            progress_callback(done, total)

    try:
        with open(cache_path, "w") as f:
            json.dump(embeddings, f)
    except Exception:
        pass

    return embeddings


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def retrieve(
    filing: Filing,
    embeddings: dict[str, list[float]],
    query: str,
    client: Optional[AzureOpenAI] = None,
    top_k: int = 6,
    theme_filter: Optional[list[str]] = None,
    pinned_ids: Optional[list[str]] = None,
) -> list[Chunk]:
    """Retrieve top-k chunks relevant to the query.

    - theme_filter: if provided, only chunks with at least one matching theme are eligible
      (pinned chunks bypass this filter)
    - pinned_ids: always included regardless of score
    """
    if client is None:
        client = _get_client()
    pinned_ids = pinned_ids or []

    try:
        q_emb = _embed_texts(client, [query])[0]
    except Exception:
        return _keyword_fallback(filing, query, top_k, theme_filter, pinned_ids)

    q_vec = np.array(q_emb)

    scored: list[tuple[float, Chunk]] = []
    for chunk in filing.chunks:
        if chunk.chunk_id in pinned_ids:
            continue
        if theme_filter:
            if not any(t in chunk.themes for t in theme_filter):
                continue
        emb = embeddings.get(chunk.chunk_id)
        if emb is None:
            continue
        score = _cosine_sim(q_vec, np.array(emb))
        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [c for _, c in scored[:top_k]]

    pinned_chunks = []
    for pid in pinned_ids:
        c = filing.get_chunk(pid)
        if c is not None:
            pinned_chunks.append(c)

    seen = set()
    result = []
    for c in pinned_chunks + top:
        if c.chunk_id not in seen:
            seen.add(c.chunk_id)
            result.append(c)
    return result[:top_k + len(pinned_chunks)]


def _keyword_fallback(
    filing: Filing,
    query: str,
    top_k: int,
    theme_filter: Optional[list[str]],
    pinned_ids: list[str],
) -> list[Chunk]:
    """Crude keyword fallback when embeddings fail."""
    keywords = [w.lower() for w in query.split() if len(w) > 3]
    scored: list[tuple[int, Chunk]] = []
    for chunk in filing.chunks:
        if chunk.chunk_id in pinned_ids:
            continue
        if theme_filter and not any(t in chunk.themes for t in theme_filter):
            continue
        text_lower = chunk.text.lower()
        score = sum(text_lower.count(k) for k in keywords)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [c for _, c in scored[:top_k]]
    pinned = [c for c in (filing.get_chunk(pid) for pid in pinned_ids) if c]
    seen = set()
    result = []
    for c in pinned + top:
        if c.chunk_id not in seen:
            seen.add(c.chunk_id)
            result.append(c)
    return result
