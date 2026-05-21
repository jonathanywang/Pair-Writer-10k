"""Three-option edit generation and application.

The memo is modeled as a list of paragraphs (strings), each with a stable ID
like "m1", "m2", etc. Edits operate on these paragraph IDs.
"""


from __future__ import annotations

import ssl_patch  # ← line 1 of every file
import difflib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

from ingest import Chunk
from prompts import (
    THREE_OPTION_EDIT_PROMPT,
    REGENERATE_GO_FURTHER_PROMPT,
    ASK_FILING_PROMPT,
)


def _get_client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        api_version=os.getenv("OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("OPENAI_API_BASE_URL"),
    )


@dataclass
class Paragraph:
    """A paragraph in the memo."""
    pid: str       # stable ID like "m1", "m2"
    text: str


@dataclass
class Memo:
    """The live memo document."""
    paragraphs: list[Paragraph] = field(default_factory=list)
    _next_id: int = 1

    def new_id(self) -> str:
        pid = f"m{self._next_id}"
        self._next_id += 1
        return pid

    def add_paragraph(self, text: str, after_pid: Optional[str] = None) -> str:
        new_p = Paragraph(pid=self.new_id(), text=text)
        if after_pid is None:
            self.paragraphs.append(new_p)
        else:
            idx = self._index_of(after_pid)
            if idx is None:
                self.paragraphs.append(new_p)
            else:
                self.paragraphs.insert(idx + 1, new_p)
        return new_p.pid

    def replace_paragraph(self, pid: str, new_text: str) -> bool:
        for p in self.paragraphs:
            if p.pid == pid:
                p.text = new_text
                return True
        return False

    def delete_paragraph(self, pid: str) -> bool:
        before = len(self.paragraphs)
        self.paragraphs = [p for p in self.paragraphs if p.pid != pid]
        return len(self.paragraphs) < before

    def _index_of(self, pid: str) -> Optional[int]:
        for i, p in enumerate(self.paragraphs):
            if p.pid == pid:
                return i
        return None

    def get(self, pid: str) -> Optional[Paragraph]:
        for p in self.paragraphs:
            if p.pid == pid:
                return p
        return None

    def to_text(self) -> str:
        return "\n\n".join(p.text for p in self.paragraphs)

    def to_text_with_ids(self) -> str:
        """Render the memo with paragraph IDs visible — used as model context."""
        if not self.paragraphs:
            return "(empty memo)"
        return "\n\n".join(f"[{p.pid}] {p.text}" for p in self.paragraphs)

    def snapshot(self) -> list[tuple[str, str]]:
        """Capture current state for history/undo."""
        return [(p.pid, p.text) for p in self.paragraphs]

    def restore(self, snapshot: list[tuple[str, str]]) -> None:
        self.paragraphs = [Paragraph(pid=pid, text=text) for pid, text in snapshot]
        if self.paragraphs:
            max_n = max(int(p.pid[1:]) for p in self.paragraphs if p.pid.startswith("m") and p.pid[1:].isdigit())
            self._next_id = max_n + 1


@dataclass
class EditOption:
    label: str
    new_text: str
    rationale: str


@dataclass
class EditProposal:
    op: str           # "replace", "insert_after", "delete"
    anchor: str       # paragraph_id or "end_of_memo"
    variation_axis: str
    options: list[EditOption]
    note: str = ""


def _format_chunks_for_prompt(chunks: list[Chunk]) -> str:
    """Format retrieved chunks for inclusion in the model prompt."""
    parts = []
    for c in chunks:
        kind = "TABLE" if c.is_table else "PARA"
        parts.append(f"--- [{c.chunk_id}] ({c.item}, {kind}) ---\n{c.text[:1500]}")
    return "\n\n".join(parts)


def generate_three_options(
    client: Optional[AzureOpenAI],
    memo: Memo,
    instruction: str,
    retrieved: list[Chunk],
    scope: str,  # "whole_memo" or a paragraph ID like "m3"
    rejected: Optional[list[EditOption]] = None,
) -> EditProposal:
    """Call the model for three (or two) options. Single call, no streaming for v1."""
    if client is None:
        client = _get_client()

    use_regen_prompt = rejected is not None and len(rejected) > 0
    system_prompt = REGENERATE_GO_FURTHER_PROMPT if use_regen_prompt else THREE_OPTION_EDIT_PROMPT

    chunks_block = _format_chunks_for_prompt(retrieved) if retrieved else "(no retrieved chunks)"

    user_parts = [
        f"INSTRUCTION:\n{instruction}",
        f"\nSCOPE: {scope}",
        f"\nCURRENT MEMO:\n{memo.to_text_with_ids()}",
        f"\nRETRIEVED FILING CHUNKS:\n{chunks_block}",
    ]

    if use_regen_prompt:
        rejected_block = "\n\n".join(
            f"[{o.label}] {o.new_text}" for o in rejected
        )
        user_parts.append(f"\nREJECTED OPTIONS (do not produce minor variations of these):\n{rejected_block}")

    user_msg = "\n".join(user_parts)

    try:
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini-0718"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=2500,
        )
        content = resp.choices[0].message.content or "{}"
        return _parse_edit_proposal(content, scope, memo)
    except Exception as e:
        # Fall back to a single trivial option so the UI never breaks
        return EditProposal(
            op="insert_after",
            anchor=scope if scope != "whole_memo" else "end_of_memo",
            variation_axis="length",
            options=[EditOption(
                label="Error",
                new_text=f"(call failed: {str(e)[:200]})",
                rationale="error fallback",
            )],
            note=f"error: {str(e)[:200]}",
        )


def _parse_edit_proposal(content: str, scope: str, memo: Memo) -> EditProposal:
    """Parse model output into an EditProposal, with defensive defaults."""
    try:
        data = json.loads(content)
    except Exception:
        data = {}

    edit_target = data.get("edit_target", {}) or {}
    op = edit_target.get("op", "insert_after")
    if op not in ("replace", "insert_after", "delete"):
        op = "insert_after"

    anchor = edit_target.get("anchor", "")
    if not anchor:
        anchor = scope if scope != "whole_memo" else "end_of_memo"

    # If the scope was a specific paragraph, force the anchor to match
    if scope != "whole_memo" and op != "insert_after":
        anchor = scope

    axis = data.get("variation_axis", "stance")
    if axis not in ("tone", "structure", "stance", "length"):
        axis = "stance"

    options_raw = data.get("options", []) or []
    options: list[EditOption] = []
    for o in options_raw:
        if not isinstance(o, dict):
            continue
        label = str(o.get("label", "Option"))[:40]
        new_text = str(o.get("new_text", "")).strip()
        rationale = str(o.get("rationale", ""))[:200]
        if new_text or op == "delete":
            options.append(EditOption(label=label, new_text=new_text, rationale=rationale))

    if not options:
        options = [EditOption(
            label="Unparseable",
            new_text="(Could not parse model response. Try again.)",
            rationale="parse error",
        )]

    note = str(data.get("note", ""))[:300]

    return EditProposal(
        op=op,
        anchor=anchor,
        variation_axis=axis,
        options=options[:3],
        note=note,
    )


def apply_edit(memo: Memo, proposal: EditProposal, chosen_option: EditOption) -> tuple[bool, str]:
    """Apply a chosen option to the memo.

    Returns (success, changed_paragraph_id).
    The changed_paragraph_id is the pid of the paragraph that was created or modified.
    """
    anchor = proposal.anchor
    op = proposal.op

    # Resolve anchor — try exact match first, then fuzzy
    target_pid = _resolve_anchor(memo, anchor)

    if op == "insert_after":
        if anchor == "end_of_memo" or target_pid is None:
            new_pid = memo.add_paragraph(chosen_option.new_text)
        else:
            new_pid = memo.add_paragraph(chosen_option.new_text, after_pid=target_pid)
        return True, new_pid

    if op == "replace":
        if target_pid is None:
            # Fall back to appending
            new_pid = memo.add_paragraph(chosen_option.new_text)
            return True, new_pid
        memo.replace_paragraph(target_pid, chosen_option.new_text)
        return True, target_pid

    if op == "delete":
        if target_pid is None:
            return False, ""
        memo.delete_paragraph(target_pid)
        return True, target_pid

    return False, ""


def _resolve_anchor(memo: Memo, anchor: str) -> Optional[str]:
    """Resolve an anchor string to a real paragraph ID."""
    if not anchor or anchor == "end_of_memo":
        return None

    # Direct ID match
    if memo.get(anchor) is not None:
        return anchor

    # Maybe the model returned the text of the paragraph. Fuzzy-match it.
    candidates = [(p.pid, p.text) for p in memo.paragraphs]
    if not candidates:
        return None

    # Try difflib closest match against the first 80 chars of each paragraph
    anchor_lower = anchor.lower()[:80]
    texts_lower = [t.lower()[:80] for _, t in candidates]
    matches = difflib.get_close_matches(anchor_lower, texts_lower, n=1, cutoff=0.6)
    if matches:
        idx = texts_lower.index(matches[0])
        return candidates[idx][0]

    return None


def ask_filing(client: Optional[AzureOpenAI], question: str, retrieved: list[Chunk]) -> str:
    """Answer a question about the filing without editing the memo."""
    if client is None:
        client = _get_client()

    chunks_block = _format_chunks_for_prompt(retrieved) if retrieved else "(no chunks retrieved)"
    user_msg = f"QUESTION:\n{question}\n\nRETRIEVED CHUNKS:\n{chunks_block}"

    try:
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini-0718"),
            messages=[
                {"role": "system", "content": ASK_FILING_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=800,
        )
        return resp.choices[0].message.content or "(no response)"
    except Exception as e:
        return f"(call failed: {str(e)[:200]})"


# --- Citation rendering ---

CITATION_PATTERN = re.compile(r"$$([0-9A-Z]+)·([¶pPtT])(\d+)$$")


def render_paragraph_html(text: str) -> str:
    """Render a paragraph's text with citation pills as HTML.

    Citations look like [1A·¶3] or [8·t4] in the source text.
    """
    # Basic HTML escape
    text = (text.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))

    def replace_citation(match: re.Match) -> str:
        item = match.group(1)
        kind = match.group(2)
        num = match.group(3)
        chunk_id = f"{item}.{'p' if kind in ('¶', 'p', 'P') else 't'}{num}"
        label = f"{item}·{'¶' if kind in ('¶', 'p', 'P') else 't'}{num}"
        return (
            f'<span class="citation-pill" data-chunk-id="{chunk_id}" '
            f'title="Source: {chunk_id}">{label}</span>'
        )

    return CITATION_PATTERN.sub(replace_citation, text)


def extract_citations(text: str) -> list[str]:
    """Return chunk IDs referenced in a paragraph."""
    out = []
    for m in CITATION_PATTERN.finditer(text):
        item = m.group(1)
        kind = m.group(2)
        num = m.group(3)
        chunk_id = f"{item}.{'p' if kind in ('¶', 'p', 'P') else 't'}{num}"
        out.append(chunk_id)
    return out
