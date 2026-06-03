from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .classifier import classify_text
from .image_backends import (
    ImageProcessor,
    OcrBackend,
    OcrOnly,
    Parallel,
    Pipeline,
    StubImageProcessor,
    VisionBackend,
    VisionOnly,
)
from .middleware import AuditLoggingMiddleware
from .ollama_client import OllamaClient
from .schemas import (
    ClassifyImageResponse,
    ClassifyRequest,
    ClassifyResponse,
    HealthResponse,
    ModelInfoResponse,
)

load_dotenv()

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL_NAME = os.environ.get("MODEL_NAME", "offensive-hebrew:v1")
VISION_MODEL_NAME = os.environ.get("VISION_MODEL_NAME", "qwen2.5vl:7b")
TIMEOUT_S = float(os.environ.get("REQUEST_TIMEOUT_S", "60"))
# Vision inference is 5–15× slower than text — give it more headroom.
VISION_TIMEOUT_S = float(os.environ.get("VISION_TIMEOUT_S", "180"))
IMAGE_STRATEGY = os.environ.get("IMAGE_STRATEGY", "pipeline")
# Windows default install path. On Linux/macOS leave unset and rely on PATH.
TESSERACT_CMD = os.environ.get(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
)

VALID_STRATEGIES = {"ocr_only", "vision_only", "pipeline", "parallel", "stub"}


def _build_image_processors(
    text_ollama: OllamaClient,
    vision_ollama: OllamaClient,
    tesseract_cmd: str | None,
) -> dict[str, ImageProcessor]:
    """Construct all four real strategies plus the stub once at startup.

    Backends are shared across strategies (one ``OcrBackend`` instance, one
    ``VisionBackend`` instance) — strategies are thin composers over them.
    """
    ocr = OcrBackend(text_ollama, tesseract_cmd=tesseract_cmd)
    vision = VisionBackend(vision_ollama)
    return {
        "ocr_only": OcrOnly(ocr),
        "vision_only": VisionOnly(vision),
        "pipeline": Pipeline(ocr, vision),
        "parallel": Parallel(ocr, vision),
        "stub": StubImageProcessor(),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = OllamaClient(OLLAMA_URL, MODEL_NAME, TIMEOUT_S)
    app.state.vision_client = OllamaClient(OLLAMA_URL, VISION_MODEL_NAME, VISION_TIMEOUT_S)

    app.state.image_processors = _build_image_processors(
        text_ollama=app.state.client,
        vision_ollama=app.state.vision_client,
        tesseract_cmd=TESSERACT_CMD if os.path.exists(TESSERACT_CMD) else None,
    )

    if IMAGE_STRATEGY not in VALID_STRATEGIES:
        raise RuntimeError(
            f"IMAGE_STRATEGY={IMAGE_STRATEGY!r} is not one of {sorted(VALID_STRATEGIES)}"
        )
    app.state.default_strategy = IMAGE_STRATEGY

    yield
    await app.state.client.aclose()
    await app.state.vision_client.aclose()


app = FastAPI(title="Offensive-Hebrew Classifier", version="0.3.0", lifespan=lifespan)

# Middleware order: add_middleware applies in reverse, so the LAST one added is
# outermost on the request path. Audit goes last so it wraps everything else.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(AuditLoggingMiddleware)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    alive = await app.state.client.is_alive()
    return HealthResponse(
        status="ok" if alive else "degraded",
        ollama_reachable=alive,
        model=MODEL_NAME,
    )


@app.get("/model/info", response_model=ModelInfoResponse)
async def model_info() -> ModelInfoResponse:
    return ModelInfoResponse(model=MODEL_NAME)


@app.post("/classify", response_model=ClassifyResponse)
async def classify(req: ClassifyRequest, request: Request) -> ClassifyResponse:
    request.state.audit["text"] = req.text

    started = time.perf_counter()
    try:
        parsed = await classify_text(app.state.client, req.text)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Ollama timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Ollama error: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    return ClassifyResponse(
        is_offensive=parsed["is_offensive"],
        category=parsed["category"],
        confidence=parsed["confidence"],
        model=MODEL_NAME,
        latency_ms=latency_ms,
    )


@app.post("/classify-image", response_model=ClassifyImageResponse)
async def classify_image(
    request: Request,
    image: UploadFile = File(...),
    strategy: str | None = None,
) -> ClassifyImageResponse:
    """Classify an uploaded image.

    The active strategy is whichever of ``ocr_only``, ``vision_only``,
    ``pipeline``, ``parallel``, or ``stub`` is selected — by default the one
    in the ``IMAGE_STRATEGY`` env var, optionally overridden per-request via
    the ``?strategy=`` query param (useful for the Phase 4 architecture study).
    """
    started = time.perf_counter()
    image_bytes = await image.read()
    if not image_bytes:
        request.state.audit["image"] = {
            "filename": image.filename,
            "content_type": image.content_type,
            "bytes": 0,
        }
        raise HTTPException(status_code=400, detail="Empty image upload")

    request.state.audit["image"] = {
        "filename": image.filename,
        "content_type": image.content_type,
        "bytes": len(image_bytes),
    }

    strategy_name = strategy or app.state.default_strategy
    processor = app.state.image_processors.get(strategy_name)
    if processor is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy: {strategy_name!r}. Valid: {sorted(VALID_STRATEGIES)}",
        )

    try:
        result = await processor.process(
            image_bytes,
            content_type=image.content_type,
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Ollama timed out (vision is slow)") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Ollama error: {exc}") from exc
    except Exception as exc:  # pytesseract.TesseractNotFoundError, etc.
        raise HTTPException(status_code=500, detail=f"Image processing failed: {exc}") from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    return ClassifyImageResponse(
        is_offensive=result.is_offensive,
        category=result.category,
        confidence=result.confidence,
        extracted_text=result.extracted_text,
        backend=result.backend,
        strategy=result.strategy,
        model=MODEL_NAME,
        latency_ms=latency_ms,
    )
