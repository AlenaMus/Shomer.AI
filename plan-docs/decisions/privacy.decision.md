# Privacy & Consent — Decisions (Monitoring App)

Decisions taken at the start of the real-monitoring-app sprint (2026-06-07). This
system passively monitors text a **minor** reads (and sends) inside third-party
apps — it is surveillance-adjacent and the privacy model must be the *default path*,
not an opt-in feature. Companion: `monitor-architecture.decision.md`,
`parent-surface.decision.md`. Approved plan:
`C:\Users\Dima\.claude\plans\linked-yawning-sifakis.md`.

---

## D1 — Monitor scope: INBOUND + OUTBOUND (child as victim *and* aggressor)

**Question:** Should the monitor classify only what the child *receives* (bullying
directed at the child), or also what the child *sends* (the child bullying others)?

**Choice:** **Both inbound and outbound.** The on-device capture tags each event
with `direction ∈ {inbound, outbound}`; both are classified. The child's own typed
text is monitored (catches the child as an aggressor), not dropped.

**Why:** The user explicitly chose inbound+outbound. Cyberbullying safety for a
minor includes catching the child harming peers, not only being harmed. The
direction tag lets the parent surface and any future analysis distinguish the two.

**Cost / obligation this creates:** A larger privacy footprint and a stronger
consent requirement than inbound-only. Mitigated by D2 (classify-and-discard) and
D4 (explicit consent copy covering outbound). The on-device pre-filter still drops
non-Hebrew / chrome / short text in both directions.

**Alternatives considered:**
- *Inbound-only* — smaller footprint, simpler consent, lower volume; passed over
  because it misses the child-as-aggressor case the user wants covered.

**Revisit:** If a privacy/ethics review (or Dr. Segal) pushes back on outbound
monitoring of the child's own messages — outbound could become a parent-configurable
toggle defaulting off.

---

## D2 — Classify-and-discard by default; persist only flagged excerpts

**Question:** What does the server store from the monitored stream?

**Choice:** **Classify-and-discard.** Non-flagged events store *nothing
content-bearing* — at most a one-way `text_hash` (TTL-expired in the dedup window)
and counters. Only **flagged** events (offensive or borderline) persist, and only:
`label`, `severity`, parent-facing Hebrew `explanation`, and a **truncated quote
≤200 chars** — never the full message, never the conversation. Gated by a setting
`MONITOR_STORE_RAW=false` (default). Monitor traffic uses `input_type="monitor"`;
for non-flagged monitor events the raw text is stored as `""`/hash, not the content.

**Why:** Data minimization is the single most important privacy control for
monitoring a minor. Storing only actionable flagged excerpts gives the parent what
they need to act while keeping the vast majority of benign content un-retained.

**Explicit deny-list (never stored):** full raw stream of non-flagged events ·
counterparty names/handles/phone numbers · the child's social graph (who they talk
to) · screenshots · location · contacts · app-usage analytics beyond the
`app_package` of a *flagged* event · any PII inside `child_id` (opaque server-minted
UUID).

**Alternatives considered:**
- *Store the full stream for parent review / model training* — rejected: maximal
  privacy harm; not needed (the parent acts on flags; training uses the parent's
  explicit labels on flagged items, D3 of parent-surface).

**Revisit:** Never loosen without a documented privacy review. The Context Agent's
short conversation-history retention (existing 7-day `RetentionSweeper`) is the one
multi-turn exception and stays minimal + opaque-keyed.

---

## D3 — Security: device-token auth, TLS in prod, at-rest encryption, PII-scrub logs

**Question:** The dev server is open cleartext LAN. What does real monitoring
require?

**Choice:**
- **Auth on every device/parent endpoint** (S2): child devices carry a long-lived
  **device token** (`Authorization: Bearer`), validated in the Gatekeeper group
  against `IdentityStore`; a child token may ingest only its own `child_id`, a
  parent may read only their own children's flags.
- **TLS only in production.** The dev cleartext LAN (`10.0.2.2:8000` /
  `<PC-LAN-IP>:8000`, cleartext network-security-config) stays **dev-only**; the
  prod host forbids cleartext in the Android `networkSecurityConfig`. TLS terminated
  at a reverse proxy in front of uvicorn.
- **Encryption at rest** for the flagged-event + conversation tables (SQLCipher or
  disk encryption); the on-device offline buffer is app-private encrypted storage,
  flushed-and-wiped on upload.
- **PII-scrub server logs** (backlog G-06 becomes mandatory): no raw monitored text
  at INFO in production.

**Why:** Real device traffic over an open LAN with no auth is unacceptable for a
product handling a minor's messages; these are the minimum bars before any non-dev
deployment.

**Alternatives considered:**
- *Keep open LAN for the MVP demo* — acceptable for **dev/demo only** and documented
  as such; not a production posture.

**Revisit:** S5 (hardening) implements TLS/at-rest/log-scrub; S2 implements auth.

---

## D4 — Dual consent + non-dismissible monitoring indicator (covers outbound)

**Question:** What consent and disclosure does monitoring a minor — including their
outbound messages — require?

**Choice:** **Dual disclosure.** The guardian (parent) consents and configures; the
**child is informed** that monitoring is active via a **visible, non-dismissible
"monitoring active" indicator** in child-mode. A consent screen states the exact
data flow in plain language, with **explicit copy for outbound monitoring** ("text
your child sends is also checked"). A privacy-policy doc accompanies it; the thesis
gets an ethics/consent section.

**Why:** Covert monitoring of another person violates Google Play policy and basic
data-protection norms; explicit, disclosed parental monitoring with a visible
indicator is both the ethical and the policy-compliant path. Outbound monitoring
specifically must be disclosed, not buried.

**Deployment reality:** `AccessibilityService`-for-monitoring is heavily scrutinized
on Play; the academic MVP ships as sideload / internal-test, documented as a
deployment constraint, not a blocker.

**Alternatives considered:**
- *Silent/covert monitoring* — rejected: unethical, Play-policy-violating, and
  legally fraught for a minor.

**Revisit:** S5 implements the consent screen + indicator; revisit copy if scope
(e.g. which apps) changes.
