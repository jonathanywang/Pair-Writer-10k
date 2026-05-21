# 10-K Pair-Writer

A Streamlit app for drafting investment memos against SEC 10-K filings, with GPT-4o as a writing partner. Every model-inserted claim is grounded in a citation back to the filing.

## Setup

1. Create a virtual environment and install dependencies:

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and add your OpenAI API key:

```bash
cp .env.example .env
# edit .env and set OPENAI_API_KEY
```

3. Run the app:

```bash
streamlit run app.py
```

## How to use

1. Paste an EDGAR 10-K filing URL into the top input. Use the "Filing Index" page URL or the direct HTML document URL.
   - Find filings at: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany
   - Example URL format: `https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm`

2. Wait for ingest + theme tagging (~30-60s for first load, instant on subsequent loads thanks to caching).

3. Start drafting your memo in the middle pane. Type rough thoughts, or use the right-side command bar to ask GPT-4o for help.

4. To target a specific paragraph, click "Select" next to it before typing your instruction. Otherwise the instruction applies to the whole memo.

5. The model returns 3 options. Pick one to apply, or click "Try 3 more" to regenerate.

6. Citations appear as `[1A·¶3]` pills. Click to scroll the filing pane to the source.

7. Export the memo via the Markdown or DOCX buttons in the header.

## Architecture

- `app.py` — Streamlit UI
- `ingest.py` — EDGAR fetch + parse → Filing object
- `tagging.py` — One-pass GPT-4o theme tagging
- `retrieval.py` — Embedding-based retrieval with theme filter + pins
- `edits.py` — Three-option edit generation, JSON schema, apply with fuzzy match
- `prompts.py` — System prompts
- `cache/` — Cached parsed + tagged filings (skip re-ingest)

## Visuals

<img width="2194" height="993" alt="Screenshot 2026-05-21 112256" src="https://github.com/user-attachments/assets/eacb85e3-df2a-44c5-8a31-09f9e1774f70" />
<img width="2195" height="1202" alt="Screenshot 2026-05-21 112406" src="https://github.com/user-attachments/assets/b027498e-1134-4d06-90bb-6c6a24b3731e" />
<img width="2123" height="1217" alt="image" src="https://github.com/user-attachments/assets/7164318d-a11c-4a3c-b6cd-b475b9a3760e" />
<img width="2150" height="1176" alt="image" src="https://github.com/user-attachments/assets/8b57a0ff-beaf-45f9-90f8-dfa32f7ed432" />



