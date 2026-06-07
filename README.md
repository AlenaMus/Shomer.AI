# Shomer.AI

**A Hebrew-first, context-aware digital guardian that helps parents detect online bullying, threats, sexual content, and emotional distress in their child's chats — while cutting the false alarms that make existing tools unusable.**

*Graduate final project · AI Experts course · Mentor: Dr. Yoram Segal*

---

## The idea & goal

Shomer.AI (*shomer* = "guardian" in Hebrew) reads a child's chat **in the context of the whole conversation**, not message-by-message, and classifies risk in **Hebrew**. Frontline classification runs **locally** (privacy-first); only borderline cases are escalated to a context-verifying agent. Every parent alert comes with an explanation and a quote — never a black box.

**The problem:** existing parental-safety tools are English-first, keyword-based, and judge each message **in isolation**. The result is a flood of false alarms (*alert fatigue*) that makes parents abandon them within days — while real bullying that only emerges across a conversation slips through. None of them understand Israeli Hebrew slang or context.

**Goal:** prove that adding conversational context to a Hebrew bullying classifier meaningfully reduces false positives **without** sacrificing the ability to catch real harm.

## Research question

> **To what extent does adding conversational context (the prior turns in a thread) to Hebrew bullying classification reduce the false-positive rate — compared to classifying a message in isolation — without hurting recall?**

- **Measured:** false-positive rate (primary), recall (must not drop), macro-F1.
- **Baseline:** the same model judging messages context-blind.
- **Success:** a statistically significant FPR reduction with non-inferior recall, on a real Hebrew gold set.

**The gap:** context-vs-false-positives research exists **only in English** (Pavlopoulos et al. 2020; Sap et al. 2019). For Hebrew there is **no conversational-context bullying research and no conversational bullying dataset**. Transferring this proven insight to Hebrew is the contribution.

## Data for training the model

The task needs **labelled Hebrew conversations** — which **do not exist**. The strategy combines four sources (*train on synthetic, evaluate on real*):

| Source | Role | Notes |
|---|---|---|
| **SinaLab Offensive-Hebrew** (Hamad et al. 2023) | The Hebrew anchor | 15,881 tweets, 5 labels (`abusive / hate / violence / pornographic / non_offensive`). Isolated messages — not conversational. |
| **Synthetic Hebrew conversations** | **Primary training data** | Generated labelled threads with deliberate *context-flip* cases (benign-in-context messages that look offensive alone). |
| **English conversational corpora** | Inspiration / cross-lingual | ConvAbuse, Wikipedia Context-Toxicity, ConvAbuse — for structure & taxonomy. Used with human post-edit only, never as test set. |
| **Real Hebrew gold set** | **Evaluation only** | Small, human-labelled — the honest benchmark the research question is scored on. |

Full data map: [`data/bullying_data_he.md`](data/bullying_data_he.md).

## High-level architecture

```
[Android app]                [FastAPI server]                       [Local model]
Kotlin + Compose  --HTTP-->   Gatekeeper (trace-id · rate-limit · size · /metrics)
                              → TextClassifier  ───────────────────► fine-tuned DictaBERT
                              → TriageEngine.decide()                 (Ollama stand-in today)
                                 ├─ SILENT         → log & return
                                 ├─ ALERT_DIRECT   → NotificationChannel → parent
                                 └─ ESCALATE       → Context Agent (verifies borderline
                                                      cases against conversation history)
                              → Audit log (SQLite)
```

- **Frontline classifier** — fast, local, privacy-preserving; handles every message.
- **Triage engine** — routes by confidence/label: silent · direct alert · escalate.
- **Context Agent** — the false-positive-reduction mechanism: re-checks borderline cases against the thread before alerting.
- **Ports-and-adapters design** — every module is Protocol-typed; swapping a model, OCR engine, or notifier is a one-line change in `main.py`.

## Chosen technologies

| Layer | Technology |
|---|---|
| **Mobile client** | Kotlin · Jetpack Compose · Material 3 |
| **Server** | Python · FastAPI · Pydantic · slowapi · Prometheus · structlog |
| **Frontline model** | DictaBERT (Hebrew BERT) fine-tuned — MLP head + Focal Loss; Ollama stand-in until checkpoint lands |
| **Context Agent** | LLM router → GPT-4o-mini / Claude Haiku 4.5 (mock fallback when no key) |
| **Image track** (secondary) | Tesseract OCR (`heb+eng`) · vision LLM via Ollama |
| **Persistence** | SQLite (WAL) audit store — classifications, agent traces, alerts, conversations |
| **Training** | PyTorch · HuggingFace Transformers · PEFT · bitsandbytes · CUDA 12.8 on RTX 5080 (WSL2) |

## Privacy, ethics & responsible design

This system reads children's private conversations, so these are **non-negotiable design constraints**, not features:

- **Local-first by default** — the frontline classifier runs on-device/locally; raw chats are not sent to the cloud. Only borderline cases escalate, and PII is scrubbed before any LLM call.
- **Explainable alerts** — every parent notification carries the offending quote + the reason. No silent black-box flagging.
- **Minimal data & retention** — audit logs hold only what's needed for evaluation; a retention sweeper purges old records.
- **Child dignity** — the goal is protection, not surveillance theatre. Cutting false positives is itself an ethical aim: fewer false accusations of a child.
- **Graceful degradation** — if the agent, OCR, or LLM is unavailable, the system fails safe rather than dropping protection silently.

## Academic contribution & evaluation

- **Contribution** — first transfer of the context-reduces-false-positives finding to **Hebrew**, plus a synthetic Hebrew conversational dataset where none existed.
- **Method** — A/B the *same* model **with vs. without** conversational context on a real Hebrew gold set; report ΔFPR, recall, macro-F1 with statistical significance.
- **Honesty principle** — train on synthetic, **evaluate on real**; the gold set is the only thing the research question is scored on.

## Status

- ✅ **POC** — app ↔ local server ↔ model proven end-to-end.
- ✅ **Server** — full pipeline wired & tested (classify → triage → context agent → alert → audit), 384 tests passing.
- ✅ **DictaBERT architecture & training environment** locked and verified.
- ⏳ **Next** — prepare data, fine-tune DictaBERT (F1 ≥ 0.78 gate), then run the context-vs-baseline evaluation that answers the research question.

## Repository

| Path | Contents |
|---|---|
| [`server/`](server/) | FastAPI service — classifier · ocr · context_agent · triage · alerts · gatekeeper · audit_log |
| [`training/`](training/) | DictaBERT fine-tuning pipeline (data prep + training) |
| [`android_client/`](android_client/) | Kotlin/Compose mobile client |
| [`docs/`](docs/) | Design package (10 module LLDs), concept docs, evaluation reports |
| [`plan-docs/`](plan-docs/) | Academic deliverables — proposal, plan, research questions, decisions |
| [`data/`](data/) | Dataset map and OCR validation |
