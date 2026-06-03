from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["abusive", "hate", "violence", "pornographic", "non_offensive"]


class ClassifyRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000, description="Hebrew text to classify")


class ClassifyResponse(BaseModel):
    is_offensive: bool
    category: Category
    confidence: float = Field(..., ge=0.0, le=1.0)
    model: str
    latency_ms: int


class ClassifyImageResponse(BaseModel):
    """Response from ``POST /classify-image``.

    Looser than :class:`ClassifyResponse`: ``category`` is a free-form string
    because Phase 1 stub uses ``"stub"`` and Phase 2 backends may emit
    categories outside the strict ``Category`` enum (e.g. ``"no_text"``).
    ``extracted_text``, ``backend``, ``strategy`` are diagnostic fields that
    let the client and the architecture study see what actually happened.
    """

    is_offensive: bool
    category: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    model: str
    latency_ms: int
    extracted_text: str = ""
    backend: str
    strategy: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    ollama_reachable: bool
    model: str


class ModelInfoResponse(BaseModel):
    model: str
    base: str | None = None
    labels: list[Category] = ["abusive", "hate", "violence", "pornographic", "non_offensive"]
