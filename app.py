"""10-K Pair-Writer — Streamlit app.

Two-pane layout with collapsible utility sections: Filing | History (expanders) + Report | Command (main).
"""

from __future__ import annotations

import ssl_patch  # ← line 1 of every file

import os
import time
from dataclasses import dataclass

import streamlit as st
from dotenv import load_dotenv

from openai import AzureOpenAI

from ingest import ingest, save_cached, load_cached, Filing
from tagging import tag_filing, all_themes_in_filing
from retrieval import build_embeddings, retrieve
from edits import (
    Memo, Paragraph, EditProposal, EditOption,
    generate_three_options, apply_edit, ask_filing,
    render_paragraph_html, extract_citations,
)
from export import memo_to_markdown, memo_to_docx
from ingest import ITEM_TITLES



load_dotenv()

st.set_page_config(
    page_title="10-K Pair-Writer",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --- Custom CSS for the two-pane layout with utility expanders ---

st.markdown("""
<style>
.block-container { 
    padding-top: 3rem; 
    padding-bottom: 1rem; 
    max-width: 100% !important; 
}
            


/* Main panes — taller now that there are only two */
.pane {
    background: #fff;
    border: 1px solid #e8e6df;
    border-radius: 8px;
    padding: 16px 18px;
    height: calc(100vh - 280px);
    overflow-y: auto;
    font-size: 13px;
}

/* Utility expanders — compact */
.streamlit-expanderHeader {
    font-size: 12px !important;
    font-weight: 600 !important;
    color: #185FA5 !important;
    background: #F1EFE8 !important;
    border-radius: 6px !important;
}

.streamlit-expanderContent {
    max-height: 400px;
    overflow-y: auto;
    border: 1px solid #e8e6df;
    border-top: none;
    border-radius: 0 0 6px 6px;
    padding: 10px;
    font-size: 12px;
}

.pane-header {
    font-size: 11px;
    font-weight: 600;
    color: #888780;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 8px;
    padding-bottom: 6px;
    border-bottom: 1px solid #eee;
}

.citation-pill {
    background: #E6F1FB;
    color: #0C447C;
    font-size: 11px;
    padding: 1px 7px;
    border-radius: 10px;
    font-weight: 500;
    cursor: pointer;
    margin: 0 2px;
    display: inline-block;
    white-space: nowrap;
}
.citation-pill:hover {
    background: #B5D4F4;
}

/* Report pane gets more prominence */
.memo-paragraph {
    margin: 0 0 14px 0;
    padding: 10px 12px;
    border-radius: 6px;
    line-height: 1.8;
    border: 1px solid transparent;
    font-size: 14px;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.memo-paragraph.selected {
    background: transparent;
    border-color: #185FA5;
    box-shadow: 0 0 0 1px rgba(24, 95, 165, 0.25);
}
}
.memo-paragraph.just-changed {
    background: transparent;
    border-left: 2px solid #BA7517;
}

.filing-para {
    font-size: 11px;
    line-height: 1.5;
    color: #5F5E5A;
    padding: 4px 6px;
    margin-bottom: 6px;
    border-radius: 3px;
}
.filing-para.highlighted {
    background: transparent;
    color: #5F5E5A;
}
.filing-para .chunk-label {
    font-weight: 600;
    color: #185FA5;
    margin-right: 6px;
}
            
/* Keep trigger button small */
div[data-testid="stPopover"] > button {
    width: auto !important;
    min-width: 0 !important;
    padding: 0 8px !important;
}

/* Wide popover content when open */
div[data-testid="stPopoverBody"] {
    width: 520px !important;
    max-width: 90vw !important;
}

.theme-chip {
    display: inline-block;
    font-size: 10px;
    padding: 2px 7px;
    border-radius: 10px;
    margin: 2px 3px 2px 0;
    background: #F1EFE8;
    color: #5F5E5A;
}
.theme-chip.active {
    background: transparent;
    color: #633806;
    font-weight: 600;
}

.option-card {
    background: transparent;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 8px;
    padding: 12px;
    margin: 6px 0;
    font-size: 12px;
    line-height: 1.6;
    color: #E5E7EB;
    transition:
        border-color 0.15s ease,
        box-shadow 0.15s ease,
        background 0.15s ease;
}

.option-card:hover {
    border-color: rgba(24, 95, 165, 0.55);
    box-shadow: 0 0 0 1px rgba(24, 95, 165, 0.18);
    background: rgba(255,255,255,0.015);
}
.option-card .label {
    font-weight: 700;
    color: #6EA8FE;
    font-size: 11px;
    text-transform: uppercase;
    margin-bottom: 8px;
    letter-spacing: 0.03em;
}

.option-card .rationale {
    color: #8B949E;
    font-size: 10px;
    font-style: italic;
    margin-top: 8px;
}

.option-card p,
.option-card div,
.option-card span {
    color: #E6EDF3 !important;
}

.history-item {
    font-size: 11px;
    padding: 8px 10px;
    margin-bottom: 6px;
    border: 1px solid transparent;
    border-left: 2px solid #444;
    border-radius: 6px;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.history-item.latest {
    background: transparent;
    border-color: rgba(24, 95, 165, 0.45);
    border-left-color: #185FA5;
    box-shadow: 0 0 0 1px rgba(24, 95, 165, 0.18);
}
.history-item .when {
    color: #888780;
    font-size: 10px;
}

.scope-indicator {
    font-size: 11px;
    color: #185FA5;
    font-weight: 600;
    margin: 4px 0;
}

/* Command pane section dividers */
.section-divider {
    display: flex;
    align-items: center;
    margin: 16px 0 10px 0;
    gap: 8px;
}
.section-divider span {
    font-size: 11px;
    font-weight: 600;
    color: #185FA5;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    white-space: nowrap;
}
.section-divider::before,
.section-divider::after {
    content: '';
    flex: 1;
    height: 1px;
    background: #e0ddd6;
}

.chat-user {
    background: rgba(59,130,246,0.07);
    border: 1px solid rgba(59,130,246,0.2);
    border-radius: 14px;
    padding: 12px;
    margin-bottom: 6px;
}

.chat-ai {
    background: #0d1117;
    border: 1px solid #1e2530;
    border-radius: 14px;
    padding: 14px;
    margin-bottom: 14px;
}

.chat-role {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    color: #60A5FA;
    margin-bottom: 8px;
    letter-spacing: 0.08em;
}

.chat-content {
    font-size: 13px;
    line-height: 1.7;
    color: #E5E7EB;
}

.action-footer {
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px dashed #2B3548;
}

.empty-hint {
    
    border: 1px dashed #2B3548;
    border-radius: 14px;
    padding: 14px;
    background: rgba(255,255,255,0.02);
}

.empty-hint ul {
    margin: 8px 0 0 18px;
    color: #9CA3AF;
    font-size: 12px;
    line-height: 1.7;
}


/* compact source rows */
.sources-row {
    position: relative;
    margin-bottom: 6px;
}

/* compact card */
.sources-card {
    border: 1px solid rgba(59,130,246,0.65);
    border-radius: 10px;

    padding: 8px 36px 8px 10px;

    background: transparent;
}

/* tighter text */
.source-id {
    font-size: 10px;
    line-height: 1;
    margin-bottom: 4px;
}

.source-preview {
    font-size: 10px;
    line-height: 1.3;
}
            
/* Green Save button — first button in inline edit row */
.inline-edit-row div[data-testid="stHorizontalBlock"] > div:first-child button {
    background-color: #16a34a !important;
    border-color: #16a34a !important;
    color: white !important;
}
.inline-edit-row div[data-testid="stHorizontalBlock"] > div:first-child button:hover {
    background-color: #15803d !important;
    border-color: #15803d !important;
    color: white !important;
}
            
/* Inline edit textarea */
.inline-edit-active {
    border: 2px solid #185FA5 !important;
    border-radius: 6px;
    background: rgba(24, 95, 165, 0.05);
}
            
.section-title {
    margin-bottom: 6px;
}
            
</style>
""", unsafe_allow_html=True)


# --- Session state ---

def _init_state():
    if "filing" not in st.session_state:
        st.session_state.filing = None
    if "embeddings" not in st.session_state:
        st.session_state.embeddings = None
    if "memo" not in st.session_state:
        st.session_state.memo = Memo()
        st.session_state.memo.add_paragraph(
            "Start your report here. Type rough thoughts directly into a paragraph, "
            "or use the command bar on the right to ask AI for help."
        )
    if "selected_pid" not in st.session_state:
        st.session_state.selected_pid = None
    if "current_proposal" not in st.session_state:
        st.session_state.current_proposal = None
    if "rejected_options" not in st.session_state:
        st.session_state.rejected_options = []
    if "last_changed_pid" not in st.session_state:
        st.session_state.last_changed_pid = None
    if "last_changed_at" not in st.session_state:
        st.session_state.last_changed_at = 0
    if "history" not in st.session_state:
        st.session_state.history = []
    if "active_themes" not in st.session_state:
        st.session_state.active_themes = []
    if "active_item_filter" not in st.session_state:
        st.session_state.active_item_filter = None
    if "pinned_chunk_ids" not in st.session_state:
        st.session_state.pinned_chunk_ids = []
    if "last_retrieved" not in st.session_state:
        st.session_state.last_retrieved = []
    if "last_instruction" not in st.session_state:
        st.session_state.last_instruction = ""
    if "ask_response" not in st.session_state:
        st.session_state.ask_response = None
    if "highlighted_chunk_id" not in st.session_state:
        st.session_state.highlighted_chunk_id = None

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    if "command_input" not in st.session_state:
        st.session_state.command_input = ""

    if "active_mode" not in st.session_state:
        st.session_state.active_mode = "edit"

_init_state()


def _get_client() -> AzureOpenAI:
    api_key     = os.environ.get("OPENAI_API_KEY")
    api_version = os.environ.get("OPENAI_API_VERSION")
    api_base    = os.environ.get("OPENAI_API_BASE_URL")
    return AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=api_base,
    )


def _push_history(label: str):
    """Snapshot current report state and push to history."""
    snap = st.session_state.memo.snapshot()
    st.session_state.history.append({
        "snapshot": snap,
        "label": label,
        "when": time.time(),
    })
    if len(st.session_state.history) > 50:
        st.session_state.history = st.session_state.history[-50:]


def _format_time_ago(ts: float) -> str:
    diff = time.time() - ts
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    return f"{int(diff // 3600)}h ago"


# --- HEADER ---

if st.session_state.filing:
    header_cols = st.columns([4, 1, 1, 1])
else:
    header_cols = st.columns([1])

with header_cols[0]:
    if st.session_state.filing:
        st.markdown(
            f"### 10-K Pair-Writer · `{st.session_state.filing.company_name[:60]}`"
        )
    else:
        st.markdown("### 10-K Pair-Writer")


# ONLY SHOW THESE AFTER A FILING IS LOADED
if st.session_state.filing:

    with header_cols[1]:
        if st.button(
            "↶ Undo",
            use_container_width=True,
            disabled=len(st.session_state.history) < 2,
        ):
            if len(st.session_state.history) >= 2:
                st.session_state.history.pop()
                prev = st.session_state.history[-1]
                st.session_state.memo.restore(prev["snapshot"])
                st.session_state.last_changed_pid = None
                st.rerun()

    with header_cols[2]:
        md_data = memo_to_markdown(
            st.session_state.memo,
            title=f"Report — {st.session_state.filing.company_name[:40]}",
        )

        st.download_button(
            "📋 MD",
            data=md_data,
            file_name="report.md",
            mime="text/markdown",
            use_container_width=True,
        )

    with header_cols[3]:
        docx_data = memo_to_docx(
            st.session_state.memo,
            title="Investment Report",
            filing_name=st.session_state.filing.company_name[:60],
        )

        st.download_button(
            "📄 DOCX",
            data=docx_data,
            file_name="report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )


# --- FILING LOAD ROW ---

if st.session_state.filing is None:
    st.markdown("---")
    st.markdown("#### Load a 10-K filing")
    st.markdown(
        "Paste an EDGAR 10-K HTML document URL. "
        "Example: `[sec.gov](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm)`"
    )
    url = st.text_input("EDGAR URL", key="filing_url_input")
    if st.button("Load filing", type="primary"):
        if not url.strip():
            st.error("Please paste an EDGAR URL.")
        else:
            client = _get_client()

            cached = load_cached(url.strip())
            if cached is not None and any(c.themes for c in cached.chunks):
                # Fix up missing company name on cached filings
                if not cached.company_name or cached.company_name == "Unknown Filing":
                    from ingest import _fetch_company_name_from_edgar
                    name = _fetch_company_name_from_edgar(url.strip())
                    if name:
                        cached.company_name = name
                        save_cached(cached)
                st.session_state.filing = cached
                with st.spinner("Loading embeddings..."):
                    st.session_state.embeddings = build_embeddings(cached, client=client)
                st.success("Loaded from cache.")
                _push_history("Loaded filing")
                st.rerun()
            else:
                try:
                    with st.spinner("Fetching filing from EDGAR..."):
                        filing = ingest(url.strip(), use_cache=False)
                    if not filing.chunks:
                        st.error("No content extracted. Check that the URL points to a 10-K HTML document.")
                        st.stop()
                    st.info(f"Parsed {len(filing.chunks)} chunks across {len(filing.items_present)} items. Tagging themes...")
                    prog = st.progress(0.0)

                    def _cb(done, total):
                        prog.progress(done / max(total, 1))

                    filing = tag_filing(filing, client=client, progress_callback=_cb)
                    prog.empty()
                    st.info("Building embeddings...")
                    eprog = st.progress(0.0)

                    def _ecb(done, total):
                        eprog.progress(done / max(total, 1))

                    st.session_state.embeddings = build_embeddings(filing, client=client, progress_callback=_ecb)
                    eprog.empty()
                    save_cached(filing)
                    st.session_state.filing = filing
                    _push_history("Loaded filing")
                    st.success(f"Loaded {filing.company_name}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Ingest failed: {e}")
    st.stop()


# --- TWO-PANE BODY WITH UTILITY EXPANDERS ---

filing: Filing = st.session_state.filing
memo: Memo = st.session_state.memo
client = _get_client()


# === UTILITY EXPANDERS: FILING + HISTORY ===

util_col1, util_col2 = st.columns([1, 1])

with util_col1:
    with st.expander("Filing: Browse & Filter", expanded=False):
        # Item nav
        item_options = ["(All Items)"] + filing.items_present
        item_labels = ["(All Items)"] + [
            f"{item}: {ITEM_TITLES.get(item, '')}" if ITEM_TITLES.get(item) else item
            for item in filing.items_present
        ]

        label_to_item = dict(zip(item_labels, item_options))
        item_to_label = dict(zip(item_options, item_labels))

        selected_label = st.selectbox(
            "Item",
            item_labels,
            index=item_labels.index(
                item_to_label.get(st.session_state.active_item_filter, "(All Items)")
            ),
            key="item_select",
            label_visibility="collapsed",
        )

        selected_item = label_to_item[selected_label]
        st.session_state.active_item_filter = selected_item if selected_item != "(All Items)" else None

        # Theme filter chips
        available_themes = all_themes_in_filing(filing)
        st.markdown("**Themes**")
        theme_cols = st.columns(3)
        for i, theme in enumerate(available_themes):
            with theme_cols[i % 3]:
                is_active = theme in st.session_state.active_themes
                label = ("✓ " if is_active else "") + theme.replace("_", " ")
                if st.button(label, key=f"theme_{theme}", use_container_width=True):
                    if is_active:
                        st.session_state.active_themes.remove(theme)
                    else:
                        st.session_state.active_themes.append(theme)
                    st.rerun()

        # Filing text view
        item_to_show = st.session_state.active_item_filter
        if item_to_show is None and filing.items_present:
            item_to_show = filing.items_present[0]

        if item_to_show:
            chunks_to_show = filing.chunks_by_item(item_to_show)
            if st.session_state.active_themes:
                chunks_to_show = [c for c in chunks_to_show if any(t in c.themes for t in st.session_state.active_themes)]

            highlighted = st.session_state.highlighted_chunk_id
            last_retrieved_ids = {c.chunk_id for c in st.session_state.last_retrieved}

            html_parts = [f"<div style='font-weight:600;margin-bottom:6px;'>{item_to_show}</div>"]
            for c in chunks_to_show[:50]:
                is_highlighted = (c.chunk_id == highlighted) or (c.chunk_id in last_retrieved_ids)
                cls = "filing-para highlighted" if is_highlighted else "filing-para"
                text_preview = c.text[:400] + ("..." if len(c.text) > 400 else "")
                text_preview = text_preview.replace("<", "&lt;").replace(">", "&gt;")
                html_parts.append(
                    f"<div class='{cls}' id='chunk-{c.chunk_id}'>"
                    f"<span class='chunk-label'>[{c.chunk_id}]</span>{text_preview}"
                    f"</div>"
                )
            st.markdown("\n".join(html_parts), unsafe_allow_html=True)

with util_col2:
    with st.expander("History: Revert Changes", expanded=False):
        hist = list(reversed(st.session_state.history))
        for i, h in enumerate(hist[:30]):
            cls = "history-item latest" if i == 0 else "history-item"
            when = _format_time_ago(h["when"])
            st.markdown(
                f"<div class='{cls}'>"
                f"<div class='when'>{when}</div>"
                f"<div>{h['label']}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if i > 0:
                if st.button("Revert", key=f"revert_{i}", use_container_width=True):
                    target_index = len(st.session_state.history) - 1 - i
                    target = st.session_state.history[target_index]
                    memo.restore(target["snapshot"])
                    st.session_state.history = st.session_state.history[:target_index + 1]
                    st.session_state.last_changed_pid = None
                    st.rerun()


# === MAIN TWO-COLUMN LAYOUT: MEMO + COMMAND ===

col_memo, col_command = st.columns([6, 3.5])


# === LEFT PANE: MEMO ===
with col_memo:
    st.markdown('<div class="pane-header">REPORT</div>', unsafe_allow_html=True)

    just_changed = st.session_state.last_changed_pid
    show_change_flash = (
        just_changed
        and (time.time() - st.session_state.last_changed_at) < 30
    )

    if "editing_pid" not in st.session_state:
        st.session_state.editing_pid = None

    for p in memo.paragraphs:
        is_selected = p.pid == st.session_state.selected_pid
        is_changed = show_change_flash and (p.pid == just_changed)
        is_editing = p.pid == st.session_state.editing_pid

        cls = "memo-paragraph"
        if is_selected:
            cls += " selected"
        if is_changed:
            cls += " just-changed"

        para_cols = st.columns([1, 11, 1])

        with para_cols[0]:
            if st.button("☐" if not is_selected else "☑", key=f"sel_{p.pid}", help="Select for targeted edit"):
                st.session_state.selected_pid = None if is_selected else p.pid
                st.rerun()

        with para_cols[1]:
            if is_editing:
                new_text = st.text_area(
                    "Edit directly",
                    value=p.text,
                    key=f"edit_{p.pid}",
                    height=max(100, len(p.text) // 3),
                    label_visibility="collapsed",
                )
                st.markdown('<div class="inline-edit-row">', unsafe_allow_html=True)
                save_col, cancel_col, delete_col = st.columns([2, 2, 1])
                with save_col:
                    if st.button("Save", key=f"save_{p.pid}", use_container_width=True):
                        if new_text != p.text:
                            _push_history(f"Manually edited {p.pid}")
                            memo.replace_paragraph(p.pid, new_text)
                            st.session_state.last_changed_pid = p.pid
                            st.session_state.last_changed_at = time.time()
                        st.session_state.editing_pid = None
                        st.rerun()
                with cancel_col:
                    if st.button("Cancel", key=f"cancel_{p.pid}", use_container_width=True):
                        st.session_state.editing_pid = None
                        st.rerun()
                with delete_col:
                    if st.button("🗑", key=f"del_{p.pid}", use_container_width=True, type="primary"):
                        _push_history(f"Deleted {p.pid}")
                        memo.delete_paragraph(p.pid)
                        st.session_state.editing_pid = None
                        st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                rendered_html = render_paragraph_html(p.text)
                st.markdown(
                    f'<div class="{cls}">{rendered_html}</div>',
                    unsafe_allow_html=True,
                )

        with para_cols[2]:
            if not is_editing:
                if st.button("✎", key=f"edit_btn_{p.pid}", help="Edit this paragraph"):
                    st.session_state.editing_pid = p.pid
                    st.rerun()
            else:
                st.empty()

    if st.button("+ Add empty paragraph", use_container_width=True):
        _push_history("Added paragraph")
        new_pid = memo.add_paragraph("")
        st.session_state.selected_pid = new_pid
        st.rerun()

    # --- Option cards (if a proposal is pending) ---
    proposal: EditProposal = st.session_state.current_proposal
    if proposal:
        st.markdown("---")
        st.markdown(
            f'<div class="pane-header">3 OPTIONS · {proposal.variation_axis.upper()}'
            f'{" · " + proposal.note if proposal.note else ""}</div>',
            unsafe_allow_html=True,
        )

        opt_cols = st.columns(len(proposal.options))
        for i, opt in enumerate(proposal.options):
            with opt_cols[i]:
                preview = opt.new_text[:200] + ("..." if len(opt.new_text) > 200 else "")
                preview_html = render_paragraph_html(preview)
                st.markdown(
                    f"<div class='option-card'>"
                    f"<div class='label'>{opt.label}</div>"
                    f"<div>{preview_html}</div>"
                    f"<div class='rationale'>{opt.rationale}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if st.button(f"Apply", key=f"apply_{i}", use_container_width=True, type="primary"):
                    _push_history(f"Applied {opt.label}")
                    success, changed_pid = apply_edit(memo, proposal, opt)
                    if success:
                        st.session_state.last_changed_pid = changed_pid
                        st.session_state.last_changed_at = time.time()
                    st.session_state.current_proposal = None
                    st.session_state.rejected_options = []
                    st.rerun()

        regen_cols = st.columns([3, 1, 1])
        with regen_cols[1]:
            if st.button("Try 3 more", use_container_width=True):
                st.session_state.rejected_options = list(proposal.options)
                with st.spinner("Generating 3 more options..."):
                    scope = st.session_state.selected_pid or "whole_memo"
                    new_prop = generate_three_options(
                        client=client,
                        memo=memo,
                        instruction=st.session_state.last_instruction,
                        retrieved=st.session_state.last_retrieved,
                        scope=scope,
                        rejected=st.session_state.rejected_options,
                    )
                    st.session_state.current_proposal = new_prop
                st.rerun()
        with regen_cols[2]:
            if st.button("Cancel", use_container_width=True):
                st.session_state.current_proposal = None
                st.session_state.rejected_options = []
                st.rerun()


# === RIGHT PANE: COMMAND ===
with col_command:
    selected_para = None

    if st.session_state.selected_pid:
        for p in memo.paragraphs:
            if p.pid == st.session_state.selected_pid:
                selected_para = p
                break

    if selected_para:

        preview = selected_para.text[:220]

        st.markdown(
            f"""
            <div class="scope-card">
                <div class="scope-label"><b>Currently Editing</b></div>
                <div class="scope-text">{preview}...</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("Clear Paragraph Selection", use_container_width=True):
            st.session_state.selected_pid = None
            st.rerun()

    else:

        st.markdown(
            """
            <div class="scope-card">
                <div class="helper-text">
                    Select a paragraph on the left for targeted editing.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )



    # =====================================================
    # CUSTOM INSTRUCTION
    # =====================================================

    st.markdown('<div class="section-title">Custom Instruction</div>', unsafe_allow_html=True)

    custom_instruction = st.text_area(
        "Instruction",
        placeholder="e.g. add China tariff exposure with exact percentages and cite supporting evidence",
        key="command_input",
        label_visibility="collapsed",
    )

    final_instruction = custom_instruction.strip()

    # =====================================================
    # EMPTY STATE GUIDANCE
    # =====================================================

    if not st.session_state.chat_history and not st.session_state.current_proposal:

        st.markdown(
            """
            <div class="empty-hint">
                <div class="section-title">Try Asking AI To...</div>
                <ul>
                    <li>Add supporting evidence from the filing</li>
                    <li>Strengthen the investment thesis</li>
                    <li>Add downside risks</li>
                    <li>Rewrite for clarity and flow</li>
                    <li>Explain revenue growth drivers</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # =====================================================
    # GENERATE
    # =====================================================
    st.markdown('<div style="margin-top: 12px;"></div>', unsafe_allow_html=True)

    if st.button(
        "Generate 3 Options",
        type="primary",
        use_container_width=True,
    ):

        if not final_instruction:
            st.warning("Add an instruction first.")

        else:

            st.session_state.last_instruction = final_instruction

            with st.spinner("Retrieving relevant filing sections..."):

                retrieved = retrieve(
                    filing=filing,
                    embeddings=st.session_state.embeddings,
                    query=final_instruction,
                    client=client,
                    top_k=6,
                    theme_filter=st.session_state.active_themes or None,
                    pinned_ids=st.session_state.pinned_chunk_ids,
                )

                st.session_state.last_retrieved = retrieved

            with st.spinner("Generating options..."):

                scope = st.session_state.selected_pid or "whole_memo"

                proposal = generate_three_options(
                    client=client,
                    memo=memo,
                    instruction=final_instruction,
                    retrieved=retrieved,
                    scope=scope,
                )

                st.session_state.current_proposal = proposal
                st.session_state.rejected_options = []

            st.rerun()

    # =====================================================
    # ASK FILING
    # =====================================================

    st.markdown('---')

    st.markdown('<div class="section-title">Research Question</div>', unsafe_allow_html=True)

    ask_query = st.text_area(
        "Research Question",
        placeholder="Ask anything about the filing...",
        key="ask_input_v2",
        height=100,
        label_visibility="collapsed",
    )

    if st.button("Ask Filing", use_container_width=True):

        if not ask_query.strip():
            st.warning("Enter a question.")

        else:

            with st.spinner("Searching filing..."):

                retrieved = retrieve(
                    filing=filing,
                    embeddings=st.session_state.embeddings,
                    query=ask_query,
                    client=client,
                    top_k=6,
                    theme_filter=st.session_state.active_themes or None,
                    pinned_ids=st.session_state.pinned_chunk_ids,
                )

                st.session_state.last_retrieved = retrieved

                answer = ask_filing(client, ask_query, retrieved)

            st.session_state.chat_history.append({
                "question": ask_query,
                "answer": answer,
            })

            st.rerun()

    # =====================================================
    # CONVERSATION
    # =====================================================

    if st.session_state.chat_history:

        st.markdown('---')

        st.markdown('<div class="section-title">Conversation</div>', unsafe_allow_html=True)

        st.markdown('<div class="chat-thread">', unsafe_allow_html=True)

        for idx, item in enumerate(reversed(st.session_state.chat_history[-6:])):

            q = item["question"]
            a = item["answer"]

            rendered = render_paragraph_html(a)

            st.markdown(
                f"""
                <div class="chat-user">
                    <div class="chat-role">You</div>
                    <div class="chat-content">{q}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown(
                f"""
                <div class="chat-ai">
                    <div class="chat-role">AI</div>
                    <div class="chat-content">{rendered}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            action_cols = st.columns(2)

            with action_cols[0]:
                if st.button(
                    "+ Insert Into Report",
                    key=f"insert_chat_{idx}",
                    use_container_width=True,
                ):

                    _push_history("Inserted AI response")
                    memo.add_paragraph(a)
                    st.rerun()

            with action_cols[1]:

                if selected_para:

                    if st.button(
                        "+ Append To Selected",
                        key=f"append_chat_{idx}",
                        use_container_width=True,
                    ):

                        _push_history("Expanded paragraph")

                        updated_text = selected_para.text + "\n\n" + a

                        memo.replace_paragraph(
                            selected_para.pid,
                            updated_text,
                        )

                        st.session_state.last_changed_pid = selected_para.pid
                        st.session_state.last_changed_at = time.time()

                        st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

    # =====================================================
    # SOURCES
    # =====================================================

    if st.session_state.last_retrieved:

        with st.expander("Retrieved Sources", expanded=False):

            for c in st.session_state.last_retrieved:

                is_pinned = c.chunk_id in st.session_state.pinned_chunk_ids

                preview = (
                    c.text[:140]
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )

                st.markdown(
                    f"""
                    <div class="sources-card">
                        <div class="source-id"><b>{c.chunk_id}</b></div>
                        <div class="source-preview">{preview}...</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )