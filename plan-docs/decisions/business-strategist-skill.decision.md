# business-strategist skill — Decisions

**Topic:** Creating a project-scoped Claude Code skill to strengthen the business-plan side of Shomer.AI.
**Decided on:** 2026-05-30
**Decided by:** Alona, with options presented by Claude.

Captures the design choices made when scaffolding the `business-strategist` skill at `.claude/skills/business-strategist/`.

Format per decision: **Question → Choice → Why → Alternatives considered → When to revisit**.

---

## D1 — Combined skill vs four separate skills

**Question:** Should the four business-plan roles (Business Analyst, Market Researcher, Financial Analyst, GTM Strategist) be packaged as one skill or as four separate skills?

**Choice:** **One combined skill, `business-strategist`, with four named personas inside.**

**Why:**
- All four roles work on the same artifact — the business plan — and constantly hand work back and forth. Splitting them would force the model to invoke 2-3 skills in sequence for a typical "strengthen section X" ask, with the risk that one is forgotten.
- Skill triggering is description-based; one rich description that mentions all four role keywords + "business plan" is more reliable than four narrower descriptions that may not fire together.
- The internal "persona" structure keeps the voice consistent: when the skill is invoked, it announces *which hat it's wearing* up front, so the user can correct mid-thread.
- Maintenance is simpler — one SKILL.md to update when the project conventions change.

**Alternatives considered:**
- *Four separate skills* — more granular, but each one would be ~⅓ the size and trigger less reliably. Also, real business-plan work crosses the role lines constantly (e.g. market sizing depends on pricing assumption, which depends on GTM motion).
- *Extend the existing `product-manager` skill* — overlap is real, but `product-manager` is global-scoped and owns *product strategy*, which is upstream of business-plan work. Mixing the two would dilute both.

**Revisit:** if one persona's content grows so much that the SKILL.md becomes unwieldy (> ~500 lines body), split that persona into its own skill and leave a pointer.

---

## D2 — Skill scope: project-local vs user-global

**Question:** Should the skill live in `.claude/skills/` (project-scoped, committed with the repo) or in `~/.claude/skills/` (user-global)?

**Choice:** **Project-scoped — `.claude/skills/business-strategist/`** under the Shomer.AI repo.

**Why:**
- The skill is heavily tailored to Shomer.AI: it knows about `docs/business_plan/business_plan.tex`, the `[למקור]` placeholder convention, the six existing sections, the Israel-specific data sources (CBS, Ministry of Health, NetSafe Israel), and the Hebrew RTL `<div>` wrapper rule from `CLAUDE.md`.
- Future projects (even academic ones) would want a *different* version of this skill — generic global, plus their own templates. Forcing a one-size-fits-all global skill loses the Shomer.AI-specific shortcuts.
- Committing the skill to git means it travels with the project's history and a future session can resume from it without setup.

**Alternatives considered:**
- *User-global skill (`C:\Users\Dima\.claude\skills\`)*: reusable across all projects, but loses the Shomer.AI-specific templates and data-source list. The trade-off — generality for relevance — wasn't worth it for a single-project graduate thesis.
- *Both — global thin skill + project-scoped extension*: more complex than the project needs at this stage. If a second project ever needs this, lift the generic parts (frameworks + sources) into a global skill, leave the templates here.

**Revisit:** if Alona starts a second project that needs the same skill, factor the generic parts (`frameworks.md`, `sources.md` non-Israel parts) into a global skill and reduce this one to project-specific templates + overrides.

---

## D3 — Default output language

**Question:** Hebrew RTL `.md` by default, English by default, or ask every time?

**Choice:** **Hebrew RTL Markdown by default**, with an explicit switch to English on user request.

**Why:**
- The business plan is in Hebrew (`business_plan.tex`). Every section the user asks to strengthen will go back into that document.
- Defaulting to Hebrew skips a clarification round on the most common ask.
- The project convention from `CLAUDE.md` requires every Hebrew `.md` file to be wrapped in `<div dir="rtl">…</div>` — the skill embeds this rule into every template, so the user never has to remember it.

**Alternatives considered:**
- *English by default*: faster to author and Claude is more fluent, but adds a manual translation step before content can be used in the business plan.
- *Ask every time*: friction-heavy on the most common case.

**Revisit:** if Alona ever does a fundraising round outside Israel, English versions of the templates will be needed — at that point, add an `english-templates.md` reference file rather than flipping the default.

---

---

## D4 — Wire `product-strategist` agent to delegate business-plan work

**Question:** How should the existing `product-strategist` agent know to use the new `business-strategist` skill when the user asks for business-plan review/edits, instead of freehanding?

**Choice:** Edit the `product-strategist` agent to (a) declare `business-strategist` in its `skills:` frontmatter, (b) add a new "Section 8 — Business Plan Work" that mandates delegating to the skill, and (c) copy the agent into the project's `.claude/agents/` so the project-scoped version overrides the user-global one when working in Shomer.AI.

**Why:**
- The `product-strategist` agent already owns AI-product strategy work; business-plan review is a natural extension of that mission but the agent's body had nothing about business plans — the user would have gotten a freehanded answer instead of routed-through-skill content.
- Declaring the skill in `skills:` loads its instructions when the agent is invoked, so the model has the skill's frameworks + templates in context, not just a pointer.
- The explicit "delegate, don't freehand" instruction prevents the agent from re-deriving content the skill already does better.
- The project-scoped copy at `.claude/agents/product-strategist.md` overrides the global agent only in Shomer.AI, so this wiring doesn't leak into other projects where `business-strategist` doesn't exist.
- Both versions are now wired (global has a conditional "if skill available"; project version is unconditional). This means the agent works correctly both inside and outside Shomer.AI.

**Alternatives considered:**
- *Only edit the global agent, skip the project copy:* simpler, but loses the explicit "this agent ships with this project" signal and makes the agent's scoping invisible to a reader of the repo. Also means the project-specific tightening (unconditional delegation, references to Shomer.AI-specific files like `docs/references.bib`) can't be made without polluting the global version.
- *Only ship the project copy, leave the global untouched:* would have meant the user-global agent stays unaware of `business-strategist` even when Alona works in another project that scaffolds it. Editing the global file is the right long-term move.
- *Create a separate `business-plan-reviewer` agent:* over-fragments. The agent + skill split is already the right axis of specialization.

**Revisit:** if the global and project copies drift apart in non-trivial ways (e.g. project-specific guidance grows large), formalize the divergence by removing the "kept in sync" claim in the project header and documenting which sections differ.

---

## Linked artifacts

- **Skill:** `.claude/skills/business-strategist/SKILL.md` (+ 3 reference files: `frameworks.md`, `sources.md`, `hebrew-templates.md`).
- **Agent (project-scoped):** `.claude/agents/product-strategist.md` — overrides the global agent in Shomer.AI; delegates business-plan work to the skill unconditionally.
- **Agent (user-global):** `C:\Users\Dima\.claude\agents\product-strategist.md` — same wiring but with conditional "if skill available" language; works across all projects.
- **Consumed by:** `docs/business_plan/business_plan.tex` (the artifact the skill is built to strengthen).
- **Cross-references:** `CLAUDE.md` "Conventions" section (Hebrew RTL `.md` wrapper rule); `plan-docs/decisions/research-framing.decision.md` (RQ anchors that the business plan must stay consistent with).
- **Companion skill** (compile route): `hebrew-latex-pdf` (global) — the natural next step after the strategist drafts content is to compile via this skill.
