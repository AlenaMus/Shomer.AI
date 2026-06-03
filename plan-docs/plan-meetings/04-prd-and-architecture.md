# Meeting 4 — PRD & Architecture (frozen)

**Phase:** B · Planning · **Status:** ⬜ not started · **Source:** `Shomer_AI_10_Meeting_Plan` §4
> ⭐ **This is where the open architecture question is decided and recorded.** After this meeting,
> coding is execution, not design.

## 🎯 Goal
Finish a full product PRD and freeze the architecture — including the **DictaBERT-vs-Qwen /
agents-vs-single-server** decision (see [Plan.md](../Plan.md) → "Open architecture question").

## 📋 Before
- Review open PRD examples (Linear, GitLab, Notion templates).
- Re-read Dr. Segal's PRD + agent slides.
- Install a diagram tool (draw.io / Excalidraw).

## ⚙️ Steps
| # | Action | Output |
|---|--------|--------|
| 4.1 | Full product PRD: vision, personas, features (MoSCoW), non-functional reqs, KPIs, out-of-scope | `docs/PRD.md` |
| 4.2 | System architecture diagram: User → API → (model/agents) → data | `results/architecture.png` |
| 4.3 | **Decide architecture** and write it up with reasoning | `plan-docs/decisions/architecture.decision.md` |
| 4.4 | Per-component PRD (model, image path, and any agents kept) | `docs/components/` |
| 4.5 | Finalize the preparatory report for mentor approval | `docs/preparatory_report.md` final |

## 📦 Deliverables
`PRD.md` (5–10 pages), architecture diagram, an **architecture decision record**, the approved preparatory report.

## ✅ Done when
- Every component has a defined role, input, output, success metric, fallback.
- The architecture decision is recorded with the chosen base model and component shape.
- Mentor approved the preparatory report. Tag **v0.4** "Design Frozen".

## ⚠️ Risks
- Diagram with no real distinctions → test: "what happens if component X fails?" If no answer, the contract is unclear.
- PRD becomes a feature list → each feature needs why / user / success / what's *not* enough.

## Note (divergence to resolve here)
The proposal's design (DictaBERT + Triage/Context/Alert + RAG) and the POC prototype (Qwen via
Ollama, single server, image-strategy study) differ. Pick one — or a hybrid — and justify it.
This unblocks steps 5–8.
