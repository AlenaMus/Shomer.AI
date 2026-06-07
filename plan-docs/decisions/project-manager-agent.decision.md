# Decision — `project-manager` Project-Scoped Agent (combined English + Hebrew)

**Date:** 2026-06-07
**Trigger:** User asked for "agent in project that manages the whole work" — explicitly referencing both project-manager AND hebrew-project-manager concepts. Previous gap analysis at `.claude/gaps.md` had recommended "don't create `hebrew-ai-project-manager-agent`" — that decision is now overturned in favor of a combined agent.

---

## D1 — Build one combined `project-manager` agent (not two)

**Question:** The user mentioned both "project manager" and "hebrew project manager" and said they need an agent that manages the whole work. Build one combined agent, or two separate agents?

**Choice:** One combined `project-manager` agent that picks the right skill per task — `hebrew-ai-project-manager` for Hebrew Dr. Segal-facing prep / implementation summaries, `project-organizer` for English sprint + backlog work, `project-planner` for risk + estimation, plus `software-diagrams` + `pdf` + `doc-coauthoring` for visualization and document synthesis.

**Why:**

- The user explicitly said "the whole work" — fragmenting whole-project ownership across two agents defeats the request.
- The Hebrew/English split isn't about ownership; it's about *output language*. The Hebrew prep doc for Dr. Segal and the English sprint plan for the dev are two outputs of the SAME coordination role.
- One coordinator means one routing matrix (which specialist owns deliverable X), one risk register, one status dashboard. Two coordinators means duplicate state to keep in sync.
- The user-global `project-organizer` and `project-planner` skills are already present — having the project-manager agent invoke them keeps the orchestration logic project-scoped while the mechanics stay reusable.
- The `hebrew-ai-project-manager` skill is already project-scoped — same pattern.

**Alternatives considered:**

- *Two agents (English `project-manager` + Hebrew `hebrew-ai-project-manager`)* — rejected because it fragments ownership and creates a coordination problem at the meta-level (who decides which agent runs the meeting prep?). User explicitly asked for "the whole work."
- *Just wrap `hebrew-ai-project-manager` skill in an agent* — rejected because it leaves English sprint / backlog / risk work without a clear owner. The skill is Hebrew-Dr.-Segal-prep-centric; it doesn't cover the broader coordination role.
- *Defer per gap analysis* — rejected because the user's request is the trigger. The gap analysis's "don't create" call was based on the project having only 2 specialist agents at the time; now it has 6.

**Revisit:** If two distinct ownership patterns emerge (e.g. a non-Alona team member needs English-only project management while Alona continues Hebrew-only), split into two agents. Trigger: 2nd primary user joining the project.

---

## D2 — Supersedes the gap-analysis "don't create hebrew-ai-project-manager-agent" decision

**Question:** `gaps.md` previously read: "`hebrew-ai-project-manager-agent` — Decision: don't create. The skill orchestrates the workflow; an agent wrapper would add overhead without value." Does the new combined agent overturn that?

**Choice:** Yes — explicitly mark the gap-analysis decision as SUPERSEDED. The new `project-manager` agent's scope is broader than just wrapping the Hebrew skill; it's the whole-project coordinator + handoff orchestrator across 5 specialist agents.

**Why:**

- The cost/benefit calculation has changed since the gap analysis was written:
  - **At time of gap analysis** (2026-06-06, after `commercial-strategist` landed): 2 project-scoped agents (`commercial-strategist`, `product-strategist`); coordination cost was low; one skill invocation per meeting was tolerable.
  - **Now** (2026-06-07, after `android-developer` lands): 6 project-scoped agents (`commercial-strategist`, `product-strategist`, `ai-researcher-developer`, `backend-developer`, `android-developer`, `project-manager`); coordination cost is meaningful; tracking handoffs across 5 specialists from the main thread is error-prone.
- A coordinator agent encodes:
  - The routing matrix (Android task → `android-developer`, business plan task → `commercial-strategist`, etc.).
  - The "always invoke a skill, never freehand" discipline at the project level.
  - The triple audit-trail consistency (`prompts/` + `plan-docs/decisions/` + `CLAUDE.md`).
  - Process discipline (always ask the meeting date; always update the status table on row state changes).
- These are exactly the items the gap analysis dismissed as "overhead without value" when the project was simpler. They are now genuine load-bearing knowledge.

**Alternatives considered:**

- *Keep the gap-analysis decision as-is, build the agent silently* — rejected because the decision-capture convention requires explicitly superseding prior decisions, not silently overriding them. Future-me reopening `gaps.md` would be confused.
- *Treat this as a brand-new decision unrelated to the gap analysis* — rejected for similar reasons; the connection to the prior call is the relevant context.

**Revisit:** Same as D1 — if ownership patterns fragment, split.

---

## D3 — Skill set: 7 skills

**Question:** Which skills does the combined agent declare?

**Choice:** Seven — `hebrew-ai-project-manager`, `project-organizer`, `project-planner`, `project-manager`, `software-diagrams`, `pdf`, `doc-coauthoring`.

**Why:**

- **`hebrew-ai-project-manager`** (project-scoped skill) — Hebrew Dr. Segal-facing prep + implementation summaries. Mandatory; the canonical Hebrew workflow.
- **`project-organizer`** (user-global skill) — English sprint planning + backlog grooming. Mechanics over the `tasks.json` files.
- **`project-planner`** (user-global skill) — Estimation + risk + dependency analysis.
- **`project-manager`** (user-global skill) — Generic PM templates / agile patterns for non-Shomer-specific work.
- **`software-diagrams`** — Gantt + dependency graph + burndown + status visualization in Mermaid. Renders in PR markdown + Hebrew prep docs via headless Edge.
- **`pdf`** — Compile every Hebrew Markdown deliverable to PDF via `scripts/md_to_pdf.py`.
- **`doc-coauthoring`** — Multi-section meeting agenda / retrospective doc co-authoring (when the deliverable has 4+ sections).

**Alternatives considered:**

- *Add `deep-research`* — rejected because research is owned by the specialists (`commercial-strategist` for market data, `ai-researcher-developer` for paper citations). The project-manager routes the research ask to the right specialist.
- *Add `business-strategist`* — rejected for the same reason; business plan is `commercial-strategist`'s domain.
- *Drop `project-manager` (the user-global skill, distinct from the agent)* — rejected because it has generic templates the Hebrew/sprint skills don't cover (e.g. retrospective templates, stakeholder-mapping frameworks).
- *Drop `doc-coauthoring`* — rejected because synthesis docs (e.g. the 3-paragraph meeting opening) genuinely benefit from the multi-section iterative refinement the skill provides.

**Revisit:** If `project-manager` skill is never invoked in practice, drop it. Trigger: 6+ meetings of agent use without a single invocation.

---

## D4 — Boundary against the 5 specialist agents

**Question:** Where does `project-manager`'s scope stop and the specialists' begin?

**Choice:** `project-manager` NEVER produces deliverable content. It picks the skill for the meta-task (prep doc, sprint plan, status, routing), invokes the skill, and routes any *content* asks to the matching specialist. Hard boundary:

| Asked for... | Routed to |
|---|---|
| Hebrew prep doc structure (tasks, deadlines, deliverables, risks) | `project-manager` agent + `hebrew-ai-project-manager` skill |
| Hebrew prep doc content (e.g. "what's the business plan section X say") | `commercial-strategist` |
| English sprint plan (which tasks, what order, dependencies) | `project-manager` agent + `project-organizer` skill |
| Sprint plan execution (the actual ML / backend / Android work) | The matching specialist |
| Risk register structure + scoring | `project-manager` agent + `project-planner` skill |
| Mitigation plan for a specific risk (e.g. LLM key blockers) | The owning specialist (here: `backend-developer`) |
| Status summary across the whole project | `project-manager` agent + `hebrew-ai-project-manager` Module 1 |
| Status summary of a specific module | The owning specialist |

**Why:**

- Keeps the "always invoke a skill, never freehand" discipline cleanly enforceable. The project-manager agent's TEXT output is short — routing decisions + skill invocations + status updates. The skills produce the long-form content.
- Prevents the agent from becoming a know-it-all that competes with the specialists. Specialists have deeper project-specific encoding for their domains; the project-manager has broader-but-shallower encoding.
- Mirrors the same Protocol-vs-adapter pattern from the server architecture — `project-manager` is the orchestrator (Protocol-level); specialists are the adapters (concrete-content-level).

**Alternatives considered:**

- *Let project-manager freehand short content (1-paragraph summaries, quick risk notes)* — rejected because freehand drift starts small and grows. Hard boundary is enforceable; soft boundary isn't.
- *Let project-manager hand off only across major handoffs, not every sub-task* — rejected because routing decisions ARE the agent's primary value-add. Coarser routing means more freehand.

**Revisit:** If the strict no-freehand rule produces awkward routing chains (e.g. "ask the user for the meeting date" → spawn `hebrew-ai-project-manager` skill → it asks the date → returns), relax it for the specific ask-for-meeting-date primitive. Trigger: 2 user complaints about excessive routing for trivial asks.

---

## Summary table — files changed in this decision

| File | Change |
|---|---|
| `.claude/agents/project-manager.md` | **Created** — fresh project-scoped agent (combined English + Hebrew + handoff orchestration). |
| `.claude/agents/README.md` | Project-scoped 4 → 6; new section for `project-manager`; handoff matrix updated; user-global `project-organizer` + `project-planner` re-described as indirect-via-PM. |
| `.claude/gaps.md` | `hebrew-ai-project-manager-agent` flipped from "Don't create" → ✅ SUPERSEDED by `project-manager`; agent count 4 → 6. |
| `plan-docs/decisions/project-manager-agent.decision.md` | **This file** — captures D1–D4. |
| `prompts/2026-06-07_meeting-6.md` | Turn appended (this session). |

---

## Reading list for revisit

When this decision is reopened:

- The 6 project-scoped agent set — still 6? If specialists have been merged or split, the coordinator's routing matrix needs updating.
- The skill mix — still all 7 invoked? Drop any that go 6+ meetings unused.
- The hard "no freehand" boundary — still defensible? If the boundary has been quietly relaxed in practice, either re-enforce or formally relax it.
- The supersession of `hebrew-ai-project-manager-agent` decision — still valid? If a non-Alona team member needs English-only PM, split.
