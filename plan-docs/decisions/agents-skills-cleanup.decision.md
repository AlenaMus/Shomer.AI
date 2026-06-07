# Decision — `.claude/` Agents & Skills Cleanup

**Date:** 2026-06-06
**Trigger:** Session prompt — "go over the gap md and create missing agents and remove non used agents in this project."
**Reference:** [`../../.claude/gaps.md`](../../.claude/gaps.md) — the gap analysis driving this pass.

---

## D1 — Remove 4 duplicate non-customized agents from `.claude/agents/`

**Question:** Six of the eight files in `.claude/agents/` were byte-identical copies of the user-global versions (verified via `diff -q`). The gap analysis recommended leaving them as user-global inherited rather than duplicating. Do we remove the duplicates so the override rule works cleanly?

**Choice:** Delete the 4 that have no near-term plan to be customized: `ai-educator-architect.md`, `architecture-reviewer.md`, `project-organizer.md`, `project-planner.md`. They now inherit from `C:\Users\Dima\.claude\agents\` per the override rule.

**Why:**

- They were byte-identical to user-global — zero project-specific encoding to defend their presence.
- Keeping them duplicated is actively harmful: editing the user-global copy would leave the project copy silently stale, and reviewers couldn't tell at a glance whether the project copy was the "real" one.
- `.claude/agents/README.md` already documented these as user-global inherited — the duplicates contradicted the README.
- The gap analysis (`gaps.md`) recommended "Leave as user-global" for all four with priority None or Low.

**Alternatives considered:**

- *Leave them in place* — rejected because the duplication contradicts the README and the override rule. Future edits to user-global would silently diverge.
- *Customize all four for Shomer.AI* — rejected because the gap analysis explicitly notes no recurring use pattern for any of them. Customization would be premature.
- *Delete only `architecture-reviewer.md` (the rarest-used)* — rejected for inconsistency; the rationale applies uniformly to all four.

**Revisit:** If recurring use of any of the four accumulates enough Shomer.AI-specific guidance to justify a project twin (e.g. `architecture-reviewer` becomes the standing reviewer for every `docs/design/review.md` update), re-create the project copy then. Trigger: ≥3 substantive uses in a single sprint.

---

## D2 — Build project twins of `ai-researcher-developer` and `backend-developer`

**Question:** The gap analysis flagged these as "Create project twin when convenient" — Low–Medium priority, deferred. Should we pull the work forward now while we're already in `.claude/` cleanup, or defer further?

**Choice:** Build both project twins now.

**Why:**

- The user explicitly asked to act on the gap analysis in this session — "create missing agents." Pulling the deferred items forward is the closest match to that request given that no agents are *strictly* missing.
- Both agents already have substantial Shomer.AI-specific guidance that lives in `CLAUDE.md` and the design docs. Encoding it in the agent definition pushes it into the agent's own context window every invocation, which is more reliable than hoping the agent reads `CLAUDE.md` first.
- `ai-researcher-developer` carries hard-won knowledge that has cost real time when missed (the 2026-06-04 WSL2 + cu128 venv trap; the 184.3 M param discovery; the locked architecture envelope). Encoding it as the agent's lock prevents future agents from re-deriving.
- `backend-developer` carries the G-03 confidence-direction rule (a silent-footgun bug already shipped once in the design package), the Windows UTF-8 stdio fix (cost real audit rows during 2026-06-06 live testing), and the pytest-from-repo-root invariant (falsely fails 9 tests). All three are documented in CLAUDE.md but easy to miss; the agent now refuses to skip them.
- Cost is one more file per agent to maintain. Benefit is defensible "agent knows the project" behavior on every invocation.

**Alternatives considered:**

- *Defer per the gap analysis* — rejected because the user explicitly asked to act on the gap analysis in the same turn; deferring would not match the request.
- *Build only `backend-developer`* (the server-side work is more active right now) — rejected because the next session's `ai-researcher-developer` work (`prepare_data_dictabert.py`) is unblocked and ready to go, and the architecture-lock-encoded twin is what prevents that next session from accidentally re-deriving the architecture.
- *Build minimal stub twins that just point to CLAUDE.md* — rejected because the value of a twin IS the encoded guidance; a stub adds nothing.

**Revisit:** The twins should be re-audited after the first time each is invoked end-to-end (so after `ai-researcher-developer` finishes training, and after `backend-developer` finishes the FCM channel or the next `lifespan()` rewire). At that point either trim guidance that proved redundant, or expand guidance that the agent missed.

---

## D3 — Promote `hebrew-latex-pdf` and `claude-api` skills to project scope

**Question:** The gap analysis listed these as the two "Now (recommended)" skill promotions. Should we land both in this pass?

**Choice:** Promote both:

- `hebrew-latex-pdf` — copied verbatim from user-global (no edits needed; skill is already generic).
- `claude-api` — copied from user-global, plus a Shomer.AI addendum appended at the bottom of `SKILL.md` covering: project-scoped Haiku 4.5 default (overriding the generic Opus 4.6 default), prompt caching as mandatory on the static portion of every Context Agent call, non-streaming (responses are short structured JSON), the `LlmRouter` primary→fallback policy that must not be silently caught, and the four file paths to read before editing the Anthropic adapter (`protocol.py`, `llm_router.py`, `anthropic_client.py`, `tokens/sqlite_token_manager.py`).

**Why:**

- `hebrew-latex-pdf` already shipped a committed artifact (`docs/business_plan/business_plan.pdf`) and will be used every time the plan is recompiled. Project scope guarantees reproducibility on a fresh machine.
- `claude-api` covers the only Anthropic SDK call site in the codebase. Locking the Haiku 4.5 + prompt-caching choice into the repo prevents future "should we just use Opus 4.6" drift on every edit.
- Both were the top of the gap analysis's "Now (recommended)" list. Cost is one folder copy each; benefit is reproducibility + locked defaults.

**Alternatives considered:**

- *Defer `claude-api` until the next time the Anthropic adapter is edited* — rejected because the project twin of `backend-developer` declares `claude-api` as a skill it invokes; having the project copy available means the adapter edits already route through the project guidance instead of the user-global generic.
- *Edit `hebrew-latex-pdf` to encode the project-specific font preamble inline* — rejected because the user-global version already covers the David CLM fallback chain generically; no edit needed.

**Revisit:** When the next Claude model version (Opus 4.7 → 4.8, Haiku 4.5 → 4.6) ships, re-evaluate whether the project-scoped Haiku default still holds for the Context Agent. The addendum is the right place to record that decision.

---

## D4 — Documentation updates

**Choice:** Update `.claude/agents/README.md` (project-scoped agents 2 → 4; user-global inherited 6 → 4; handoff matrix), `.claude/skills/README.md` (project-scoped 20 → 22; user-global section trimmed), and `.claude/gaps.md` (mark Now-recommended items done; mark deferred twins done; add 2026-06-06 status note at the top).

**Why:** Without these updates the docs would contradict the filesystem within the same commit. The override rule depends on README.md being trustworthy.

**Revisit:** Next time `gaps.md` is re-run (per its own "Revisit" section — after first financial model, first deck, brand work, Android resumption, or DictaBERT fine-tune success), refresh the count tables again.

---

## Summary table — files changed in this decision

| File | Change |
|---|---|
| `.claude/agents/ai-educator-architect.md` | Deleted (duplicate of user-global). |
| `.claude/agents/architecture-reviewer.md` | Deleted (duplicate of user-global). |
| `.claude/agents/project-organizer.md` | Deleted (duplicate of user-global). |
| `.claude/agents/project-planner.md` | Deleted (duplicate of user-global). |
| `.claude/agents/ai-researcher-developer.md` | **Rewritten as project twin** — DictaBERT architecture lock + WSL2 env + F1 gate + fallback chain encoded. |
| `.claude/agents/backend-developer.md` | **Rewritten as project twin** — Protocol+adapter + G-03 rule + composition-root + UTF-8 stdio + pytest invariant encoded. |
| `.claude/agents/README.md` | Project-scoped agents 2 → 4; user-global inherited 6 → 4; handoff matrix updated. |
| `.claude/skills/hebrew-latex-pdf/` | **New** — verbatim copy from user-global (`SKILL.md` + `assets/` + `references/` + `scripts/`). |
| `.claude/skills/claude-api/` | **New** — copy from user-global + Shomer.AI addendum appended to `SKILL.md` (covers Haiku 4.5 + caching defaults + adapter file paths). |
| `.claude/skills/README.md` | Project-scoped count 20 → 22; user-global section trimmed; gap-analysis pointer updated. |
| `.claude/gaps.md` | Status note added at top; Action plan items marked DONE; count tables updated. |
| `plan-docs/decisions/agents-skills-cleanup.decision.md` | **This file** — captures D1–D4. |

---

## Reading list for revisit

When this decision file is reopened in 6 months:

- The override rule (`.claude/agents/README.md` "Override rule" section) — still load-bearing.
- The locked DictaBERT architecture (`docs/concepts/dictabert_classifier_architecture.md`) — still locked? If the architecture has been re-derived, the `ai-researcher-developer` twin needs an update.
- The composition-root rule (`docs/design/README.md`) — still load-bearing? If the architecture has gone microservices, the `backend-developer` twin needs an update.
- The two skill promotions — still relevant? `hebrew-latex-pdf` is only relevant if the business plan is still LaTeX-based. `claude-api` is only relevant if the Context Agent still uses the Anthropic SDK.
