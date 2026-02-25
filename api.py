"""
Production-grade headless REST API for 3D game integration.

Exposes src/engine RAG logic for a game engine (Unity/WebGL) without touching the Streamlit app.
Run separately: python api.py (or uvicorn api:app --host 0.0.0.0 --port 8000).

Game commands follow AI_GAME_MANIPULATION_SPEC.md (Command Router; bounded actions only).

Environment:
  GAME_API_KEY  Required for X-API-Key header (set in .env or Render/env).
  OPENAI_API_KEY, etc.  Same as main app (engine.py).
"""

import json
import os
import re
from typing import List, Literal, Optional

from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

# Load env before importing engine (uses Config)
from dotenv import load_dotenv
load_dotenv()

from src.engine import ask_assistant

# -----------------------------------------------------------------------------
# 1. Strict Data Models (Pydantic) — prevents malformed data reaching the game
# -----------------------------------------------------------------------------


class GameRequest(BaseModel):
    """Request from the game client. Validated so the API never forwards bad input to the engine."""
    session_id: str = Field(..., description="For chat memory / multi-user separation")
    question: str = Field(..., min_length=1, description="The user's prompt")
    selected_part: Optional[str] = Field(None, description="Part ID or P/N the user clicked in 3D (use as targetName when relevant)")


# Command payloads per AI_GAME_MANIPULATION_SPEC.md. Only these shapes are sent to the game.

class CameraFocusCommand(BaseModel):
    action: Literal["camera.focus"] = "camera.focus"
    targetName: str = Field(..., min_length=1)
    distance: float = Field(..., ge=0.1, le=100.0)
    durationMs: int = Field(..., ge=0, le=10000)


class ModelHighlightCommand(BaseModel):
    action: Literal["model.highlight"] = "model.highlight"
    targetName: str = Field(..., min_length=1)
    color: str = Field(default="#FFAA00", pattern=r"^#[0-9A-Fa-f]{6}$")
    intensity: float = Field(default=1.0, ge=0.0, le=2.0)
    durationMs: int = Field(default=2000, ge=0, le=30000)


class ModelExplodeCommand(BaseModel):
    action: Literal["model.explode"] = "model.explode"
    enabled: bool = True
    distance: float = Field(default=2.0, ge=0.0, le=10.0)
    speed: float = Field(default=1.0, ge=0.1, le=3.0)


class SceneSwitchCommand(BaseModel):
    action: Literal["scene.switch"] = "scene.switch"
    sceneId: Literal["helicopter", "cockpit", "engine"]


class ManualOpenCommand(BaseModel):
    action: Literal["manual.open"] = "manual.open"
    docId: str = Field(..., min_length=1)
    page: int = Field(..., ge=1, le=10000)


_ALLOWED_ACTIONS = frozenset({
    "camera.focus",
    "model.highlight",
    "model.explode",
    "scene.switch",
    "manual.open",
})

_COMMAND_MODELS: dict[str, type[BaseModel]] = {
    "camera.focus": CameraFocusCommand,
    "model.highlight": ModelHighlightCommand,
    "model.explode": ModelExplodeCommand,
    "scene.switch": SceneSwitchCommand,
    "manual.open": ManualOpenCommand,
}


class GameResponse(BaseModel):
    """Response to the game. Pydantic ensures JSON shape so Unity/WebGL never get wrong types."""
    text_reply: str = Field(..., description="The AI's conversational/procedural answer")
    sources: List[str] = Field(default_factory=list, description="Citations (e.g. 'AMM 24-30-00, Page 5')")
    game_command: Optional[dict] = Field(None, description="Optional command for the Command Router (see spec)")


# -----------------------------------------------------------------------------
# 2. API Security — X-API-Key checked against GAME_API_KEY
# -----------------------------------------------------------------------------

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_game_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)) -> str:
    """Dependency: require valid X-API-Key header."""
    expected = os.getenv("GAME_API_KEY", "").strip()
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: GAME_API_KEY is not set",
        )
    if not api_key or api_key != expected:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return api_key


app = FastAPI(
    title="Aircraft Maintenance Game API",
    description="Headless RAG API for 3D game integration (Ghost Director, Click & Ask, session memory).",
    version="1.0.0",
)

# CORS: required when the game (WebGL) runs in a browser on another origin (see togamedalil.md Tip 4).
# Set GAME_CORS_ORIGINS to comma-separated origins, e.g. "https://mygame.com,https://airmanual.onrender.com"
_origins = [o.strip() for o in os.getenv("GAME_CORS_ORIGINS", "").split(",") if o.strip()]
if not _origins:
    _origins = ["*"]  # allow all when unset (e.g. local dev / Postman)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

# -----------------------------------------------------------------------------
# 3. Endpoint: POST /api/chat — rulebook injected so LLM knows allowed commands
# -----------------------------------------------------------------------------

# Rulebook: allowed actions and exact JSON signatures (per AI_GAME_MANIPULATION_SPEC.md).
# Injected into the prompt so the LLM outputs only these shapes.
_GAME_COMMAND_RULEBOOK = """
When your answer involves locating a part, showing an assembly, or opening a manual, you MUST output exactly one game command as a single line at the end of your response.

Allowed actions and exact JSON signatures (use these verbatim):

1. Locate/focus on a part (camera flies to part):
   {"action": "camera.focus", "targetName": "<part_id>", "distance": <float 0.1-100>, "durationMs": <int 0-10000>}

2. Highlight a part:
   {"action": "model.highlight", "targetName": "<part_id>", "color": "#RRGGBB", "intensity": <float 0-2>, "durationMs": <int 0-30000>}
   (color optional, default #FFAA00; intensity default 1.0; durationMs default 2000)

3. Exploded view of an assembly:
   {"action": "model.explode", "enabled": true|false, "distance": <float 0-10>, "speed": <float 0.1-3>}
   (distance/speed optional; defaults 2.0 and 1.0)

4. Switch scene (helicopter overview, cockpit, or engine):
   {"action": "scene.switch", "sceneId": "helicopter"|"cockpit"|"engine"}

5. Open manual at a page:
   {"action": "manual.open", "docId": "<document id or name>", "page": <int 1-10000>}

Output format: End your reply with exactly one line: GAME_CMD: <valid JSON for one of the above>. Omit the GAME_CMD line if your answer does not involve locating a part, showing an assembly, or opening a manual.
"""

# Contextual awareness: when user asks about "this" part, use selected_part as targetName.
_CONTEXTUAL_AWARENESS = """
If the user asks "what is this?", "how do I fix this?", "how much does this weigh?", or similar, the request includes a selected_part (the part they clicked in 3D). Use that value as the targetName in your game command (e.g. camera.focus or model.highlight). Use the part ID exactly as provided.
"""

# Zero-hallucination / "miss" rule: when the exact procedure or data is NOT in the retrieved context, do not give generic advice or filler.
_ZERO_FILLER_ON_MISS = """
CRITICAL — When the answer is not in the provided documentation:
- If the exact procedure, torque, limit, or specification for the asked part is NOT found in the retrieved context, DO NOT give generic advice, guesses, or filler (e.g. "check the manual", "refer to the AMM", long disclaimers).
- Reply exactly with a short, explicit statement, e.g.: "The specific procedure for this part is not in the provided documentation. Please consult the AMM chapter for this system (e.g. Chapter 74 for ignition) directly." Then cite the most relevant document name from the context if available.
- Do NOT output a game_command.manual.open unless you know the exact docId and page number from the retrieved context. Do NOT guess "page": 1 or invent a docId.
"""


def _inject_selected_part(question: str, selected_part: Optional[str]) -> str:
    if not selected_part or not selected_part.strip():
        return question
    return f"The user is asking about part {selected_part.strip()}: {question}"


def _parse_game_command_from_reply(text: str) -> tuple[str, Optional[dict]]:
    """Extract GAME_CMD line from reply; validate against spec and return (cleaned_reply, command_dict or None)."""
    pattern = r"\n?\s*GAME_CMD:\s*(\{.*?\})\s*$"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if not match:
        return text.strip(), None
    json_str = match.group(1).strip()
    try:
        data = json.loads(json_str)
        if not isinstance(data, dict):
            clean = text[: match.start()].strip()
            return clean, None
        action = (data.get("action") or "").strip()
        if action not in _ALLOWED_ACTIONS:
            clean = text[: match.start()].strip()
            return clean, None
        model_cls = _COMMAND_MODELS.get(action)
        if not model_cls:
            clean = text[: match.start()].strip()
            return clean, None
        # Validate and coerce with Pydantic (enforces bounds and types)
        cmd = model_cls.model_validate(data)
        clean = text[: match.start()].strip()
        return clean, cmd.model_dump()
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    clean = text[: match.start()].strip()
    return clean, None


def _sources_to_citation_list(source_nodes: List[dict]) -> List[str]:
    """Convert engine source nodes to a simple list of citation strings."""
    out: List[str] = []
    for s in source_nodes or []:
        name = s.get("file_name") or "Unknown"
        page = s.get("page_number") or "Unknown"
        out.append(f"{name}, Page {page}")
    return out


@app.post("/api/chat", response_model=GameResponse)
def api_chat(
    body: GameRequest,
    _api_key: str = Depends(require_game_api_key),
) -> GameResponse:
    """
    Send a question (and optional selected part) and get an AI reply plus optional game command.

    - **session_id**: For future session memory (Mechanic A vs B); accepted and echoed.
    - **selected_part**: If set, the question is contextualized (Click & Ask); LLM uses it as targetName when relevant.
    - **game_command**: When the answer involves locating a part, showing an assembly, or opening a manual, the LLM may return a spec-compliant command (camera.focus, model.highlight, model.explode, scene.switch, manual.open).
    """
    question = _inject_selected_part(body.question, body.selected_part)
    prompt_parts = [
        _ZERO_FILLER_ON_MISS.strip(),
        _GAME_COMMAND_RULEBOOK.strip(),
        _CONTEXTUAL_AWARENESS.strip(),
    ]
    if body.selected_part:
        prompt_parts.append(f"USER SELECTED PART (use as targetName when relevant): {body.selected_part.strip()}")
    prompt_parts.append(f"USER QUESTION: {question}")
    question_for_engine = "\n\n".join(prompt_parts)

    # Call existing RAG/agent (skip regulation path for game/maintenance use)
    try:
        response_text, source_nodes = ask_assistant(
            question_for_engine,
            use_chat_mode=True,
            skip_regulation_check=True,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Engine error: {str(e)}") from e

    # Parse optional game command and clean reply
    text_reply, game_command = _parse_game_command_from_reply(response_text)
    # Strip LLM "null command" lines so the UI never shows robot logic (e.g. "GAME_CMD: None")
    for suffix in ("GAME_CMD: None", "GAME_CMD: none", "GAME_CMD: null", "GAME_CMD: N/A"):
        text_reply = text_reply.replace(suffix, "").strip()
    # Collapse any double newlines left by the removal
    while "\n\n\n" in text_reply:
        text_reply = text_reply.replace("\n\n\n", "\n\n")
    text_reply = text_reply.strip()
    sources = _sources_to_citation_list(source_nodes)

    return GameResponse(
        text_reply=text_reply,
        sources=sources,
        game_command=game_command,
    )


# -----------------------------------------------------------------------------
# 4. Safe execution — separate process from Streamlit
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
