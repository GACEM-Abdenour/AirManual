"""OpenAI token usage and cost tracking — persistent across restarts (local and Render)."""
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from llama_index.core.callbacks.base_handler import BaseCallbackHandler
from llama_index.core.callbacks.schema import CBEventType, EventPayload

from src.config import Config

# GPT-4o pricing per 1M tokens (as of 2024–2025)
GPT4O_INPUT_PER_1M = 2.50
GPT4O_OUTPUT_PER_1M = 10.00


def _get_tokens_from_payload(payload: Dict[str, Any]) -> Tuple[int, int]:
    """Extract (prompt_tokens, completion_tokens) from LLM event payload."""
    response = payload.get(EventPayload.RESPONSE)
    if response is None:
        completion = payload.get(EventPayload.COMPLETION)
        response = completion
    if response is None:
        return 0, 0
    usage = getattr(response, "additional_kwargs", None) or {}
    if isinstance(usage, dict):
        pass
    elif hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    else:
        usage = {}
    raw = getattr(response, "raw", None)
    if raw is not None and hasattr(raw, "usage"):
        u = raw.usage
        return (
            getattr(u, "prompt_tokens", 0) or getattr(u, "input_tokens", 0),
            getattr(u, "completion_tokens", 0) or getattr(u, "output_tokens", 0),
        )
    prompt_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
    return int(prompt_tokens), int(completion_tokens)


def _usage_file_path() -> str:
    """Path to the persistent usage JSON file (from Config.USAGE_FILE)."""
    return Config.USAGE_FILE


class _UsageStore:
    """
    Cumulative usage store backed by a JSON file.
    Survives restarts; same file on local and Render gives a single running total.
    """
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._path = _usage_file_path()
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._request_count = 0
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not os.path.isfile(self._path):
                return
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._prompt_tokens = int(data.get("prompt_tokens", 0))
                self._completion_tokens = int(data.get("completion_tokens", 0))
                self._request_count = int(data.get("request_count", 0))
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self) -> None:
        with self._lock:
            data = {
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "request_count": self._request_count,
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            dirpath = os.path.dirname(self._path)
            if dirpath:
                os.makedirs(dirpath, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

    def add(self, prompt: int, completion: int) -> None:
        with self._lock:
            self._prompt_tokens += prompt
            self._completion_tokens += completion
            self._request_count += 1
        self._save()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            total = self._prompt_tokens + self._completion_tokens
            cost = (
                self._prompt_tokens * GPT4O_INPUT_PER_1M
                + self._completion_tokens * GPT4O_OUTPUT_PER_1M
            ) / 1e6
            return {
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "total_tokens": total,
                "request_count": self._request_count,
                "estimated_cost_usd": round(cost, 4),
            }

    def reset(self) -> None:
        with self._lock:
            self._prompt_tokens = 0
            self._completion_tokens = 0
            self._request_count = 0
        self._save()


usage_store = _UsageStore()


class OpenAITokenCountingHandler(BaseCallbackHandler):
    """Callback handler that accumulates OpenAI token usage and persists it to disk."""

    def __init__(self) -> None:
        super().__init__(
            event_starts_to_ignore=[],
            event_ends_to_ignore=[],
        )

    def on_event_start(
        self,
        event_type: CBEventType,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        parent_id: str = "",
        **kwargs: Any,
    ) -> str:
        return event_id

    def on_event_end(
        self,
        event_type: CBEventType,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        if event_type != CBEventType.LLM or not payload:
            return
        prompt_tokens, completion_tokens = _get_tokens_from_payload(payload)
        if prompt_tokens or completion_tokens:
            usage_store.add(prompt_tokens, completion_tokens)

    def start_trace(self, trace_id: Optional[str] = None) -> None:
        pass

    def end_trace(
        self,
        trace_id: Optional[str] = None,
        trace_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        pass


def get_usage() -> Dict[str, Any]:
    """Return current cumulative usage and estimated cost (persistent total)."""
    return usage_store.snapshot()


def reset_usage() -> None:
    """Reset cumulative usage and overwrite the persisted file with zeros."""
    usage_store.reset()
