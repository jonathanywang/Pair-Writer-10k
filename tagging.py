"""One-pass theme tagging for filing chunks using GPT-4o.

Tags are stored on each chunk and persisted in the filing cache, so this
only runs once per filing.
"""


from __future__ import annotations
import ssl_patch  # ← line 1 of every file
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

from ingest import Filing, Chunk
from prompts import THEME_TAGGING_PROMPT

VALID_THEMES = {
    "supply_chain", "regulatory", "technology", "competition",
    "financial_performance", "liquidity", "segment_performance",
    "macroeconomic", "legal", "human_capital", "intellectual_property",
    "cybersecurity", "environmental", "governance", "general",
}

BATCH_SIZE = 8
MAX_WORKERS = 5


def _get_client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        api_version=os.getenv("OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("OPENAI_API_BASE_URL"),
    )


def _tag_batch(client: AzureOpenAI, chunks: list[Chunk]) -> list[list[str]]:
    """Tag a batch of chunks in a single model call."""
    user_msg_parts = ["Tag each paragraph below. Output JSON: {\"results\": [{\"tags\": [...]}, ...]}\n"]
    for i, c in enumerate(chunks, 1):
        text = c.text[:800]
        user_msg_parts.append(f"\n[{i}] {text}")
    user_msg = "\n".join(user_msg_parts)

    try:
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini-0718"),
            messages=[
                {"role": "system", "content": THEME_TAGGING_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=800,
        )
        content = resp.choices[0].message.content or "{}"
        parsed = json.loads(content)
        results = parsed.get("results", [])
        out = []
        for i in range(len(chunks)):
            if i < len(results) and isinstance(results[i], dict):
                tags = results[i].get("tags", [])
                tags = [t for t in tags if t in VALID_THEMES]
                if not tags:
                    tags = ["general"]
                out.append(tags[:3])
            else:
                out.append(["general"])
        return out
    except Exception as e:
        print(f"Tagging batch failed: {e}")
        return [["general"]] * len(chunks)


def tag_filing(
    filing: Filing,
    client: Optional[AzureOpenAI] = None,
    progress_callback=None,
) -> Filing:
    """Apply theme tags to every chunk in the filing. Mutates and returns filing."""
    if client is None:
        client = _get_client()

    text_chunks = [c for c in filing.chunks if not c.is_table]
    for c in filing.chunks:
        if c.is_table:
            c.themes = ["financial_performance"]

    batches: list[list[Chunk]] = []
    for i in range(0, len(text_chunks), BATCH_SIZE):
        batches.append(text_chunks[i:i + BATCH_SIZE])

    total_batches = len(batches)
    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_to_batch = {ex.submit(_tag_batch, client, b): b for b in batches}
        for fut in as_completed(future_to_batch):
            batch = future_to_batch[fut]
            try:
                tag_lists = fut.result()
            except Exception:
                tag_lists = [["general"]] * len(batch)
            for chunk, tags in zip(batch, tag_lists):
                chunk.themes = tags
            completed += 1
            if progress_callback:
                progress_callback(completed, total_batches)

    return filing


def all_themes_in_filing(filing: Filing) -> list[str]:
    """Return sorted list of unique themes actually present in this filing."""
    themes: set[str] = set()
    for c in filing.chunks:
        themes.update(c.themes)
    return sorted(themes)
