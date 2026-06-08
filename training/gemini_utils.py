"""Shared synchronous Gemini helper for DictaBERT data-preparation scripts.

Uses Gemini's OpenAI-compatible endpoint (same pattern as server/app/context_agent/
clients/gemini_client.py but SYNCHRONOUS for use in data-prep scripts that are not
async). Reads GEMINI_API_KEY via python-dotenv from server/.env.

Model: gemini-2.5-flash
Mode: json_object + reasoning_effort=none (avoids thinking-truncation)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_DEFAULT_MODEL = "gemini-2.5-flash"
_MAX_RETRIES = 4
_BASE_BACKOFF = 2.0  # seconds, exponential


def _load_key() -> str:
    """Load GEMINI_API_KEY from server/.env (relative to the repo root)."""
    # Walk up from this file's directory to find server/.env
    here = Path(__file__).resolve()
    repo_root = here.parent.parent  # training/ -> repo root
    env_path = repo_root / "server" / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise EnvironmentError(
            f"GEMINI_API_KEY not found. Looked in env and {env_path}"
        )
    return key


class GeminiSync:
    """Thin synchronous wrapper around the Gemini OpenAI-compatible endpoint.

    Usage:
        g = GeminiSync()
        result = g.call_json(messages=[{"role": "user", "content": "..."}])
        # result is a Python dict parsed from the JSON response
    """

    def __init__(self, model: str = _DEFAULT_MODEL) -> None:
        self._model = model
        self._client = OpenAI(api_key=_load_key(), base_url=_BASE_URL)

    def call_json(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.3,
        max_retries: int | None = None,
        base_backoff: float | None = None,
    ) -> dict[str, Any]:
        """Call Gemini with JSON mode; return parsed dict. Retries on transient errors.

        Args:
            max_retries: Override the default _MAX_RETRIES (4). Set to 1 for fast-fail
                         (translation scripts where retrying the same input won't help).
            base_backoff: Override _BASE_BACKOFF (2.0). Set to 0.3 for fast-fail cases.
        """
        n_retries = _MAX_RETRIES if max_retries is None else max_retries
        backoff = _BASE_BACKOFF if base_backoff is None else base_backoff
        last_exc: Exception | None = None
        for attempt in range(n_retries):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    extra_body={"reasoning_effort": "none"},
                )
                raw = response.choices[0].message.content or ""
                # Strip markdown fences in case Gemini adds them despite json_object mode
                raw = raw.strip()
                if raw.startswith("```"):
                    lines = raw.splitlines()
                    raw = "\n".join(
                        l for l in lines if not l.startswith("```")
                    ).strip()
                return json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                wait = backoff * (2**attempt)
                print(
                    f"  [gemini_utils] attempt {attempt + 1}/{n_retries} failed: "
                    f"{type(exc).__name__}: {exc}. Retrying in {wait:.1f}s..."
                )
                time.sleep(wait)
        raise RuntimeError(
            f"Gemini call failed after {n_retries} retries"
        ) from last_exc

    def call_json_batch(
        self,
        batch_messages: list[list[dict[str, str]]],
        max_tokens: int = 512,
        temperature: float = 0.3,
        delay_between: float = 0.3,
    ) -> list[dict[str, Any] | Exception]:
        """Call call_json for each item in batch; return list of dicts or Exceptions."""
        results: list[dict[str, Any] | Exception] = []
        for i, messages in enumerate(batch_messages):
            try:
                result = self.call_json(messages, max_tokens=max_tokens, temperature=temperature)
                results.append(result)
            except Exception as exc:  # noqa: BLE001
                results.append(exc)
            if delay_between > 0 and i < len(batch_messages) - 1:
                time.sleep(delay_between)
        return results
