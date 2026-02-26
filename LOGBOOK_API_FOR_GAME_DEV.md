# Logbook Forensic Audit API — Game Developer Integration

This document answers how to call the Logbook Map/Reduce forensic audit from the game (Unity/WebGL) and how the backend is wired so you can rely on the same behavior as the Streamlit UI.

---

## 1. Data Ingestion: How should the game send logbook data?

**Use a JSON array of logbook rows in the request body.** Do not use CSV/Excel upload (multipart/form-data) for this endpoint.

| Option | Recommendation | Reason |
|--------|----------------|--------|
| **JSON array** | ✅ **Use this** | The engine expects a **list of rows** with fixed fields (`Component`, `Part_Number`, `Hours_Since_New`, `Installed_Date`). The existing Map/Reduce logic in `engine.py` iterates over rows and builds one micro-prompt per row. Sending JSON matches that model exactly: the API converts each entry to the internal row dict and passes the list to `run_logbook_forensic_audit(rows)`. No file parsing, no extra I/O. |
| **CSV/Excel upload** | ❌ Not needed for this flow | The Streamlit UI uses CSV **only** to populate the table; the actual audit runs on the in-memory DataFrame (same row shape). If the game already has structured logbook data (e.g. from its own save or UI), sending it as JSON is simpler and type-safe. If you later want “paste CSV” from the game, we could add a separate endpoint that accepts multipart file and returns the same JSON response after parsing CSV → rows. |

**Summary:** Send `POST /api/logbook/analyze` with a JSON body: `{ "entries": [ { "component", "part_number", "hours_since_new", "installed_date" }, ... ] }`. This is the best fit for the current engine logic and keeps the pipeline identical to the Streamlit flow.

---

## 2. Endpoint Design: Request, Response, and Route

**Route:** `POST /api/logbook/analyze`  
**Auth:** Same as chat: `X-API-Key` header (required).

### Request (Pydantic)

| Model | Field | Type | Description |
|-------|--------|------|-------------|
| **LogbookRowRequest** | `component` | `string` (required, min 1) | Component name (e.g. "Main Rotor Blades", "Magneto") |
| | `part_number` | `string` (optional, default `""`) | Part number from IPC; empty if unknown (system will look up) |
| | `hours_since_new` | `float \| null` (optional, ≥ 0) | Total hours on component since new |
| | `installed_date` | `string \| null` (optional) | Date installed, `YYYY-MM-DD` |
| **LogbookAnalyzeRequest** | `entries` | `array` of **LogbookRowRequest** (min 1) | Logbook rows to analyze |

**Example request body:**

```json
{
  "entries": [
    {
      "component": "Main Rotor Blades",
      "part_number": "C016-7",
      "hours_since_new": 1779.5,
      "installed_date": null
    },
    {
      "component": "Magneto",
      "part_number": "10-600646-201",
      "hours_since_new": 726.0,
      "installed_date": null
    },
    {
      "component": "ELT Battery",
      "part_number": "",
      "hours_since_new": null,
      "installed_date": null
    }
  ]
}
```

### Response (Pydantic)

| Model | Field | Type | Description |
|-------|--------|------|-------------|
| **CitationSource** | `file_name` | `string` | Document name (e.g. "AMM 24-30-00") |
| | `page_number` | `string \| int` | Page number or "Unknown" |
| **ComponentAudit** | `component` | `string` | Component name |
| | `part_number` | `string` | P/N as provided or "Looked up by system" |
| | `report` | `string` | 3-bullet compliance/remaining-life summary (markdown, AMM citations) |
| | `sources` | `array` of **CitationSource** | Citations for this component |
| **LogbookAnalyzeResponse** | `system_wide_anomaly_report` | `string` | Markdown: Critical Anomalies, Maintenance Forecast, Recommendations |
| | `anomaly_sources` | `array` of **CitationSource** | Sources for the anomaly report |
| | `component_audits` | `array` of **ComponentAudit** | One audit per requested component (same order as request) |

---

## 3. Wiring: How the endpoint hooks into the engine (429-safe)

The new endpoint does **not** reimplement the Map/Reduce logic. It calls a single engine function that mirrors the Streamlit flow:

1. **API**  
   - Validates the body with **LogbookAnalyzeRequest**.  
   - Converts each `LogbookRowRequest` to the internal row shape (`Component`, `Part_Number`, `Hours_Since_New`, `Installed_Date`).  
   - Calls **`run_logbook_forensic_audit(rows)`** in `src/engine.py`.

2. **Engine (`run_logbook_forensic_audit`)**  
   - **Map phase:** For each row, builds the same micro-prompt as Streamlit, calls **`ask_assistant(micro_prompt, use_chat_mode=True, skip_regulation_check=True)`**, appends to `component_reports`. After each row (except the last), **`time.sleep(8)`** to avoid burst traffic and 429s.  
   - **Deep Research:** Unchanged. Inside `ask_assistant`, if retrieval confidence is below threshold, the engine runs the existing Deep Research path (expanded retrieval, query variations, truncation at 40k chars).  
   - **Reduce phase:** Truncates each report to **2,500** chars and caps total context at **18,000** chars (same constants as Streamlit), builds `full_context`, then one **`ask_assistant(synthesis_prompt, ...)`** to produce the System-Wide Anomaly Report.  
   - Returns `(component_reports, synthesis_response, synthesis_sources)`.

3. **API**  
   - Maps engine results into **LogbookAnalyzeResponse** (anomaly report, anomaly_sources, component_audits with citation objects) and returns JSON.

**Rate-limit (429) behavior:** The 8-second delay between Map rows, the Reduce-phase truncation (2,500 / 18,000 chars), and the Deep Research context cap (40k chars) are all inside `run_logbook_forensic_audit`. The REST endpoint is a thin wrapper; no extra parallelization or batching is introduced, so the existing 429 fixes remain in effect.

---

## 4. Response Payload: How the System-Wide Anomaly Report is packaged

The final JSON has three top-level fields. Use them as follows in the game UI:

### 4.1 `system_wide_anomaly_report` (string, markdown)

This is the **System-Wide Anomaly Report** produced in the Reduce phase. It is meant to be shown in a prominent block (e.g. warning-style panel) at the top of the logbook results screen.

- **Content:** Free-form markdown from the LLM, structured under:
  - **Critical Anomalies** — safety-critical issues (e.g. component replaced but dependent inspection not done).
  - **Maintenance Forecast** — next maintenance windows and priorities.
  - **Recommendations** — specific actions for compliance.
- **Rendering:** Use a markdown-capable UI control. No need to parse sections programmatically unless you want to split into tabs or sections; the backend does not return structured bullets, only the single markdown string.

**Example (conceptual):**

```text
**Critical Anomalies:** ...
**Maintenance Forecast:** ...
**Recommendations:** ...
```

### 4.2 `anomaly_sources` (array of citations)

Citations for the anomaly report itself (document + page). Use for a “Sources” or “References” area next to the report.

- Each element: `{ "file_name": "AMM 24-30-00", "page_number": 5 }` (or `"Unknown"`).
- Optional: show as “Source 1: AMM 24-30-00, Page 5” etc.

### 4.3 `component_audits` (array of per-component audits)

One object per requested logbook row, in the **same order** as `entries` in the request.

- **Use:** Expandable/collapsible rows or detail panels: component name, part number, full report text, and per-component sources.
- **Fields:**
  - `component`, `part_number` — for the row header/label.
  - `report` — markdown 3-bullet summary (Part Number Found / Limit Found, Current Status, Remaining Life) with AMM citations.
  - `sources` — list of `{ "file_name", "page_number" }` for that component.

**Example response (minimal):**

```json
{
  "system_wide_anomaly_report": "**Critical Anomalies:** ...\n\n**Maintenance Forecast:** ...\n\n**Recommendations:** ...",
  "anomaly_sources": [
    { "file_name": "AMM 24-30-00", "page_number": 5 }
  ],
  "component_audits": [
    {
      "component": "Main Rotor Blades",
      "part_number": "C016-7",
      "report": "• **Part Number Found:** P/N: C016-7 - **Limit Found:** ...\n• **Current Status:** COMPLIANT - ...\n• **Remaining Life:** ...",
      "sources": [
        { "file_name": "AMM 20-10-00", "page_number": 12 }
      ]
    }
  ]
}
```

**Suggested game UI layout:**

1. **Top:** One panel with `system_wide_anomaly_report` (markdown) and, optionally, `anomaly_sources` as references.
2. **Below:** List of `component_audits`; each row shows component name and P/N, expandable to show `report` (markdown) and `sources`.

This matches the Streamlit “System-Wide Anomaly Report” + “Individual Component Audits” structure so the game can replicate the same UX from a single API response.
