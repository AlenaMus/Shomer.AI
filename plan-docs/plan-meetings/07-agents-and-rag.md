# Meeting 7 — Context/Alert Logic + Image Path + End-to-End Flow

**Phase:** C · Development · **Status:** ⬜ not started · **Source:** `Shomer_AI_10_Meeting_Plan` §7
> Scope here depends on the Step-4 architecture decision. If "agents" were dropped in favour of the
> single-server design, this meeting becomes "context filtering + alert formatting + image
> backends", reusing the POC server. Image-strategy work = [`../POC_Plan.md`](../POC_Plan.md) Phases 2 & 4.

## 🎯 Goal
Complete the pipeline beyond raw classification: a **context** step that cuts false positives, an
**alert** step that phrases a parent-facing message, the **image** path (OCR + vision), wired into
one end-to-end flow.

## 📋 Before
- Install orchestration + vector DB only if the chosen design needs them (LangGraph, ChromaDB).
- Collect 30–50 support-protocol sources (e.g. national child-safety hotline materials).

## ⚙️ Steps
| # | Action | Output |
|---|--------|--------|
| 7.1 | Context step: LLM (Claude Haiku / GPT-4o-mini) validates yellow/red flags | `src/context/` |
| 7.2 | Image backends: OCR (Tesseract `heb`) + vision (Ollama VL) + strategy router | `server/app/image_backends/` |
| 7.3 | Knowledge base + retrieval for alert resources (if RAG kept) | `src/rag/` |
| 7.4 | Alert step: 3 severity levels, parent-friendly text + resources | `src/alert/` |
| 7.5 | End-to-end flow: classify → context (if needed) → alert (if needed) | `src/pipeline/` |
| 7.6 | Integration tests: ~10 end-to-end scenarios | `tests/test_pipeline.py` |
| 7.7 | Demo surface (existing Android app, plus optional Streamlit for the defense) | demo |

## 📦 Deliverables
Working end-to-end pipeline, a flow diagram, FastAPI with Swagger, a runnable demo.

## ✅ Done when
- 10 example messages run end-to-end in < ~2 s each.
- Cost per call measured; context step removes ≥ 2 known false positives out of 10.
- Tag **v0.7** "Full Pipeline".

## ⚠️ Risks
- Latency too high (LLM calls) → caching, async, shorter prompts, smaller model.
- Orchestration framework too heavy → fall back to plain Python; the logic matters, not the framework.
- Vision/OCR weak on Hebrew → quantify in Meeting 8 / `POC_Plan` Phase 4; swap models via config.
