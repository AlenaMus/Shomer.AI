# Session prompts log

This folder is the **per-session audit trail** of what the user asked for and what was produced.
The convention is defined in `CLAUDE.md` → "Session prompts log — REQUIRED on every session". This file is just the index + quick how-to.

## File naming

`YYYY-MM-DD_meeting-N.md`

- `YYYY-MM-DD` — the session date in ISO form (convert relative phrasing like "yesterday" to the absolute date).
- `N` — the **next upcoming meeting number** the session is preparing for. After a meeting just happened, `N` is the *next* meeting, not the one that passed.
- Multiple sessions on the same date for the same meeting → suffix with `-2`, `-3`, … (e.g. `2026-05-30_meeting-4-2.md`).

Examples:
- `2026-05-30_meeting-4.md` — session on 30/05/2026, preparing for Meeting 4.
- `2026-06-02_meeting-4-2.md` — second session on a later date, still preparing for Meeting 4.

## What goes inside

Per turn (one user prompt → one assistant response that closed it out): a 3-6 line digest covering:

- A one-line restatement of what the user asked.
- Bullet list of what was produced (with links to files).
- Any new decisions, skills, or notable artifacts.

The full structure lives in `_template.md` — copy it as the starting point for each new session file.

## When to write

- **As the session progresses** — append a new `### N. …` block after each substantive prompt. Don't try to reconstruct at session end; early turns will be blurry by then.
- The first prompt of a session creates the file.
- **Skip** sessions consisting of a single trivial question with no produced artifact ("what's the meeting date?"). If any file was created or changed, log it.

## Relationship to other artifacts

- **`plan-docs/decisions/*.decision.md`** — records *what was decided and why*. The prompts log records *what happened*. When a turn produces a decision, the prompts entry links to the decision file rather than restating it.
- **`docs/prompt-book.md`** — a curated highlight reel of the most reusable / illustrative prompts, in the 7-field academic format. The prompts log is the raw chronicle; the prompt book is the polished excerpt. Promote entries from the log into the book when they're worth showing off.
- **`CLAUDE.md` "Session update — YYYY-MM-DD" blocks** — coarse-grained, project-wide narrative deltas. The prompts log is finer-grained (turn-level) and per-session. Both are useful.
