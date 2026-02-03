# ✈️ Aircraft Maintenance Documentation Assistant

RAG-based assistant for aircraft maintenance: technical manuals (PDF/HTML), part numbers, regulations, and cross-references. Uses **OpenAI** (GPT-4o, embeddings), **Qdrant** (vector store), **Unstructured** (parsing), and **Streamlit** (UI).

---

## Prerequisites

- **Python 3.10+**
- **API keys:** OpenAI, Unstructured, and (for production) Qdrant Cloud

---

## Environment Variables

Create a `.env` file in the project root (see `.env.example` if present, or use this template):

```env
# Required for app and ingest
OPENAI_API_KEY=sk-...
UNSTRUCTURED_API_KEY=...
UNSTRUCTURED_API_URL=https://platform.unstructuredapp.io

# Required for production (Qdrant Cloud). Omit for local-only.
QDRANT_URL=https://your-cluster.europe-west3-0.gcp.cloud.qdrant.io:6333
QDRANT_API_KEY=...
```

- **Local only:** Leave `QDRANT_URL` unset. The app uses `./qdrant_db` (create index with `python src/ingest.py` first).
- **Production:** Set `QDRANT_URL` and `QDRANT_API_KEY` to your Qdrant Cloud cluster. The app uses **dense-only** search on Cloud; local uses **hybrid** (dense + sparse) when available.

---

## Run Locally

```bash
# Install dependencies
pip install -r requirements.txt

# (Optional) Ingest documents into the index (skip if using Qdrant Cloud with existing data)
python src/ingest.py

# Start the app
streamlit run app.py
```

Open the URL shown in the terminal (e.g. `http://localhost:8501`).

---

## Deployment (Recommended: Streamlit Community Cloud)

1. **Push the repo** to GitHub (omit `.env`; use `.gitignore`).
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. **New app** → select this repo, branch, main file: `app.py`.
4. **Advanced settings** → add **Secrets** (same keys as `.env`):

   ```toml
   OPENAI_API_KEY = "sk-..."
   UNSTRUCTURED_API_KEY = "..."
   UNSTRUCTURED_API_URL = "https://platform.unstructuredapp.io"
   QDRANT_URL = "https://your-cluster....cloud.qdrant.io:6333"
   QDRANT_API_KEY = "..."
   ```

5. Deploy. The app runs in the cloud and talks to **Qdrant Cloud** and **OpenAI**; no local Qdrant or VPN needed.

**Other options:** Railway, Render, Fly.io, or a small VPS — run `streamlit run app.py` and expose the port. Always use **secrets** or env vars for keys; never commit `.env`.

---

## Data Ingestion

- **PDFs and HTML** under `assets/` are parsed with the Unstructured API and indexed into Qdrant.
- **First run:**  
  `python src/ingest.py`  
  (Uses `.env`; requires OpenAI + Unstructured keys.)
- **Reset and re-index:**  
  `python src/ingest.py --reset`
- **Crawl regulations (HTML):**  
  `python src/crawl.py --url "https://example.com/regs" --max-pages 500`  
  or `python src/crawl.py --all` to crawl all configured URLs. Then run `python src/ingest.py` to index the downloaded HTML.

Ingest state is stored in `data/ingest_state.json`; parsed chunks are cached under `data/parsed/`.

---

## Migration: Local Qdrant → Qdrant Cloud

If you have a large local index (`./qdrant_db`) and want to move it to Qdrant Cloud with **compression** (INT8) and **dense-only** vectors:

1. Set `QDRANT_URL` and `QDRANT_API_KEY` in `.env` to your Cloud cluster.
2. In Qdrant Cloud, delete the target collection if it already exists (so the script can create it with quantization).
3. Run:  
   `python migrate_robust.py`  
   The script scrolls the local collection, creates the Cloud collection with Scalar INT8 quantization, and upserts in batches (checkpointed; resumable on failure).
4. When finished, the app (local or deployed) uses Cloud as long as `QDRANT_URL` is set.

**Note:** The script reads from local `qdrant_db` and writes to Cloud. Stop any app using `qdrant_db` while migrating.

---

## Optional Scripts

- **`estimate_regulations_cost.py`** — Estimates Unstructured API “page” usage (and thus cost) for HTML files under `assets/regulations/` (parsing cost only, not embeddings).  
  Run: `python estimate_regulations_cost.py`

---

## Project Layout

```
aircraft/
├── app.py                 # Streamlit entrypoint
├── pages/                 # Streamlit multi-page (Logbook, Auditor)
├── src/
│   ├── config.py          # Env and config
│   ├── engine.py          # RAG, agent, query engine
│   ├── index_store.py     # Qdrant client, index, dense vs hybrid
│   ├── ingest.py          # Unstructured + Qdrant indexing
│   └── crawl.py           # Regulations HTML crawler
├── migrate_robust.py      # Local → Cloud migration (resumable)
├── estimate_regulations_cost.py
├── assets/                # PDFs and HTML (and regulations crawl output)
├── data/                  # ingest_state.json, parsed cache
├── requirements.txt
└── README.md
```

- **Local Qdrant data:** `qdrant_db/` (created when `QDRANT_URL` is not set).
- **Secrets:** `.env` (never commit; use Streamlit Secrets or platform env for deploy).

---

## Design Notes

High-level architecture and constraints (RAG, hybrid search, agentic loop, citations) are described in **`cursor_master_plan.md`**.

---

## License

Use and modify as needed for your context.
