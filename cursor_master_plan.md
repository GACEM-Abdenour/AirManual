# Aircraft Maintenance Assistant - Master Plan

## Project Goal
Build an RAG-based assistant for aircraft maintenance that can handle technical manuals (PDFs), recognize part numbers, and follow cross-references.

## Tech Stack
* **LLM:** OpenAI (GPT-4o)
* **Embeddings:** OpenAI (text-embedding-3-small)
* **Parser:** Unstructured API (Hi-Res strategy for tables)
* **Vector DB:** Qdrant (Local mode)
* **Framework:** LlamaIndex
* **Frontend:** Streamlit

## Architecture Guidelines

### 1. Data Ingestion (Crucial)
* We must process PDFs using `Unstructured`.
* **Strategy:** Use `strategy="hi_res"` to correctly identify tables in Parts Catalogs.
* **Chunking:**
    * Text chunks must include metadata (Filename, Page Number, Section Header).
    * **Tables:** Must be extracted separately. Convert tables to JSON or Markdown text. We need to index the *content* of the table so part numbers are searchable.

### 2. Hybrid Search (Vector + Keyword)
* Aviation queries are specific ("Part 12-45A").
* We cannot rely on vector similarity alone.
* Use Qdrant's Hybrid Search capability (combining sparse vectors/BM25 for keywords and dense vectors for semantic meaning).

### 3. The Agentic Loop (Handling Cross-References)
* Use LlamaIndex `OpenAIAgent` or a ReAct pattern.
* If the LLM reads "Refer to Section 5.2", it must have a tool to query the database again for "Section 5.2".
* The system must cite sources (Document Name + Page).

### 4. Constraints
* Do not hallucinate. If info is missing, state it.
* Keep the UI clean.