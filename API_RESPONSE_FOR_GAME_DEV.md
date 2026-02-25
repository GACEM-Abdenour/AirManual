# API Response Structure for the Game Developer

This document explains how the **POST /api/chat** response is structured so the frontend can cleanly separate conversational text, citations, and executable 3D commands.

---

## 1. Final JSON payload shape

Every successful response from **POST /api/chat** is a single JSON object with exactly three top-level fields:

```json
{
  "text_reply": "string",
  "sources": ["string", "..."],
  "game_command": { ... } | null
}
```

| Field           | Type            | Meaning |
|----------------|-----------------|--------|
| **text_reply** | `string`        | The AI’s conversational answer. Safe to show in the in-game chat/UI. Never contains raw `GAME_CMD:` lines or JSON. |
| **sources**    | `array` of `string` | Citation strings (e.g. `"AMM 24-30-00, Page 5"`). For the manual/references UI only. |
| **game_command** | `object` or `null` | Optional command for your Command Router. When present, it is a spec-compliant action object; when absent, it is `null`. |

**Example:**

```json
{
  "text_reply": "The oil filter is on the engine module. I've focused the camera and opened the relevant manual page.",
  "sources": ["AMM 24-30-00, Page 5", "AMM 24-30-00, Page 6"],
  "game_command": {
    "action": "camera.focus",
    "targetName": "OilFilter_01",
    "distance": 2.5,
    "durationMs": 1500
  }
}
```

When there is no 3D action:

```json
{
  "text_reply": "General maintenance is scheduled every 500 flight hours.",
  "sources": ["AMM 12-00-00, Page 1"],
  "game_command": null
}
```

---

## 2. How the backend guarantees separation

- **Strict response model**  
  The backend uses a Pydantic `GameResponse` model. Every response is validated and serialized through it. So the game **always** receives exactly these three fields with the types above: `text_reply` (string), `sources` (array of strings), `game_command` (object or null).

- **Conversational text never contains command syntax**  
  The LLM may output a line like `GAME_CMD: {...}` at the end of its reply. The backend:
  - Detects and parses that line with a regex.
  - Validates the JSON against the allowed actions and Pydantic command models.
  - Puts the validated object **only** in `game_command`.
  - Puts **only** the text *before* that line (and after stripping “GAME_CMD: None” etc.) into `text_reply`.  
  So `text_reply` is **never** mixed with raw `GAME_CMD:` or JSON; it is purely conversational.

- **Citations come from retrieval metadata, not from the LLM text**  
  `sources` is built from the RAG engine’s source nodes (e.g. `file_name`, `page_number`), not parsed from the model’s reply. So citations are a separate, structured list and do not appear inside `text_reply`.

- **Game commands are validated before they are sent**  
  Only whitelisted actions (`camera.focus`, `model.highlight`, `model.explode`, `scene.switch`, `manual.open`) and their spec-compliant shapes pass validation. Invalid or unknown commands are discarded and `game_command` is set to `null`; the rest of the reply still appears in `text_reply` and `sources`.

So: **conversational text**, **citations**, and **game command** are produced by different pipeline steps and combined into one strict JSON shape. The game never has to parse `GAME_CMD:` or citations out of the reply string.

---

## 3. How the game developer should extract and route

1. **Parse the JSON**  
   Parse the response body once as JSON. You get one object with `text_reply`, `sources`, and `game_command`.

2. **Conversational text → chat/UI**  
   Use `response.text_reply` (or `response["text_reply"]`) as the only source for the text shown in the in-game chat or dialogue UI. Do not concatenate or mix in `sources` or `game_command` for the main message.

3. **Citations → manual/references UI**  
   Use `response.sources` (or `response["sources"]`) to drive your “Sources” or “References” panel. Render each string as one citation (e.g. one line or one chip). Do not show these inside the main chat bubble if you want to keep narrative and references separate.

4. **Game command → Command Router**  
   - If `response.game_command` is `null` or missing, do nothing for 3D.  
   - If it is an object, read `response.game_command.action` and route to your Command Router:
     - `camera.focus` → camera logic (use `targetName`, `distance`, `durationMs`).
     - `model.highlight` → highlight a part (use `targetName`, `color`, `intensity`, `durationMs`).
     - `model.explode` → explode view (use `enabled`, `distance`, `speed`).
     - `scene.switch` → change scene (use `sceneId`: `"helicopter"` | `"cockpit"` | `"engine"`).
     - `manual.open` → open manual (use `docId`, `page`).  
   Execute exactly one command per response; do not re-execute the same command if you reuse the same reply.

**Pseudocode:**

```text
data = parseJson(responseBody)

// 1. Show conversation
chatUI.appendMessage(data.text_reply)

// 2. Show citations
referencesPanel.setCitations(data.sources)

// 3. Execute 3D command if present
if (data.game_command != null) {
  switch (data.game_command.action) {
    case "camera.focus":    cameraFocus(data.game_command); break
    case "model.highlight": modelHighlight(data.game_command); break
    case "model.explode":   modelExplode(data.game_command); break
    case "scene.switch":    sceneSwitch(data.game_command); break
    case "manual.open":     manualOpen(data.game_command); break
  }
}
```

This keeps chat, citations, and 3D actions on separate code paths and avoids mixing LLM text with executable payloads.
