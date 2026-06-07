# Commercial Strategist Agent — Decisions

**Phase:** project-wide tooling (cross-meeting)
**Decided on:** 2026-06-06
**Decided by:** Alona, with options presented by Claude

Captures the scoping choices made when creating the project-scoped
`commercial-strategist` agent at `.claude/agents/commercial-strategist.md`.

---

## D1 — Create a dedicated commercial agent (vs. extending product-strategist)

**Question:** Should business plan + profit + resource optimization + marketing +
branding work be handled by extending the existing `product-strategist` agent,
or by creating a new dedicated agent?

**Choice:** **New dedicated agent — `commercial-strategist`.** Project-scoped at
`.claude/agents/commercial-strategist.md`. `product-strategist` keeps its
§8 "Business Plan Work" section but, going forward, business-plan invocations
route to `commercial-strategist`, which then orchestrates the underlying
skills.

**Why:**
- `product-strategist` is already large (~19 KB, 8 sections) and centered on
  AI-product strategy — vision, PRDs, roadmaps, NN comparison, requirements.
  Bolting full CFO + CMO + brand responsibility onto it would dilute the agent
  and make per-skill orchestration rules harder to maintain.
- The two roles split cleanly in any real org: a product head owns the
  *product*, a commercial head owns the *business / pricing / marketing / brand*.
  Mirroring that split here keeps each agent's mission tight.
- Decision capture, output formats, and skill-orchestration rules differ enough
  between the two that one agent would have to constantly branch on intent.

**Alternatives considered:**
- *Extend `product-strategist`:* simpler in the short term, but produces a
  single overgrown agent and forces every commercial turn through a lens
  primarily tuned for product strategy.
- *Three separate narrower agents (financial-modeler / marketing-strategist /
  brand-strategist):* clean separation in theory, but the five responsibilities
  share heavy context (the business plan, the financials, the brand voice) —
  splitting them across three agents would multiply handoffs and risk drift.

**Revisit:** if `commercial-strategist` itself grows past ~20 KB or the per-skill
sections start fighting for space, consider splitting branding out into a
dedicated `brand-strategist` while keeping plan/finance/marketing together.

---

## D2 — Agent name

**Question:** What to call the new agent — `business-and-marketing-strategist`,
`commercial-strategist`, `business-plan-strategist`, `growth-strategist`?

**Choice:** **`commercial-strategist`.**

**Why:**
- Does **not** collide with the existing `business-strategist` *skill* name
  (which the agent invokes). Avoiding agent/skill name collisions keeps both
  the YAML frontmatter and the Skill-tool invocations unambiguous.
- "Commercial" is the standard umbrella term for business + financial +
  marketing + brand functions (commercial director, commercial strategy,
  commercial operations) — a single word that covers all five user-requested
  responsibilities without sounding narrow.
- Shorter than `business-and-marketing-strategist`; less startup-flavored than
  `growth-strategist` (which usually implies growth marketing only); broader
  than `business-plan-strategist` (which would underscope the agent to one
  artifact).

**Alternatives considered:**
- `business-and-marketing-strategist`: descriptive but long; "and" in agent
  names is a code smell that usually signals an under-defined scope.
- `growth-strategist`: too marketing-flavored; would under-represent the
  business-plan and resource-optimization parts of the scope.
- `business-plan-strategist`: too narrow; the agent owns far more than the
  single business-plan artifact.

**Revisit:** only if a future convention emerges (e.g. a global skill catalog
adopts a different umbrella term for this role).

---

## D3 — Skill set assigned to the agent

**Question:** Which skills should the agent declare in its YAML `skills:` field
(beyond the two the user mandated, `business-strategist` and `hebrew-latex-pdf`)?

**Choice:** **11 skills**, mapping to the five responsibilities:

| Skill | Purpose |
|---|---|
| `business-strategist` | Business plan prose (core, user-mandated). |
| `hebrew-latex-pdf` | Compile `business_plan.tex` → PDF (core, user-mandated). |
| `xlsx` | Financial models — P&L, unit economics, cash flow, sensitivity. |
| `pptx` | Investor / board / supervisor decks. |
| `deep-research` | Fact-checked market sizing, competitor data, regulatory citations; fills `[למקור]`. |
| `canvas-design` | Brand identity + marketing visuals (logo, social tiles, print). |
| `frontend-design` | Marketing landing pages, lead-gen forms. |
| `theme-factory` | Brand-consistent theming across decks, docs, landing pages. |
| `software-diagrams` | Business model canvas, value chain, market map, GTM funnel. |
| `product-manager` | Frameworks — RICE / MoSCoW prioritization, ICP, positioning, GTM templates. |
| `doc-coauthoring` | Structured iteration on long multi-section deliverables. |

**Why:** Each skill maps to a concrete deliverable in the agent's scope. Each
responsibility has at least one skill that produces the artifact and at least
one skill that supplies the framework or the sourced data.

**Alternatives considered:**
- *Add `brand-guidelines`:* Anthropic-specific brand assets, irrelevant to
  Shomer.AI's own brand.
- *Add `docx`:* the business plan is LaTeX-first, not Word; Word output is
  rare enough to ask for case-by-case rather than wire in by default.
- *Add `pdf`:* `hebrew-latex-pdf` already produces the PDF; raw PDF
  manipulation (merging appendices, splitting) is rare enough to load
  on demand.
- *Add `internal-comms`:* internal-team status-style updates are not yet
  recurring for Shomer.AI; revisit if and when a regular cadence appears.

**Revisit:** add `docx` if an English Word deliverable is requested for an
investor / board audience; add `pdf` if PDF appendix merging becomes routine;
remove a skill if it is never invoked across 5+ agent runs.

---

## D4 — Boundary with `product-strategist`

**Question:** How do the two agents avoid stepping on each other now that both
touch the business plan?

**Choice:** **`commercial-strategist` owns the artifact; `product-strategist`
owns the consistency check.**

**Why:**
- `commercial-strategist` is now the default route for business-plan work —
  it writes, edits, audits, recompiles, and owns the financial model and
  pricing decisions.
- `product-strategist` keeps its §8 "Business Plan Work" handoff section, but
  it now hands off to `commercial-strategist` (which then invokes
  `business-strategist` the skill). Its commercial role is reduced to
  flagging product↔plan inconsistencies (e.g., the plan claims on-device
  inference but the architecture requires cloud GPU).
- This mirrors the org-chart split: product writes the PRD; commercial writes
  the plan; both review each other's artifacts.

**Alternatives considered:**
- *Leave `product-strategist` as the primary business-plan owner:* would
  defeat the purpose of creating the new agent.
- *Strip the business-plan section out of `product-strategist` entirely:*
  loses the product↔plan consistency check that `product-strategist` is
  uniquely positioned to do.

**Revisit:** if `product-strategist` and `commercial-strategist` end up
producing conflicting business-plan edits in practice, formalize a
"`commercial-strategist` writes, `product-strategist` reviews" handshake
explicitly in both agent files.
