# Shomer.AI

**A Hebrew-first, context-aware digital guardian that helps parents detect online bullying, threats, sexual content, and emotional distress in their child's chats — while cutting the false alarms that make existing tools unusable.**

*Graduate final project · AI Experts course · Mentor: Dr. Yoram Segal*

---

## The idea

Shomer.AI (*shomer* = "guardian" in Hebrew) reads a child's chat **in the context of the whole conversation**, not message-by-message, and classifies risk in **Hebrew**. Sensitive classification runs **locally, on-device** (privacy-first); only borderline cases are escalated to a context-verifying agent. Every alert to the parent comes with an explanation and a quote — not a black box.

## The problem

Existing parental-safety tools are English-first, keyword-based, and judge each message **in isolation, without context**. The result is a flood of false alarms (*Alert Fatigue*) that makes parents abandon them within days — while real bullying that only emerges across a conversation slips through. None of them understand Israeli Hebrew slang or context.

## Research question

> **To what extent does adding conversational context (the prior turns in a thread) to Hebrew bullying classification reduce the false-positive rate — compared to classifying a message in isolation — without hurting recall?**

- **Measured:** false-positive rate (primary), recall (must not drop), macro-F1.
- **Baseline:** the same model judging messages context-blind.
- **Success:** a statistically significant FPR reduction with non-inferior recall, on a real Hebrew gold set.

## The gap we close

Research on context vs. false positives exists **only in English** (e.g., Pavlopoulos et al. 2020; Sap et al. 2019). For Hebrew there is **no conversational-context bullying research and no conversational bullying dataset** — the main Hebrew resource (SinaLab Offensive-Hebrew) is *isolated tweets*, not conversations. Shomer.AI transfers this proven insight to Hebrew, where it has never been tested. **That transfer is the contribution.**

## Approach

- **Frontline classifier** — a Hebrew LLM fine-tuned with QLoRA, served locally via Ollama (≈ $0/token, full privacy).
- **Context Agent** — an LLM agent that re-checks borderline cases against the conversation history before alerting; this is the false-positive-reduction mechanism.
- **Data** — no Hebrew conversational corpus exists, so we **synthesize** labelled Hebrew conversations (with deliberate "context-flip" cases) and build a small **real gold set**. Principle: *train on synthetic, evaluate on real.*
- **Local-first & multimodal** — text is the primary modality; images (OCR / vision) are a secondary track.

## Architecture

```
[Android (Kotlin/Compose)] --HTTP--> [FastAPI] --HTTP--> [Ollama] -> local Hebrew model
                                          └── Context Agent (verifies borderline alerts)
```

## Status

- ✅ **POC** — app ↔ local server ↔ model proven end-to-end.
- ✅ **Meeting-3 deliverables** ready (see `docs/`).
- ⏳ Base-model and single-server-vs-agents decisions are intentionally **frozen until Meeting 4**.

## Repository

| Path | Contents |
|---|---|
| [`docs/`](docs/) | Academic deliverables: [research question](docs/research_question/research_question.md) · [flagship papers](docs/literature/literature_flagship.md) · [preparatory report](docs/preparatory_report/preparatory_report.md) · [business plan](docs/business_plan/business_plan.md) · prompt book · project proposal |
| [`poc/`](poc/) | POC plan and notes |
