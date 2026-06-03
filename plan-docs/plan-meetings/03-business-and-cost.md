# Meeting 3 — Business Plan & Cost Analysis

**Phase:** B · Planning · **Status:** ⬜ not started · **Source:** `Shomer_AI_10_Meeting_Plan` §3

## 🎯 Goal
Turn Shomer.AI from a tech experiment into a defensible **product**: business plan, competition
map, token-cost model based on real prices, and a pricing policy.

## 📋 Before
- Pull official price pages: Anthropic, OpenAI, Google.
- List 5 active competitors with links to their pricing.
- Market-size sources: Statista, Grand View Research, Israel CBS.

## ⚙️ Steps
| # | Action | Output |
|---|--------|--------|
| 3.1 | Executive summary + problem + a concrete user persona | `docs/business_plan.md` §1–2 |
| 3.2 | TAM / SAM / SOM — each number with a formula and a source | `results/tam_sam_som.png` |
| 3.3 | Competitor analysis (Bark, Qustodio, Canopy, Keepers, Bosco) on Price vs Value | `results/competitive_map.png` |
| 3.4 | Token-cost model: input/output tokens × price × calls/user × agents | `results/token_economics.xlsx` |
| 3.5 | Model comparison (local model vs Claude Haiku vs GPT-4o-mini vs Gemini Flash): cost, quality, latency | `results/model_comparison.md` |
| 3.6 | USP in one sentence + revenue model (freemium tier) | section in plan |

## 📦 Deliverables
Full `business_plan.md`, TAM/SAM/SOM chart, competitive map, token-economics sheet.

## ✅ Done when
- You can answer in 30 s: "Who is the customer, what do they pay, what do they cost me?"
- Every chart number has a source footnote.
- Tag **v0.3** "Business Foundation".

## ⚠️ Risks
- Numbers look arbitrary → start from public Statista + CBS; justify, don't invent.
- Token cost scares the defense → stress the hybrid design (cheap classifier first, LLM only on edge cases).
