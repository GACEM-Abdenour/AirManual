# Logbook Forensic Audit — Technical Flow

**Document purpose:** Step-by-step architectural breakdown of the Logbook analysis execution flow when the user clicks **"Generate Maintenance & Compliance Plan"**.  
**Scope:** `pages/1_Logbook.py` (UI + orchestration) and `src/engine.py` (RAG, agent, deep research, truncation).

---

## 1. Entry Point and Initialization

| Step | Location | Description |
|------|----------|-------------|
| 1.1 | `1_Logbook.py` | User clicks **"🔍 Generate Maintenance & Compliance Plan"** (`st.button`). |
| 1.2 | `1_Logbook.py` | If `edited_df` is empty → show warning and stop. |
| 1.3 | `1_Logbook.py` | Initialize: `total_rows = len(edited_df)`, `progress_bar`, `status_text`, `component_reports = []`, `component_sources = []`. |

---

## 2. Map Phase (Row-by-Row Deep Audit)

### 2.1 Row Iteration

- **Loop:** `for idx, (row_idx, row) in enumerate(edited_df.iterrows())`
- **Per row:** Extract `Component`, `Part_Number`, `Hours_Since_New`, `Installed_Date`. Normalize:
  - Part number: treat `NaN`, `""`, or whitespace-only as missing → `part_number = ""`.
  - Date: format for display (`strftime("%Y-%m-%d")` or `"Not specified"`).
  - Hours: `f"{hours:.1f} hours"` or `"Not specified"`.

### 2.2 Micro-Prompting (Per Component)

For **each row**, a single **micro_prompt** is built and sent to the assistant. It encodes:

- **Component details:** Name, Part Number (or `"Not provided - you must look it up"`), Hours Since New, Date Installed.
- **Search instruction (branching):**
  - **If P/N provided:**  
    *"Search the Aircraft Maintenance Manual (AMM) for the exact flight hour limit OR calendar time limit for Part Number {part_number}. If not found, search by component name \"{component}\"."*
  - **If P/N not provided:**  
    *"FIRST: Search the Illustrated Parts Catalog (IPC) or AMM to find the Part Number for component \"{component}\". THEN search for the exact flight hour limit OR calendar time limit using the Part Number you found (or component name if P/N still not found)."*
- **Audit tasks:**  
  1. Execute the search instruction.  
  2. Search for mandated inspection/replacement procedure.  
  3. Compute current status (COMPLIANT / DUE SOON within 10% / OVERDUE) using hours and/or calendar.  
  4. Compute remaining life.
- **Output format:** 3-bullet summary: **Part Number Found / Limit Found**, **Current Status**, **Remaining Life**, with AMM citations.

### 2.3 Per-Row Agent Call

- **API:** `ask_assistant(micro_prompt, use_chat_mode=True, skip_regulation_check=True)`.
- **Engine behavior:** Uses the **agent** (not regulation path); agent can use retrieval tools for multi-step lookup and cross-references.
- **Result:** `(response_text, source_nodes)` appended to `component_reports` (and `component_sources` extended). On exception, append an error report and empty sources.

### 2.4 Anti-Burst Logic (Rate Limit / TPM)

- **After each component** (except the last):  
  `if idx + 1 < total_rows: time.sleep(8)`  
- **Purpose:** Space out requests to stay under ~30k TPM and avoid 429s.
- **UX:** Progress bar text set to `"Rate limit cooldown... moving to next component"` during the delay.

---

## 3. Deep Research Trigger (Engine-Side)

**When:** After the agent (or query engine) returns, inside `ask_assistant()`.

### 3.1 Confidence Threshold

- **Constant:** `DEEP_RESEARCH_CONFIDENCE_THRESHOLD = 0.70` (`src/engine.py`).
- **Logic:**  
  - Collect `scores` from `source_nodes` (only entries with non-`None` score).  
  - `top_score = max(scores, default=1.0)`.  
  - **If** `scores` is non-empty **and** `top_score < 0.70` → run **Deep Research** and **replace** `(response_text, source_nodes)` with its result.

### 3.2 Expanded Retrieval (Similarity Top-K and Cap)

- **Expanded retriever:**  
  `expanded_k = min(int(1.5 * similarity_top_k), 30)`  
  - Example: `similarity_top_k=20` → `expanded_k=30`; `similarity_top_k=10` → `expanded_k=15`.
- **Usage:**  
  - **Original question:** retrieved with `similarity_top_k=expanded_k` (up to 30 chunks).  
  - **Query variations:** retrieved with **original** `similarity_top_k` (no expansion).

### 3.3 Query Variations

- **Function:** `_generate_query_variations(question, llm)`.
- **Behavior:** LLM is asked to produce alternative phrasings for searching aviation manuals (synonyms, technical terms, broader scope).  
- **Count used in Deep Research:** `variations = _generate_query_variations(question, llm)[:2]` → **2 variations** (reduced from 3 to limit context and burst).
- **Deduplication:** Nodes from original + each variation are merged by stable node id (`_get_node_id`); duplicates are dropped.

### 3.4 Deep Research Synthesis

- **Context:** Built from the merged node list, then **truncated** (see Section 4.2).
- **Prompt:** `DEEP_RESEARCH_SYSTEM_PROMPT` + context + user question; asks for **Direct Answer**, **Reasoning**, **Related Data** with citations.
- **Output:** Replaces the initial response and source list when the confidence check triggers.

---

## 4. Context Truncation (429 / TPM Mitigation)

### 4.1 Reduce Phase: Component Reports (Logbook Page)

**Location:** `pages/1_Logbook.py`, before building `full_context` for the synthesis prompt.

| Constant | Value | Approx. Tokens | Role |
|----------|--------|-----------------|------|
| `MAX_CHARS_PER_REPORT` | **2,500** | ~600 per component | Per-component report text cap. |
| `MAX_TOTAL_CONTEXT_CHARS` | **18,000** | ~4,500 total | Cap for all component blocks combined. |

**Truncation helper:**

```python
def truncate(s: str, max_len: int) -> str:
    s = (s or "").strip()
    return s[:max_len] + ("..." if len(s) > max_len else "")
```

**Assembly:**

- Each block: `"**{component}** (P/N: {part_number})\n\n" + truncate(report, MAX_CHARS_PER_REPORT)`.
- If adding a block would exceed `MAX_TOTAL_CONTEXT_CHARS`, that block is truncated to `max(500, MAX_TOTAL_CONTEXT_CHARS - total_len - 100)`.
- Stop appending blocks when `total_len >= MAX_TOTAL_CONTEXT_CHARS`.
- If any report was truncated or total cap was hit, prefix the assembled string with:  
  `"(Reports truncated for token limit.)\n\n"`.

**Result:** `full_context` is the string passed into the **synthesis prompt** as "COMPONENT AUDIT REPORTS", keeping the Reduce phase well under token/TPM limits.

### 4.2 Deep Research: Retrieval Context (Engine)

**Location:** `src/engine.py`, inside `_run_deep_research()`.

| Constant | Value | Approx. Tokens | Role |
|----------|--------|-----------------|------|
| `MAX_CHARS` | **40,000** | ~10,000 | Cap for combined retrieval context sent to the LLM. |

**Assembly:**

- Iterate over `all_nodes` (merged from original + variation retrievals).
- Append each node’s text to `context_parts` until `current_len + len(text) > MAX_CHARS`, then **break** (no further nodes).
- `context_str = "\n\n---\n\n".join(context_parts)`.
- If not all nodes were included: prefix  
  `"(Context truncated: {len(context_parts)} of {len(all_nodes)} nodes)\n\n"`.

This keeps Deep Research requests within context-window and TPM limits and is the **429 fix** for the deep-research path.

---

## 5. Reduce Phase (Synthesis)

### 5.1 Full-Context Assembly (Recap)

- **Input:** `component_reports` (each: `component`, `part_number`, `report`, `sources`).
- **Caps:** Per-report 2,500 chars; total 18,000 chars (see Section 4.1).
- **Output:** `full_context = "\n\n---\n\n".join(parts)` with optional truncation notice.

### 5.2 Synthesis Prompt

- **Role:** *"You are a Senior Aerospace Engineer performing a final forensic review of a compiled component audit."*
- **Body:**  
  - **COMPONENT AUDIT REPORTS:** `full_context`.  
  - **ANOMALY DETECTION TASKS:**  
    1. Cross-Component Logic Check (e.g. A replaced but B not inspected per AMM; inconsistent patterns; missing dependencies).  
    2. Maintenance Pattern Analysis (out-of-sequence replacements; missing inspections; calendar vs hour limits).  
    3. System-Wide Forecast (immediate attention, next critical window, cascading requirements).  
  - **OUTPUT FORMAT:** A **"System-Wide Anomaly Report"** with:  
    - **Critical Anomalies**  
    - **Maintenance Forecast**  
    - **Recommendations**

### 5.3 Final Agent Call

- **API:** `ask_assistant(synthesis_prompt, use_chat_mode=True, skip_regulation_check=True)`.
- **Result:** `synthesis_response`, `synthesis_sources`.
- **Display:** Progress set to 100%; status "✅ Forensic Audit Complete".

---

## 6. Pedagogical Output (Phase 3)

- **System-Wide Anomaly Report:** Rendered at top in a warning-style block: `st.warning("⚠️ **SYSTEM-WIDE ANOMALY REPORT**")` + `st.markdown(synthesis_response)`.
- **Anomaly sources:** Optional expander "Anomaly Detection Sources" with file name and page number per source.
- **Individual Component Audits:** Each `component_reports` entry in an expander: component name, P/N, full report, and per-component sources.

---

## 7. Summary Table

| Phase | Where | Main behavior |
|-------|--------|----------------|
| **Map** | `1_Logbook.py` | `iterrows()` → micro_prompt per row → `ask_assistant(..., use_chat_mode=True)` → `time.sleep(8)` between rows. |
| **Deep Research trigger** | `engine.py` | If `top_score < 0.70` → expanded_k = min(1.5×top_k, 30), 2 query variations, merge + dedupe nodes. |
| **Context truncation (Reduce)** | `1_Logbook.py` | 2,500 chars/report, 18,000 chars total for synthesis context. |
| **Context truncation (Deep Research)** | `engine.py` | 40,000 chars (~10k tokens) for retrieval context in `_run_deep_research`. |
| **Reduce** | `1_Logbook.py` | Build `full_context` from truncated reports → synthesis prompt → `ask_assistant` → System-Wide Anomaly Report. |

---

*Generated for post–429-fix Logbook Forensic Audit flow. Token estimates assume ~4 chars/token.*
