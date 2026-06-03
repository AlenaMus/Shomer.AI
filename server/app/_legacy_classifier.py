"""Reusable text-classification helper.

Both the ``/classify`` endpoint and the OCR image backend need to take a
Hebrew text and run it through the Ollama text classifier. This module
hosts the shared function so neither has to know about the other.
"""

from __future__ import annotations

from .ollama_client import OllamaClient
from .prompt import build_user_prompt, parse_model_output


async def classify_text(ollama: OllamaClient, text: str) -> dict:
    """Classify ``text`` via the configured Ollama text model.

    Returns a dict with keys ``is_offensive`` (bool), ``category`` (str),
    ``confidence`` (float 0.0–1.0). Raises whatever :class:`OllamaClient`
    or :func:`parse_model_output` raise on transport / parse failure —
    the caller is responsible for translating those into HTTP errors.
    """
    prompt = build_user_prompt(text)
    raw = await ollama.generate_json(prompt)
    return parse_model_output(raw)
