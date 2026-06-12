# Decision — `presentation-designer` agent

**Date:** 2026-06-11
**Phase/Step:** Tooling / project agents

---

## D1 — Create a dedicated Hebrew presentation-designer agent

**Question:** Should deck creation (business + product presentations) be owned by a dedicated
agent, or stay folded into `commercial-strategist` (which already declares `pptx`)?

**Choice:** Create a new project-scoped agent `presentation-designer`
(`.claude/agents/presentation-designer.md`), Hebrew-RTL-first, specialized in the *craft* of
slide decks across both genres (business + product), declaring all 12 presentation-relevant
skills: `pptx`, `software-diagrams`, `canvas-design`, `frontend-design`, `theme-factory`,
`brand-guidelines`, `business-strategist`, `product-manager`, `xlsx`, `deep-research`,
`hebrew-latex-pdf`, `doc-coauthoring`.

**Why:**
- A deck is a distinct craft (narrative arc, one-message-per-slide, visual system, RTL
  typesetting) that cuts across **both** business and product material — neither
  `commercial-strategist` (business-plan document) nor `product-strategist` (PRDs/roadmaps)
  owns it cleanly. A dedicated agent gives that craft a single home.
- `pptx` is the only primary deck producer; pairing it with `software-diagrams` (architecture
  slides), `xlsx` (chart data), `deep-research` (sourced facts), `canvas-design` (cover art),
  and `theme-factory`/`brand-guidelines` (consistent theme) is exactly the skill set a
  professional deck needs — no single skill does it end-to-end.
- Clear boundary: this agent **presents** existing content; it routes *authoring* to
  `commercial-strategist`, `product-strategist`, or `ai-researcher-developer`. Avoids
  duplicating their roles while removing deck work from their plates.

**Alternatives considered:**
- *Keep deck work in `commercial-strategist`* — rejected: it would only cover business decks,
  not product/architecture/demo decks, and would overload that agent's business-plan focus.
- *No agent; invoke `pptx` from the main thread ad hoc* — rejected: loses the project-specific
  encoding (source-artifact map, RTL mandate, output conventions, decision logging) and the
  multi-skill orchestration discipline.
- *A skill instead of an agent* — rejected: the work is multi-step orchestration across many
  skills, which is the agent pattern, not a single skill.

**Revisit:** If product-deck volume turns out negligible, consider merging back into
`commercial-strategist`. If decks frequently need new authored content (not just
re-presentation), revisit the present-vs-author boundary.
