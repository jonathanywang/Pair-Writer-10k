"""EDGAR fetch + HTML parse for 10-K filings.

Returns a Filing object containing structured chunks keyed by Item + paragraph.
"""


from __future__ import annotations
import ssl_patch  # ← line 1 of every file

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests
from bs4 import BeautifulSoup

# EDGAR requires a User-Agent identifying the requester
USER_AGENT = "yung Charc charly.espinoza@factset.com"

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)


# Map of standard 10-K item headings to canonical labels
ITEM_PATTERNS = [
    (r"item\s*1a[.\s]", "Item 1A"),
    (r"item\s*1b[.\s]", "Item 1B"),
    (r"item\s*1c[.\s]", "Item 1C"),
    (r"item\s*1[.\s]", "Item 1"),
    (r"item\s*2[.\s]", "Item 2"),
    (r"item\s*3[.\s]", "Item 3"),
    (r"item\s*4[.\s]", "Item 4"),
    (r"item\s*5[.\s]", "Item 5"),
    (r"item\s*6[.\s]", "Item 6"),
    (r"item\s*7a[.\s]", "Item 7A"),
    (r"item\s*7[.\s]", "Item 7"),
    (r"item\s*8[.\s]", "Item 8"),
    (r"item\s*9a[.\s]", "Item 9A"),
    (r"item\s*9b[.\s]", "Item 9B"),
    (r"item\s*9[.\s]", "Item 9"),
    (r"item\s*10[.\s]", "Item 10"),
    (r"item\s*11[.\s]", "Item 11"),
    (r"item\s*12[.\s]", "Item 12"),
    (r"item\s*13[.\s]", "Item 13"),
    (r"item\s*14[.\s]", "Item 14"),
    (r"item\s*15[.\s]", "Item 15"),
    (r"item\s*16[.\s]", "Item 16"),
]

# Friendly titles for common items
ITEM_TITLES = {
    "Item 1": "Business",
    "Item 1A": "Risk Factors",
    "Item 1B": "Unresolved Staff Comments",
    "Item 1C": "Cybersecurity",
    "Item 2": "Properties",
    "Item 3": "Legal Proceedings",
    "Item 4": "Mine Safety",
    "Item 5": "Market for Registrant's Common Equity",
    "Item 6": "Reserved",
    "Item 7": "MD&A",
    "Item 7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "Item 8": "Financial Statements",
    "Item 9": "Changes in and Disagreements with Accountants",
    "Item 9A": "Controls and Procedures",
    "Item 9B": "Other Information",
    "Item 9C": "Foreign Jurisdictions",
    "Item 10": "Directors and Executive Officers",
    "Item 11": "Executive Compensation",
    "Item 12": "Security Ownership",
    "Item 13": "Related Transactions and Director Independence",
    "Item 14": "Principal Accountant Fees",
    "Item 15": "Exhibits and Financial Statement Schedules",
    "Item 16": "Form 10-K Summary",
}


@dataclass
class Chunk:
    """A single paragraph-level chunk of the filing."""
    chunk_id: str          # e.g., "1A.p3" — stable, used for citations
    item: str              # e.g., "Item 1A"
    paragraph_index: int   # 1-based within the item
    text: str
    themes: list[str] = field(default_factory=list)
    is_table: bool = False


@dataclass
class Filing:
    """Parsed 10-K filing."""
    url: str
    company_name: str
    chunks: list[Chunk] = field(default_factory=list)
    items_present: list[str] = field(default_factory=list)

    def chunks_by_item(self, item: str) -> list[Chunk]:
        return [c for c in self.chunks if c.item == item]

    def get_chunk(self, chunk_id: str) -> Optional[Chunk]:
        for c in self.chunks:
            if c.chunk_id == chunk_id:
                return c
        return None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "company_name": self.company_name,
            "chunks": [asdict(c) for c in self.chunks],
            "items_present": self.items_present,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Filing":
        chunks = [Chunk(**c) for c in data["chunks"]]
        return cls(
            url=data["url"],
            company_name=data["company_name"],
            chunks=chunks,
            items_present=data["items_present"],
        )


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _cache_path(url: str) -> str:
    return os.path.join(CACHE_DIR, f"{_cache_key(url)}.json")


def load_cached(url: str) -> Optional[Filing]:
    """Load a previously-ingested filing from disk, if available."""
    path = _cache_path(url)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return Filing.from_dict(json.load(f))
        except Exception:
            return None
    return None


def save_cached(filing: Filing) -> None:
    """Persist a parsed + tagged filing to disk."""
    path = _cache_path(filing.url)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(filing.to_dict(), f, ensure_ascii=False, indent=2)


def fetch_html(url: str) -> str:
    """Fetch an EDGAR filing's HTML with the proper User-Agent."""
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    # EDGAR is polite — small delay to be safe with rate limits
    time.sleep(0.1)
    return resp.text


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _looks_like_item_heading(text: str) -> Optional[str]:
    """Return the canonical Item label if this text is an Item heading."""
    if not text or len(text) > 200:
        return None
    lowered = text.lower().strip()
    for pattern, label in ITEM_PATTERNS:
        if re.match(pattern, lowered):
            return label
    return None


def _extract_company_name(soup: BeautifulSoup, raw_html: str = "") -> str:
    """Best-effort company name extraction from filing HTML."""
    # 1. EDGAR header comment — most reliable
    # Looks like: COMPANY CONFORMED NAME:\t\tApple Inc.
    m = re.search(r"COMPANY CONFORMED NAME:\s*(.+)", raw_html)
    if m:
        name = m.group(1).strip()
        if name:
            return name[:120]

    # 2. SEC EDGAR covers the company name in a <span> with class "companyName"
    tag = soup.find(attrs={"class": re.compile(r"companyName", re.I)})
    if tag:
        name = _normalize_text(tag.get_text())
        if name:
            return name[:120]

    # 3. Try <title> but strip the ticker/date suffix (e.g. "aapl-20240928")
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        # If it looks like a slug, skip it
        if title and not re.match(r"^[a-z0-9\-]+$", title.lower()):
            return title[:120]

    # 4. First h1/h2
    for tag in ["h1", "h2"]:
        h = soup.find(tag)
        if h:
            name = _normalize_text(h.get_text())
            if name and len(name) > 3:
                return name[:120]

    return "Unknown Filing"


def parse_filing(html: str, url: str) -> Filing:
    """Parse an EDGAR 10-K HTML document into structured chunks."""
    soup = BeautifulSoup(html, "lxml")

    # Strip script, style, head metadata
    for tag in soup(["script", "style", "head", "meta", "link"]):
        tag.decompose()

    company_name = _extract_company_name(soup, raw_html=html)

    # Walk the document collecting text blocks. EDGAR filings vary wildly in
    # structure, but the common denominator is: text blocks separated by
    # paragraph or div boundaries, with Item headings interspersed.
    blocks: list[tuple[str, str]] = []  # (kind, text), kind in {"p", "table"}

    body = soup.body if soup.body else soup
    for el in body.descendants:
        if not hasattr(el, "name") or el.name is None:
            continue
        if el.name == "table":
            txt = _normalize_text(el.get_text(" "))
            if txt and len(txt) > 20:
                blocks.append(("table", txt[:3000]))  # cap very long tables
        elif el.name in ("p", "div"):
            # Only take leaves; nested div text gets pulled at the inner level
            if el.find(["p", "div", "table"]):
                continue
            txt = _normalize_text(el.get_text(" "))
            if txt and len(txt) > 0:
                blocks.append(("p", txt))

    # If we found nothing via p/div (unusual), fall back to any text node
    if not blocks:
        for line in body.get_text("\n").split("\n"):
            line = _normalize_text(line)
            if line:
                blocks.append(("p", line))

    # Group blocks into Items by walking and tracking the current Item
    current_item: Optional[str] = None
    current_para_idx = 0
    current_table_idx = 0
    chunks: list[Chunk] = []
    items_present: list[str] = []
    seen_items: set[str] = set()

    for kind, text in blocks:
        heading = _looks_like_item_heading(text)
        if heading:
            current_item = heading
            current_para_idx = 0
            current_table_idx = 0
            if heading not in seen_items:
                seen_items.add(heading)
                items_present.append(heading)
            continue

        if current_item is None:
            # Skip preamble (cover page, table of contents, etc.)
            continue

        # Filter out short or junky blocks
        if len(text) < 50 and kind == "p":
            continue

        item_short = current_item.replace("Item ", "")  # "1A", "7", etc.
        if kind == "table":
            current_table_idx += 1
            chunk_id = f"{item_short}.t{current_table_idx}"
            chunks.append(Chunk(
                chunk_id=chunk_id,
                item=current_item,
                paragraph_index=current_table_idx,
                text=text,
                is_table=True,
            ))
        else:
            current_para_idx += 1
            chunk_id = f"{item_short}.p{current_para_idx}"
            chunks.append(Chunk(
                chunk_id=chunk_id,
                item=current_item,
                paragraph_index=current_para_idx,
                text=text,
                is_table=False,
            ))

    return Filing(
        url=url,
        company_name=company_name,
        chunks=chunks,
        items_present=items_present,
    )


def _fetch_company_name_from_edgar(url: str) -> str:
    """Extract CIK from URL and look up company name via EDGAR API."""
    # URL looks like: .../edgar/data/320193/000032019324000123/aapl-20240928.htm
    m = re.search(r"/edgar/data/(\d+)/", url)
    if not m:
        return ""
    cik = m.group(1).lstrip("0")
    try:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        resp = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json",
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("name", "")
    except Exception:
        return ""


def ingest(url: str, use_cache: bool = True) -> Filing:
    """Fetch + parse a 10-K filing. Uses cache if available."""
    if use_cache:
        cached = load_cached(url)
        if cached is not None:
            return cached

    html = fetch_html(url)
    filing = parse_filing(html, url)

    # Override company name from EDGAR submissions API — much more reliable
    name = _fetch_company_name_from_edgar(url)
    if name:
        filing.company_name = name

    return filing


if __name__ == "__main__":
    # Quick smoke test from CLI
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ingest.py <edgar_url>")
        sys.exit(1)
    f = ingest(sys.argv[1], use_cache=False)
    print(f"Company: {f.company_name}")
    print(f"Items: {f.items_present}")
    print(f"Total chunks: {len(f.chunks)}")
    for item in f.items_present[:3]:
        item_chunks = f.chunks_by_item(item)
        print(f"\n{item}: {len(item_chunks)} chunks")
        if item_chunks:
            print(f"  First chunk ({item_chunks[0].chunk_id}): {item_chunks[0].text[:150]}...")
