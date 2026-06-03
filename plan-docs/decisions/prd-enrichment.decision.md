# PRD Enrichment — Decisions (post-freeze additions to PRD v1.0)

**Phase:** Meeting 4 (PRD + architecture freeze) — late-stage additions
**Decided on:** 2026-05-31
**Decided by:** Alona, in dialogue (Claude surfaced gaps + options)
**Predecessor:** [`architecture.decision.md`](architecture.decision.md) — Architecture B locked on 2026-05-30 with 4 sub-decisions (D-Arch-Variant, D-Arch-Model, D-Arch-Form, D-Arch-LLM).

This file captures decisions made the day after the architecture freeze, in response to gaps Alona noticed when reviewing the PRD:
- **D1 — SDK as first-class component:** SDK was present in the project tree (`server/sdk/`) but absent from the PRD and architecture. Elevated to PRD-level component.
- ~~**D2 — Explicit Gatekeeper-vs-Monitor product positioning:**~~ **REVERTED same session.** See "D2 — REVERTED" entry below for full audit trail.
- **D3 — Gatekeeper / API Gateway component added to architecture:** New rate-limit + observability layer added to the architecture. (After D2 was reverted, this is now the *only* "gatekeeper" concept in the document, so no disambiguation is needed.)

These additions do **not** override Architecture B from `architecture.decision.md` — they enrich the PRD's coverage of components that were either implicit, missing, or untextured.

Format per decision: **Question → Choice → Why → Alternatives considered → When to revisit**.

---

## D1 — Elevate SDK from placeholder to PRD-level component

**Question:** The `server/sdk/` folder exists as a placeholder (`server/sdk/README.md` describes intent only). Should the SDK be promoted to a first-class component in the PRD and architecture diagrams, or stay as infrastructure-detail that the PRD ignores?

**Choice:** **Elevate to PRD-level component.** Added to:
- §1 (Executive Summary) — listed as one of the things being built (item 5 of 6).
- §7.2 (C4 Container diagram) — drawn as `Shomer.AI SDK` sub-component inside each client Container (child + parent Android apps), purple swimlane, with explicit edge from SDK → Gatekeeper.
- §8.6 (new Component-level PRD) — full spec: role, languages (Kotlin MVP, TS Phase 9), wrapped endpoints, retry semantics, implementation approach (hand-written for MVP — deferred from `server/sdk/README.md`), success metrics, versioning.

**Why:**
- The SDK is the seam between every client and the FastAPI server. Without it visible in the PRD, the architecture implies that each client hand-rolls HTTP — which contradicts the actual project structure and the API-as-a-product line in the business plan.
- Defense risk at Meeting 4: if Dr. Segal asks "how does a third-party integrate with Shomer.AI?", the only honest answer with the old PRD was "they don't — we have Android client only". With SDK in the PRD, the answer is "they import `com.shomer.sdk` and call `classify(text)` — same path the Android client uses".
- Business-plan consistency: the business plan §5 sells API-as-a-product to schools and platforms. The PRD must back that claim with a component spec, not just an infrastructure folder.
- Cost of adding: trivial — the SDK is already conceptually present; this is a documentation enrichment, not new engineering work. Implementation lands in Meeting 5 (replace Android Client's hand-rolled HTTP with SDK calls).

**Alternatives considered:**
- *Leave SDK out of PRD, mention only in `server/sdk/README.md`:* the path I almost took. Rejected because it makes the architecture diagram lie (Android Client → FastAPI directly, when in reality the project intends a SDK layer).
- *Add SDK as a future-work item in §11 (Out-of-Scope):* would have under-sold what's actually planned. The SDK IS in MVP scope — Meeting 5 will build the first version.
- *Defer the Hand-written vs Generated-from-OpenAPI choice (status quo from `server/sdk/README.md`):* split — kept the implementation-approach choice deferred until Meeting 5, but locked the **conceptual presence** of the SDK in this PRD.

**Revisit:**
- After Meeting 5: lock the Hand-written-vs-Generated implementation choice based on actual experience adapting the Android client.
- After Meeting 8: if 3rd-party interest emerges, promote SDK to a separate top-level concern with its own versioning + changelog + published artifact (Maven Central / npm).

---

## D2 — REVERTED — Explicit Gatekeeper-vs-Monitor product positioning (PRD §5.1)

**Status:** ❌ **Reverted within the same session (2026-05-31).**

**Original choice (now reverted):** Add explicit §5.1 sub-section "Gatekeeper vs Monitor: למה Shomer.AI היא Monitor במכוון" — definitional table + 5 reasons (technical / academic-RQ / legal / UX / trust) + theoretical sidebar.

**Why reverted:** Alona requested removal: *"תוריד את עניין של gatekeeper vs monitoring בהקשר של המוצר, תשאיר רק בהקשר של הטכנולוגי של הפיתוח"*. The product-positioning framing was deemed unnecessary; the existing one-line table cell in §5 ("מציע ולא חוסם") is enough to communicate the intent, without a half-page defense built around a vocabulary the PRD doesn't otherwise use.

**What was removed:**
- §5.1 sub-section deleted from `docs/PRD.md`.
- ⚠️ disambiguation note in §5.1 (pointing forward to §7.2/§8.7) — deleted.
- Disambiguation paragraph below §7.2 C4 diagram ("Gatekeeper here ≠ Gatekeeper in §5.1") — deleted.
- Disambiguation line in `docs/architecture_diagrams.md` key-points ("אינו קשור לדיון Monitor vs Gatekeeper המוצרי ב-PRD §5.1") — deleted.
- Historical note in §8.7 referencing the §5.1 cross-link — softened to a neutral note about why the Gateway was added (load + observability).

**What stays:**
- §5 table row "מציע ולא חוסם" — unchanged; carries the product intent compactly.
- §8.7 Gatekeeper / API Gateway component — fully preserved (this is what D3 covers).
- Orange Gateway swimlane in §7.2 + `architecture_diagrams.md` — unchanged.

**Side benefit of the revert:** with D2 gone, the word "Gatekeeper" now appears in only ONE sense across the document — the technological API Gateway (D3). No more disambiguation needed; the document reads cleaner.

**Lessons / when to revisit:**
- If the Meeting 4 audience asks "why don't you just block messages?", fall back to the technical reason verbally (Android accessibility-services restrictions for parental-control apps in 2022-2024) — this is the strongest one-line defense and doesn't require the PRD to carry a half-page argument for it.
- If a future reviewer pushes back hard enough to need a written defense, re-add a leaner version (one paragraph, technical reason only) rather than the original 5-reason version.

---

## D3 — Add Gatekeeper / API Gateway as architectural component (PRD §8.7)

**Question:** Should the architecture include an explicit Gatekeeper / API Gateway component between the SDK and the FastAPI classification core — for rate limiting, observability, and load management?

**Choice:** **Yes — add §8.7 "Gatekeeper / API Gateway"** as a distinct component, shown in the C4 Container diagram as a Edge layer between the SDK and the classification core.

**Implementation in MVP** = FastAPI middleware chain (in-process, single deployment):
- `slowapi` — rate limiting (100 req/min per IP default, env-configurable)
- `structlog` + `python-json-logger` — structured logging with trace-id per request
- `prometheus-fastapi-instrumentator` — Prometheus metrics on `/metrics`
- FastAPI built-ins — request size limit (10MB), timeout enforcement (60s text / 180s image)

**Phase 9 stretch:** API key auth (per-tenant for 3rd-party integrations), per-key rate limits, circuit breaker, optional request caching.

**Why:**
- Alona asked for it explicitly: "אני צריכה להוסיף gatekeeper לארכיטקטורה של הפרויקט במובן הטכנולוגי...כדי לשלוט על העומסים ולנתר קריאות". Direct ask, direct answer.
- Real production systems separate Edge concerns (rate limit, auth, observability) from core business logic (classification). Architecting that separation now — even if implementation is middleware in MVP — makes the upgrade path to a real reverse proxy (nginx + Lua, Traefik, Kong) zero-cost.
- Provides the data source for several NFRs in §9: p99 latency, request volume, error rate. Without explicit observability, Meeting 8 evaluation has nothing to measure against the NFRs.
- Conceptual cleanliness: the C4 diagram now correctly distinguishes "what the system does to a request" (classification) from "how the system manages requests" (gateway).

**Naming clarity (after D2 revert):** with D2 removed, "Gatekeeper" now appears in only one sense across the document — the technological API Gateway here. No disambiguation note needed.

**Alternatives considered:**
- *Skip — leave as implicit FastAPI middleware:* rejected because the user explicitly asked for it, AND because making it explicit gives Meeting 8 evaluation a defined surface for NFR measurement.
- *Use a heavyweight gateway (Kong / Tyk / AWS API Gateway):* rejected for MVP — overkill for a thesis demo, requires separate process + container + deployment story. FastAPI middleware delivers 95% of the value at 5% of the complexity. Heavyweight gateway can replace the middleware later without code changes elsewhere.
- *Build a custom proxy in a separate Python process:* rejected — same overkill problem, with the additional cost of building rate-limit logic from scratch when `slowapi` exists.

**Revisit:**
- After Meeting 8: if metrics show the gateway middleware is a latency bottleneck (>5ms p99 overhead), switch to a sidecar reverse proxy (Caddy or nginx) for the metrics + rate-limit work, keep request validation in FastAPI.
- If a 3rd-party integration arrives in Phase 9: add API key auth as the first new responsibility on the gateway, before everything else.

---

## Linked artifacts

- **PRD:** `docs/PRD.md` — updated §1 (item 5 SDK added), §7.2 (C4 diagram now shows SDK + Gateway), §8.6 (new Client SDK component), §8.7 (new Gatekeeper / API Gateway component). [§5.1 was added and then removed in the same session — see D2 REVERTED above.]
- **Architecture diagrams:** `docs/architecture_diagrams.md` — Diagram 1 (C4) updated to match PRD §7.2; legend extended with purple (SDK) and orange (Gateway) swimlanes; "נקודות מפתח" extended from 3 to 5 to cover both new components.
- **Predecessor decision (still authoritative for everything else):** `plan-docs/decisions/architecture.decision.md` — Architecture B + 4 sub-decisions; not overridden by this file, only enriched.
- **SDK placeholder README:** `server/sdk/README.md` — still source-of-truth for the Hand-written-vs-Generated implementation choice (deferred to Meeting 5).
- **Concepts glossary:** `docs/concepts/concepts.md` — should be extended in a future session with entries for "API Gateway / Gatekeeper" and "SDK" (not done in this turn to stay scoped to PRD edits).
