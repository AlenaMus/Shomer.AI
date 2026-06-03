# Shomer.AI LLD Package - Architecture Review

**Document:** Pre-implementation review of the 9 Low-Level Design documents
**Prepared for:** Meeting 4 sign-off
**Reviewer:** Architecture Review Agent
**Date:** 2026-05-31

---

## 1. Executive Summary

The 9-LLD package is **Conditional Ready** for task execution. The design is technically sophisticated, internally consistent on the happy path, and covers the majority of PRD requirements. However, 3 blockers must be resolved before the first implementation sprint because they will force schema-level rewrites within week 1 if left open. An additional 7 important issues will cause engineering friction but do not prevent work from starting on several unblocked modules.

**Top three reasons for Conditional rating:**

1. **Audit Log has no standalone LLD.** PRD section 8.5 treats the Audit Log as a first-class component. The schema is split: server/design.md section 5.1 owns requests and alert_history tables; context_agent/design.md section 5.1 owns agent_traces. The conversations table (needed by ToolRunner.read_conversation_history) is missing from both. The retention cron, JSONL sink, and gold-set annotation columns for Meeting 8 ΔFPR evaluation are missing from all LLDs.

2. **Label spelling is actively inconsistent.** "none-offensive" (hyphen) appears in classifier/design.md section 2.2 Category Literal and PRD section 8.1. "non_offensive" (underscore) appears in server/app/schemas.py line 7, server/app/prompt.py line 8, sdk/design.md section 2.2, and android_client/design.md example logs. This is a runtime bug at the triage-classifier boundary.

3. **Confidence direction is unresolved in triage router.** Server/design.md section 4.2 flags that confidence flips meaning between offensive and non-offensive labels. The triage/design.md section 3 _decide_inner pseudocode applies confidence thresholds without conditioning on result.is_offensive. For label="non_offensive", confidence=0.92: 0.92 >= 0.7 routes to ALERT_DIRECT instead of SILENT -- causing the parent to receive alerts for safe messages.

**Counts: 3 Blockers · 7 Important · 5 Nice-to-have**

---

### Status update — 2026-05-31 (post-review fixes)

All 3 blockers have been resolved. The package is now **Ready** for implementation start, modulo the 7 Important items that should be picked up during week 1.

| Blocker | Resolution | Evidence |
|---|---|---|
| **G-01** Audit Log has no standalone LLD | New `docs/design/audit_log/design.md` (758 L) + `tasks.json` (14 tasks); `tasks_index.json` now at 138 tasks; `README.md` module index updated to 10 rows; `SERVER-LIFESPAN-01` and `CTX-TOOLS-01` now depend on `AUDIT-IF-01` | `audit_log/design.md` §1-§11 |
| **G-02** Label spelling inconsistent | Locked to `non_offensive` (underscore). Edits applied to `PRD.md` §8.1, `classifier/design.md` §2.2/§5.2/§5.3/§6.1/§8/§11, `classifier/tasks.json` (5 occurrences replaced; semantic flip of legacy-normalization test acceptance). Remaining `none-offensive` mentions are intentional citations of SinaLab's upstream column name in `references.bib` and `literature_flagship.md`. | `classifier/design.md` §5.2 resolution note; `classifier/design.md` §11 Q1 marked ✅ |
| **G-03** Confidence direction footgun | `triage/design.md` §3 `_decide_inner` now normalizes to `prob_offensive = result.confidence if result.is_offensive else 1 - result.confidence` BEFORE applying thresholds. 6-row polarity test matrix added to §3 as a mandatory contract test. Decision Rules Summary updated. §11 row marked ✅ Resolved. | `triage/design.md` §3 Step A / Step B / Polarity Test Matrix |

The 3 blocker fixes unblock: classifier, triage, server lifespan skeleton, context_agent (read_history now has an AuditStore Protocol to depend on), parent-app dashboard (audit_log query interface defined), and Meeting 8 evaluation scripts (gold_label + frontline_only_decision columns on the classifications table). The previously-unblocked 4 modules (gatekeeper, ocr, sdk, android_client child flavor) remain unblocked.

The 7 Important issues (G-04 port naming, G-05 error model, G-06 PII scrub, G-07 A/B eval procedure, G-08 retention impl owner — now answered by G-01, G-09 Slang Lexicon LLD, G-12 health rollup, G-14 gold-set annotation procedure — partially answered by `AUDIT-GOLD-01`) still need attention but do not block sprint start.


---

## 2. PRD Requirements Coverage Matrix

Coverage legend: COVERED = fully addressed | PARTIAL = addressed with gaps | NOT COVERED = missing | OUT OF SCOPE = per PRD section 11

### PRD section 8 — Component-level Requirements

**8.1 Frontline Classifier**
**8.2 OCR Pipeline**

---

## 2. PRD Requirements Coverage Matrix

Coverage legend: COVERED = fully addressed | PARTIAL = addresses with gaps | NOT COVERED = missing | OUT OF SCOPE = per PRD section 11

### PRD section 8 — Component Requirements

**8.1 Frontline Classifier (Owner: classifier/design.md)**
5-label classification: classifier section 2.2 Category type, section 3.2 OllamaClassifier. COVERED. Gap: label spelling inconsistency G-02.
p99 < 100ms CPU: classifier section 7.1 latency test plan. COVERED.
macro-F1 >= 0.78: classifier section 7.2 and section 3.3 training pipeline. COVERED.
failure fallback (returns error=True never raises): classifier section 8 and section 2.1 Protocol contract. COVERED.

**8.2 OCR Pipeline (Owner: ocr/design.md)**
Tesseract heb+eng: ocr section 3.2 TesseractRunner. COVERED.
p99 < 2s: ocr section 7.1 latency test. COVERED.
CER < 15%: ocr section 7.2 CER measurement plan. COVERED.
image_unreadable signal: ocr section 5.2 signal semantics table. COVERED.

**8.3 Context Agent (Owner: context_agent/design.md)**
GPT-4o-mini primary, Haiku 4.5 fallback: context_agent section 2.5 Port 2 LlmClient, section 3.2 LlmRouter. COVERED.
3 tools (read_history, lookup_slang, check_age): context_agent section 3.2 ToolRunner, section 3.3 JSON schemas. COVERED.
p99 < 3s: context_agent section 7.1 latency test. COVERED.
stateless (no persistent memory): context_agent section 5.2 stateless design. COVERED.
fallback to frontline + review_flag: context_agent section 8, section 3.2 _fallback_result. COVERED.
ΔFPR measurement path (A/B embedded): context_agent section 7.2, triage section 5 audit fields. COVERED.

**8.4 Notification Service (Owner: alerts/design.md)**
FCM push to parent: alerts section 3 FCMNotificationService. COVERED.
explanation + quote in payload: alerts section 2.1 AlertRequest fields. COVERED.
p99 < 2s: alerts section 7 NFR test plan. COVERED.

**8.5 Audit Log (Owner: server/design.md section 5.1 + context_agent/design.md section 5.1 — split, no standalone LLD)**
7-day retention: Retention cron mentioned in prose in server section 5.1 only; no standalone LLD; no implementation class or test. PARTIAL. See G-01, G-08.
SQLite + JSONL: Schema defined in LLD; existing audit.py writes JSONL only, no SQLite implemented yet. PARTIAL.
full CA reasoning trace: context_agent section 5.1 agent_traces table. COVERED.

**8.6 Client SDK (Owner: sdk/design.md)**
Kotlin wraps 4 endpoints (/classify, /classify-image, /health, /model/info): sdk section 2.1 ShomerClient, section 3.1 package layout. COVERED.
ShomerResult<T> sealed hierarchy: sdk section 2.3 ShomerResult + ShomerError. COVERED.
retry 3 attempts 1s/2s/4s: sdk section 3.3 retry logic detail. COVERED.

**8.7 Gatekeeper / API Gateway (Owner: gatekeeper/design.md)**
rate-limit 100 req/min per IP: gatekeeper section 2.5 Port 1 RateLimitStore, section 3.2 build_limiter. COVERED.
structured logging + trace-id: gatekeeper section 3.3 TraceIdMiddleware, section 6.1 logger. COVERED.
/metrics Prometheus endpoint: gatekeeper section 2.3, section 6.3 metrics table. COVERED.
request size 10MB limit: gatekeeper section 3.3 RequestSizeMiddleware. COVERED.
fail-open on rate-limit store failure: gatekeeper section 8 failure modes. COVERED.

### PRD section 5 — User Flows

Child sends text -> server classifies -> silent if safe: server section 4.2 fast path sequence. COVERED.
Child sends screenshot -> OCR -> classify -> same pipeline: server section 4.3 /classify-image sequence. COVERED.
Borderline -> Context Agent reasons on 5 turns: context_agent section 4.1 happy path sequence. COVERED.
Real threat -> push alert with explanation + quote: alerts section 4 happy path sequence. COVERED.
Tame result -> silent, no notification: triage section 3 SILENT path. COVERED.
LLM unreachable -> frontline fallback + review_flag: context_agent section 4.3 both-fail sequence. COVERED.

### PRD section 9 — Non-Functional Requirements

Frontline latency p99 < 100ms: classifier section 7.1 test plan; server section 6c NFR matrix. COVERED.
Context Agent latency p99 < 3s: context_agent section 7.1 latency test. COVERED.
End-to-end latency p99 < 5s: server section 6c test_e2e_latency.py. COVERED.
Cost/interaction < $0.005: context_agent section 6.4 TokenManager daily budget enforcement. COVERED.
Accuracy frontline macro-F1 >= 0.78: classifier section 7.2 SinaLab test procedure. COVERED.
ΔFPR >= 15pp: context_agent section 7.2 gold-set measurement plan. COVERED.
Privacy: no PII in external LLM calls: CA_PRIVACY_MAX_CHARS limits chars but no explicit scrub step documented. PARTIAL. See G-06.
Availability frontline >= 99%: classifier section 8 failure fallback; server section 6c uptime test. COVERED.
Availability CA >= 95%: context_agent section 8; server section 7 test_fallback_chain. COVERED.
Hardware RTX 5080 16GB: classifier section 3.3 hyperparameter table BF16. COVERED.
Languages Hebrew MVP: classifier section 3.3 DictaBERT; ocr section 3.2 heb+eng. COVERED.
Gateway overhead < 5ms p99: gatekeeper section 7 test_gateway_overhead.py. COVERED.
Audit retention 7 days: Mentioned in server section 5.1 prose only; no implementation class or test. PARTIAL. See G-01, G-08.

### PRD section 10 — KPIs

Research KPI: ΔFPR >= 15pp: context_agent section 7.2 A/B measurement plan including McNemar test. COVERED.
Research KPI: Recall non-inferior <= 3pp drop: context_agent section 7.2 gold-set evaluation plan. COVERED.
Research KPI: macro-F1 >= 0.78: classifier section 7.2 SinaLab test split evaluation. COVERED.
Research KPI: IAA kappa >= 0.6: No LLD covers gold-set annotation procedure. NOT COVERED. See G-14.
Research KPI: McNemar p < 0.05: context_agent section 7.2 statistical test plan. COVERED.
Commercial KPIs (users, ARPU, revenue): Out of scope per PRD section 11. OUT OF SCOPE.
Alert-fatigue churn < 3/day: triage_decisions_total metric; ΔFPR directly addresses this. COVERED.
< 20% traffic to paid LLM: triage_decisions_total{decision=escalate_to_ca} counter. COVERED.

### Locked Architecture Decisions

D-Arch-Variant: Architecture B (text + Chat-OCR only): Vision LLM out-of-scope uniformly enforced across all LLDs. COVERED.
D-Arch-Model: DictaBERT-base: classifier section 3.3 train_dictabert.py. COVERED.
D-Arch-Form: Single Context Agent in-process: context_agent section 3 single ContextAgent class; server section 3.2 in-process. COVERED.
D-Arch-LLM: GPT-4o-mini primary, Haiku 4.5 fallback: context_agent section 2.5 Port 2, section 3.2 LlmRouter. COVERED.
D-Arch-OCR: Tesseract heb+eng: ocr section 3.2 TesseractRunner config. COVERED.
D1 prd-enrichment: SDK as PRD-level component: sdk section 1, section 2. COVERED.
D3 prd-enrichment: Gatekeeper/API Gateway component: gatekeeper section 1, section 3. COVERED.
Privacy boundary (message + <=5 turns, no PII): CA_PRIVACY_MAX_CHARS configured; explicit scrub step missing. PARTIAL. See G-06.
Confidence threshold 0.3-0.7 borderline zone: triage section 6 TriageSettings, .env.example. COVERED.

---

## 3. Architecture Diagram Consistency Check

### C4 Container Diagram

ChildApp (Shomer.AI Client Kotlin/Compose): android_client section 3.1 child flavor. MATCH.
ChildSDK (Shomer.AI SDK Kotlin lib): sdk section 1. MATCH. Same SDK used for child and parent flavors.
Gateway (Gatekeeper/API Gateway): gatekeeper section 1. MATCH. Orange swimlane confirmed.
Server (FastAPI :8000): server section 1. MATCH.
OCR (Tesseract heb+eng): ocr section 1. MATCH.
DictaBERT-base frontline classifier: classifier section 1. MATCH.
Context Agent (in-process): context_agent section 1. MATCH.
SlangDB (Slang Lexicon local DB): server section 3.1 slang_db/ package stub. PARTIAL. No standalone SlangDB LLD. See G-09.
AuditLog (7-day retention): server section 5.1 + context_agent section 5.1. PARTIAL. Schema split; no standalone LLD. See G-01.
Metrics (/metrics endpoint): gatekeeper section 2.3, section 6.3. MATCH. Owned by gatekeeper confirmed.
GPT-4o-mini: context_agent section 2.5 Port 2 GptMiniClient. MATCH.
Claude Haiku 4.5 (fallback): context_agent section 2.5 Port 2 HaikuClient. MATCH.
ParentApp (Dashboard + Push notifications): android_client section 2.1 ParentDashboardViewModel. MATCH.
ParentSDK (Shomer.AI SDK Kotlin lib): sdk section 1. MATCH. Same SDK, parent flavor.

C4 Edges:
ChildSDK -> Gateway (HTTPS message/screenshot): sdk section 4.1 TraceIdInterceptor; gatekeeper section 4.1 sequence. MATCH.
Gateway -> Server (validated, rate-limit OK): gatekeeper section 3.2; server section 2.5. MATCH.
Gateway -> Metrics (emit metrics + structured log): gatekeeper section 3.3 PrometheusMetricsEmitter. MATCH.
Server -> OCR (if image): server section 4.3. MATCH.
OCR -> Server (extracted text): ocr section 2; server section 4.3. MATCH.
Server -> DictaBERT (classify): server section 4.1. MATCH.
Server -> Agent (if borderline 0.3-0.7): triage section 3 ESCALATE_TO_CA; server section 4.1. MATCH. Threshold 0.3-0.7 confirmed in triage section 6.
Agent -> SlangDB (tool: read history / slang): context_agent section 3.2 ToolRunner.lookup_slang. MATCH. Slang schema gap G-09.
Agent -> GPT-4o-mini (reason about context): context_agent section 3.2 LlmRouter. MATCH.
Agent -> Haiku (if API unreachable, dotted): context_agent section 3.2 LlmRouter fallback, section 4.2. MATCH.
Server -> AuditLog (log full trace): server section 6b; context_agent section 5.1. PARTIAL. Write path exists; ownership ambiguous. See G-01.
Server -> ParentSDK (push notification HTTPS): alerts section 3 FCMNotificationService. PARTIAL. Actual delivery transits FCM cloud (Google), not direct HTTPS. See G-10.

### Data Flow Diagram

All elements match their LLD counterparts. Borderline threshold 0.3-0.7 confirmed in triage section 6. The 'if LLM unreachable' dotted edge to Manual confirmed in context_agent section 4.3. The confidence >=0.7 or <=0.3 confident path confirmed in triage section 3.

### Sequence Diagram (Borderline Case)

All sequence steps match. The Agent->>Log (write reasoning trace) step maps to context_agent section 5.1 agent_traces write. The alternative flow (LLM timeout) is covered in context_agent sections 4.3 and 8.

### Suspected Gap Checks

Audit Log (PRD section 8.5 + C4 AuditLog box): Not owned as a first-class module. Schema split between server section 5.1 (requests table) and context_agent section 5.1 (agent_traces table). No standalone audit_log/design.md exists. See G-01.

/metrics endpoint (C4 Metrics box): Owned by gatekeeper/design.md sections 2.3 and 6.3. CONFIRMED. Served at port 8000 /metrics in Prometheus text format.

Slang Lexicon (C4 SlangDB): server section 3.1 lists slang_db/ as a package stub. context_agent section 9.4 documents the JSON schema and Meeting 6 initial population (~200 entries) but no update path, curation criteria, or version control strategy. See G-09.

Push notification path to ParentSDK (C4 edge): The actual delivery path is server -> firebase-admin -> FCM cloud (Google) -> Android FCM service -> Room -> ViewModel. The FCM cloud hop transits Google's infrastructure. The C4 edge label 'push notification HTTPS' is accurate for the server-to-FCM leg but the cloud hop is unacknowledged. See G-10.

Dashboard + History on Parent phone (C4 ParentApp): Covered in android_client sections 2.1, 3.1 (DashboardScreen, HistoryScreen, AlertDetailScreen). CONFIRMED.

'if API down -> Haiku' fallback edge: Covered in context_agent section 3.2 LlmRouter and section 4.2 GPT-4o-mini-fails sequence. CONFIRMED.

'if borderline -> Context Agent' with 0.3-0.7 threshold: Owned by triage/design.md sections 3 and 6 TriageSettings. Configurable via TRIAGE_BORDERLINE_LOW and TRIAGE_BORDERLINE_HIGH env vars. CONFIRMED.

---

## 4. Cross-Cutting Concerns Verification

### 1. Trace-ID Propagation

VERDICT: Covered with one observability gap (G-11).

Trace-ID is minted by TraceIdMiddleware (gatekeeper section 3.3) as uuid4() and bound to structlog context via bind_contextvars. All module log calls inherit trace_id automatically (server section 6.1 merge_contextvars). The audit row receives trace_id via AuditLoggingMiddleware (server section 6b trace_id flow diagram). The FCM alert payload carries trace_id in data.trace_id (alerts section 3 FCM payload schema). The SDK generates its own trace_id per request via TraceIdInterceptor (sdk section 3.2) and sends it as X-Trace-ID header.

Gap: The SDK and server generate separate UUIDs for the same request. The server does not propagate the client's X-Trace-ID as its own trace_id. End-to-end debugging requires matching the server's X-Request-ID response header to the client's outbound X-Trace-ID. See G-11 (Nice-to-have).

### 2. A/B Switch for RQ3 — CONTEXT_AGENT_ENABLED

VERDICT: Covered. The evaluation procedure for switching conditions at Meeting 8 is not documented. See G-07.

The flag is defined in triage section 6 TriageSettings. When false, borderline cases are decided by baseline_threshold (0.5 midpoint) instead of escalating to CA (triage section 3 A/B baseline path sequence). The context_agent_enabled field is written to every audit row (triage section 5). Server section 7 test_ab_switch.py verifies zero CA calls when flag is false. The flag is read only by triage, not by context_agent -- correct design.

### 3. Privacy Guarantee — No PII in External LLM Calls

VERDICT: Partially covered. Important gap; Blocker if Dr. Segal requires it at Meeting 4.

PRD section 9 states 'no PII in external LLM calls.' Context_agent section 6.2 defines CA_PRIVACY_MAX_CHARS=500 which limits total characters sent. However, the build_user_prompt() function in context_agent section 3.4 injects input.current_message and conversation history directly into the LLM prompt without any scrubbing step for phone numbers, @mentions, or names. Character-count limiting is not equivalent to PII scrubbing. Context_agent section 11 Q2 defers this to 'Confirm with Dr. Segal at Meeting 4.' See G-06.

### 4. 7-Day Retention

VERDICT: Partially covered — Important gap.

Server section 5.1 describes a lifespan() startup task that deletes rows older than 7 days. This is a prose description only -- no implementation class, no cron/task specification, no test. The existing server/app/audit.py is append-only JSONL only (no SQLite writes). The retention task has no implementation owner since there is no standalone audit_log LLD. See G-01 and G-08.

### 5. Cost / Token Budget

VERDICT: Covered.

Context_agent section 6.4 TokenManager enforces per-day global budgets (CONTEXT_AGENT_DAILY_USD_BUDGET=0.50 default). The cost_per_interaction NFR is measurable via context_agent_usd_spent_total / context_agent_requests_total from Prometheus (context_agent section 6.3). Per-call budget check blocks LLM calls when exhausted (context_agent section 4.4 sequence). The daily reset at midnight UTC is implemented via _today_utc() in TokenManager.

### 6. 5-Label Schema Consistency

VERDICT: Inconsistent — Blocker.

Label spelling across the codebase and design documents:
PRD section 8.1: none-offensive (hyphen)
classifier/design.md section 2.2 Category Literal: none-offensive (hyphen)
server/app/schemas.py line 7: non_offensive (underscore)
server/app/prompt.py line 8 VALID_CATEGORIES: non_offensive (underscore)
sdk/design.md section 2.2 ClassificationResult.category comment: non_offensive (underscore)
android_client/design.md section 6.1 example log: non_offensive (underscore)
server/design.md section 4.2 sequence: non_offensive (underscore)

The classifier LLD section 5.2 acknowledges the inconsistency and describes a normalization step (replace("-", "_") in prompt.py line 31 converts hyphens to underscores). The canonical runtime form is 'non_offensive' (underscore) but the PRD and classifier LLD use the hyphen form. See G-02.

### 7. Confidence Direction Footgun

VERDICT: Acknowledged but unresolved — Blocker.

Server/design.md section 4.2 contains a design note: 'For non-offensive results, confidence represents confidence in the non_offensive label, so high confidence = clearly non-offensive = SILENT. The Triage router treats confidence as offensive confidence.' The note defers resolution to triage/design.md.

Triage/design.md section 3 _decide_inner pseudocode applies thresholds without branching on result.is_offensive:
confidence <= borderline_low (0.3) -> SILENT
confidence >= borderline_high (0.7) -> ALERT_DIRECT

For label=non_offensive, confidence=0.92: 0.92 >= 0.7 routes to ALERT_DIRECT. This is wrong -- the parent would receive alerts for safe messages. The ClassifierResult model (triage section 2 input type) has is_offensive: bool but _decide_inner pseudocode does not branch on it. See G-03.

### 8. Health Rollup

VERDICT: Partially covered — Important gap.

Server section 9.6 checks classifier.is_alive(), audit.is_writable(), alerts.health_status(). It does NOT check: Tesseract binary present (OCR), OpenAI/Anthropic API key validity (Context Agent), or Gatekeeper health. The OcrBackend Protocol (ocr section 2.5) and ContextReasoner Protocol (context_agent section 2.5 Port 1) do not define a health() method despite README.md section 2 claiming each module exposes health() via its Protocol. See G-12.

### 9. Configuration Composition

VERDICT: Substantially covered; intentionally non-composed.

Server section 9.1 ServerSettings does not compose sub-module settings -- each module loads its own settings independently. Startup is fail-lenient for missing API keys (context_agent init warns but does not fail). The .env.example in server section 9.2 covers approximately 35 variables across all modules. This design choice is not documented explicitly in server section 9.1. See G-13 (Nice-to-have: documentation addition).

### 10. NFR Test Ownership

VERDICT: Covered for most NFRs; gold-set annotation procedure and IAA calculation missing.

Every PRD section 9 NFR row has at least one test task in a module's section 7. Missing: PRD section 10 KPI 'IAA kappa >= 0.6' -- no LLD covers the annotation procedure. The agent_traces table schema (context_agent section 5.1) has no gold_label column. The evaluation query in context_agent section 7.2 filters WHERE gold_label IS NOT NULL -- this column does not exist in the defined schema. See G-14.

---

## 5. Gap Analysis (Severity-Ranked)

### G-01: Audit Log has no standalone LLD  ✅ RESOLVED 2026-05-31
Severity: Blocker (resolved)
Resolution: New LLD at `docs/design/audit_log/design.md` (758 L, full 11-section template) + `tasks.json` (14 tasks AUDIT-IF-01 through AUDIT-DOC-01) + module added to `README.md` index + `tasks_index.json` updated to 138 entries. Schema covers 5 tables (classifications, agent_traces, alerts, conversations, gold_set_metadata). WAL mode chosen, NullAuditStore failure fallback explicit, `frontline_only_decision` column added for Meeting 8 A/B query.
What is missing: The Audit Log is a C4 first-class component and PRD section 8.5 component. Schema is split: server/design.md section 5.1 owns requests and alert_history tables; context_agent section 5.1 owns agent_traces. The conversations table (needed by ToolRunner.read_conversation_history) is missing from both. The retention cron, JSONL sink, and gold-set query interface have no single owner.
Why it matters: Engineers building Meeting 5 database tasks have no single source of truth. The Meeting 8 evaluation queries both requests and agent_traces -- coordination requires a shared owner.
Recommended resolution: Create docs/design/audit_log/design.md. Own: merged schema (all four tables -- requests, alert_history, agent_traces, conversations), retention cron as a lifespan() startup task, JSONL sink wrapping existing server/app/audit.py, gold_label column in agent_traces, and query API for Meeting 8 evaluation scripts.
Resolution owner: New LLD: docs/design/audit_log/design.md
Effort: M (half-day)

### G-02: Label spelling 'none-offensive' vs 'non_offensive' unresolved  ✅ RESOLVED 2026-05-31
Severity: Blocker (resolved)
Resolution: Canonical = `non_offensive` (underscore). All operational paths now use it. Updated: `docs/PRD.md` §8.1 categories row; `classifier/design.md` §1/§2.2/§5.2/§6.1/§8 plus §11 Q1 marked Done; `classifier/tasks.json` 5 string occurrences plus semantic flip of legacy-normalization test acceptance. Remaining `none-offensive` mentions are intentional citations of SinaLab's upstream column spelling and stay as historical references in `references.bib` and `literature_flagship.md`.
What is missing: PRD and classifier LLD use 'none-offensive' (hyphen). Running code and SDK/android LLDs use 'non_offensive' (underscore). The classifier LLD acknowledges the inconsistency but treats it as a runtime normalization workaround.
Why it matters: Audit rows, alert payloads, SDK contract, and Android display labels will silently produce a different value from the PRD-documented one. The gold-set annotation at Meeting 8 needs a canonical label vocabulary.
Recommended resolution: Lock 'non_offensive' (underscore) as canonical -- it is the form used in all code. Update classifier/design.md section 2.2 Category Literal and PRD section 8.1 to use the underscore form.
Resolution owner: classifier/design.md section 2.2; PRD section 8.1
Effort: S (30 minutes: one grep-replace pass)

### G-03: Confidence direction not resolved in triage router  ✅ RESOLVED 2026-05-31
Severity: Blocker (resolved)
Resolution: `triage/design.md` §3 `_decide_inner` now does Step A (normalize `prob_offensive = result.confidence if result.is_offensive else 1 - result.confidence`) before Step B (threshold routing). Decision Rules Summary rewritten. 6-row polarity test matrix added as a mandatory contract test (`tests/contracts/test_triage_engine_contract.py`). §11 row marked ✅. The failing case (`is_offensive=False, confidence=0.92`) now correctly maps to `prob_offensive=0.08 → SILENT`.
What is missing: Triage section 3 _decide_inner applies confidence thresholds without conditioning on result.is_offensive. For label=non_offensive, confidence=0.92: routes to ALERT_DIRECT (0.92 >= 0.7) instead of SILENT.
Why it matters: Runtime correctness bug. Every confident non-offensive classification would trigger a parent alert.
Recommended resolution: Update triage/design.md section 3 _decide_inner pseudocode to branch on result.is_offensive first. When is_offensive=False: confidence >= borderline_high maps to SILENT. Add test case: label=non_offensive, confidence=0.92 -> SILENT.
Resolution owner: triage/design.md section 3 _decide_inner pseudocode and section 7 test plan
Effort: S (1 hour)

### G-04: Port-naming drift across LLDs
Severity: Important
What is missing: Each LLD has two names for its primary Protocol. Triage: TriageRouter (section 2) vs TriageEngine (section 2.5). Alerts: NotificationService (section 2) vs NotificationChannel (section 2.5). Context agent: ContextAgentProtocol (section 2.1) vs ContextReasoner (section 2.5); TokenManagerProtocol (section 6.4) vs TokenBudgetGuard (section 2.5). The composition root in server section 2.5 and README.md section 4 use the section 2.5 names.
Why it matters: An engineer reads section 2, implements TriageRouter, then tries to register it in main.py which expects TriageEngine -- import error on day 1.
Recommended resolution: Lock the section 2.5 names as canonical. Update section 2 of the four affected LLDs: triage to TriageEngine; alerts to NotificationChannel; context_agent section 2.1 to ContextReasoner; context_agent section 6.4 to TokenBudgetGuard.
Resolution owner: triage section 2, alerts section 2, context_agent sections 2.1 and 6.4
Effort: S (30 minutes)

### G-05: Error model mismatch -- Android ClassificationSource throws vs SDK returns ShomerResult
Severity: Important
What is missing: android_client section 2.5 ClassificationSource interface defines classifyText() returning ClassificationResult directly (no Result wrapper). SDK ShomerApi returns ShomerResult<ClassificationResult>. The SdkClassificationSource adapter must bridge these two but neither the bridging semantics nor the ViewModel error-handling pattern is documented. The contract test for ClassificationSource says it surfaces ShomerError as 'typed exceptions' but the interface has a plain return type.
Why it matters: When the server is unreachable, the ChildClassifyViewModel will either receive an uncaught exception or a silent failure.
Recommended resolution: Document how SdkClassificationSource.classifyText() maps ShomerResult.Failure. Recommended: unwrap and throw a ShomerError subclass (which is a Kotlin Exception). Update android_client section 2.5 SdkClassificationSource to document the unwrap+throw pattern.
Resolution owner: android_client/design.md section 2.5
Effort: S (30 minutes)

### G-06: No PII scrub/redaction step before LLM call
Severity: Important (Blocker if Dr. Segal requires it at Meeting 4)
What is missing: Context_agent section 3.4 build_user_prompt() injects input.current_message and conversation history directly into the LLM prompt without removing phone numbers, @mentions, or names. CA_PRIVACY_MAX_CHARS=500 limits characters but does not scrub PII. Context_agent section 11 Q2 defers this to Meeting 4 confirmation.
Why it matters: PRD section 9 NFR 'no PII in external LLM calls.' Message text can contain embedded phone numbers, usernames, and names.
Recommended resolution: Confirm requirement with Dr. Segal at Meeting 4. If required: define PrivacyScrubber class in context_agent with minimum regex scrubbing (phone numbers, @mentions). Apply before build_user_prompt(). Update context_agent section 3.4 to show the scrub step.
Resolution owner: context_agent/design.md section 3.4
Effort: S (define scrubber + plug into agent.py evaluate())

### G-07: A/B evaluation procedure at Meeting 8 not documented
Severity: Important
What is missing: Server section 11 OQ-S5 flags that the exact procedure for switching between A/B conditions at Meeting 8 needs documentation. No LLD documents the gold-set annotation workflow, the server restart procedure for each condition, which agent_traces rows correspond to which condition, or how to run the evaluation scripts.
Why it matters: Meeting 8 is the primary academic evaluation event. Executing the A/B experiment incorrectly invalidates the ΔFPR measurement.
Recommended resolution: Create a stub docs/design/evaluation_procedure.md. Cover: annotation workflow (double-annotation + disagreement resolution), A/B switching steps, required SQL queries, and McNemar test script location. Expand at Meeting 7.
Resolution owner: New docs/design/evaluation_procedure.md
Effort: S (1-page procedure outline; detail added at Meeting 7)

### G-08: 7-day retention cron has no implementation class or test
Severity: Important
What is missing: Server section 5.1 mentions 'a lifespan() startup task deletes rows older than 7 days' as prose only. No AuditRetentionTask class or function is defined. No test verifies rows older than 7 days are deleted. The existing server/app/audit.py is append-only.
Why it matters: Without retention, the SQLite database grows unboundedly -- a disk usage problem and a privacy violation (PRD section 9 'retention 7 days').
Recommended resolution: Define AuditRetentionTask with a prune() method running DELETE statements on all tables with timestamps older than AUDIT_RETENTION_DAYS. Call from lifespan() step 1 (AuditLog.init()). Add retention assertion to test_audit_completeness.py. Best handled in the new audit_log LLD from G-01.
Resolution owner: audit_log/design.md (new LLD from G-01)
Effort: S

### G-09: Slang Lexicon (SlangDB) has no LLD
Severity: Important
What is missing: C4 diagram shows SlangDB as a first-class component. Server section 3.1 lists slang_db/lexicon.py as a package stub. Context_agent section 9.4 documents the JSON schema and Meeting 6 initial population (~200 entries) but no update path, curation criteria, or version control strategy.
Why it matters: The lookup_slang tool is central to the Context Agent's FP-reduction mechanism. A poorly constructed lexicon undermines the ΔFPR claim.
Recommended resolution: Expand context_agent section 9.4 with: JSON schema fields (meaning, common_use, valence, age_group), initial curation criteria (Meeting 6), update policy (git-committed JSON, no runtime writes), and the exact SlangLexicon.lookup() method signature.
Resolution owner: context_agent/design.md section 9.4 (expanded) or new docs/design/slang_db/design.md
Effort: S (half-day)

### G-10: C4 edge 'Server to ParentSDK push notification HTTPS' oversimplifies FCM path
Severity: Nice-to-have
What is missing: The actual delivery path transits Google's FCM cloud infrastructure (server -> firebase-admin -> FCM cloud -> Android FCM service -> Room -> ViewModel). The alert payload (label, severity, explanation, quote, child_id) passes through Google's FCM servers. No LLD explicitly acknowledges this.
Why it matters: In a thesis defense, Dr. Segal may ask whether alert payloads leave the home network. They do via FCM.
Recommended resolution: Add a note to alerts section 5 or architecture_diagrams.md legend clarifying the FCM hop and confirming this is acceptable under the project's privacy model.
Resolution owner: alerts/design.md section 5 or architecture_diagrams.md legend
Effort: S

### G-11: SDK and server generate separate trace-IDs; no correlated end-to-end tracing
Severity: Nice-to-have
What is missing: SDK sends X-Trace-ID: <sdk-uuid> per request. Gatekeeper mints a NEW uuid4() as its server-side trace_id, ignoring the SDK's header. The two trace-IDs are different values for the same logical request.
Why it matters: Debugging a failed request requires correlating Android logcat (SDK trace_id) with server JSONL (server trace_id). Currently these are unrelated UUIDs.
Recommended resolution: Update gatekeeper section 3.3 TraceIdMiddleware to prefer the inbound X-Trace-ID header from the SDK request (propagate rather than mint new). If header absent, mint new. Follows W3C traceparent propagation model.
Resolution owner: gatekeeper/design.md section 3.3 TraceIdMiddleware
Effort: S

### G-12: /health endpoint does not check OCR, Context Agent reachability, or Gatekeeper health
Severity: Important
What is missing: Server section 9.6 checks classifier, audit_log, and alerts only. It does NOT check Tesseract binary present (OCR), OpenAI/Anthropic API key validity (Context Agent), or Gatekeeper. The OcrBackend and ContextReasoner Protocols do not define a health() method despite README.md section 2 claiming each module exposes health() via its Protocol.
Why it matters: /health returning 'ok' when Tesseract is not installed violates the readiness contract. The parent SDK shows a 'connection OK' banner while /classify-image silently fails.
Recommended resolution: Add async def health() -> ModuleHealthStatus to OcrBackend Protocol (ocr section 2.5) and ContextReasoner Protocol (context_agent section 2.5 Port 1). Implement TesseractOcrBackend.health() as a binary-exists check; LlmContextAgent.health() as an API-key-format check. Update server section 9.6 to call these.
Resolution owner: ocr section 2.5; context_agent section 2.5 Port 1; server section 9.6
Effort: M (2 hours)

### G-13: ServerSettings does not validate all sub-module settings at startup
Severity: Nice-to-have
What is missing: Each module loads its own *Settings independently. A missing OPENAI_API_KEY is discovered on the first CA call, not at startup. Server section 9.1 does not document this intentional design choice.
Why it matters: Low severity for thesis. Fail-fast at startup is preferred for production.
Recommended resolution: Add explicit documentation to server section 9.1 stating that ServerSettings intentionally does not validate sub-module settings (fail-lenient design for MVP). No code change needed.
Resolution owner: server/design.md section 9.1 (documentation addition only)
Effort: S (10 minutes)

### G-14: Gold-set annotation procedure missing; agent_traces missing gold_label column
Severity: Important
What is missing: PRD section 10 KPI 'IAA kappa >= 0.6' has no LLD. The agent_traces table schema (context_agent section 5.1) has no gold_label, gold_annotator, or annotation_ts columns. The evaluation query in context_agent section 7.2 filters WHERE gold_label IS NOT NULL -- this column does not exist in the defined schema.
Why it matters: Without the gold_label column, the Meeting 8 ΔFPR measurement query returns zero rows.
Recommended resolution: Add gold_label TEXT, gold_annotator TEXT, annotation_ts TEXT to agent_traces in context_agent section 5.1 and the new audit_log LLD from G-01. Create stub docs/design/evaluation_procedure.md covering annotation workflow (double-annotation, disagreement resolution, IAA calculation).
Resolution owner: context_agent/design.md section 5.1 (schema change); new evaluation_procedure.md
Effort: S

---

## 6. Pre-existing Open Questions Re-assessed

**Q1 — MoSCoW feature prioritization**
LLD default: android_client section 3.1 includes parent screens (DashboardScreen, HistoryScreen, AlertDetailScreen) as NEW without MoSCoW tags.
Assessment: Child flavor can start immediately. Parent flavor implementation scope is ambiguous without MoSCoW clarity.
Classification: Blocker for parent flavor. Decision needed before Meeting 5.

**Q2 — Confidence threshold (borderline zone 0.3-0.7)**
LLD default: triage section 6 TriageSettings has borderline_low=0.3, borderline_high=0.7, configurable via env.
Assessment: Reasonable default. Empirical tuning at Meeting 8 already planned (triage OQ-T1).
Classification: Defer-to-mid-implementation.

**Q3 — Alert notification format (UX)**
LLD default: alerts section 3 FCM payload schema provides a working default. open_questions.md section 3 provides a template.
Assessment: Sufficient to build the alerts module at Meeting 7. UX refinement deferred.
Classification: Defer-to-mid-implementation.

**Q4 — Conversation history retention / storage**
LLD default: context_agent section 11 Q1 explicitly calls out that read_conversation_history reads from audit.db but the trace table only stores borderline cases. A conversations table storing ALL messages is needed and not yet defined.
Assessment: Schema gap that blocks Meeting 5 Context Agent implementation.
Classification: Blocker. Must be resolved before Meeting 5. See G-01.

**Q5 — Offline scenario**
LLD default: android_client section 8 shows NetworkError -> ChildUiState.Error. Server-side: context_agent section 8 shows frontline-only fallback.
Assessment: Enough to build with. No pending design decision.
Classification: Defer-to-mid-implementation.

**Q6 — Single-child / family account**
LLD default: server section 5.1 uses child_id TEXT (single child). Single-child MVP fully designed.
Assessment: Proceed with single-child default.
Classification: Defer-to-mid-implementation.

**Q7 — Quiet hours / DND**
LLD default: alerts sends all alerts immediately. android_client section 11 Q2 defers to Meeting 7 UX session.
Assessment: No impact on current implementation.
Classification: Defer-to-mid-implementation.

---

## 7. Recommended Actions Before Task Execution Begins

1. Resolve label spelling (G-02). Lock 'non_offensive' (underscore) as canonical. Update PRD section 8.1 and classifier/design.md section 2.2 Category Literal. Output: updated PRD + classifier LLD. Effort: 30 min. Blocks: CLASSIFIER-IF-01, TRIAGE-IF-01.

2. Fix confidence direction in triage router (G-03). Update triage/design.md section 3 _decide_inner to branch on result.is_offensive before applying thresholds. Add test case: label=non_offensive, confidence=0.92 -> SILENT. Output: updated triage section 3 + section 7. Effort: 1 hour. Blocks: TRIAGE-ROUTER-01.

3. Define conversations table + add gold_label to agent_traces (G-01, G-14). Add conversations table schema (conversation_id, role, text, timestamp, child_id) and gold_label column to the audit_log LLD. Output: updated server section 5.1 or new audit_log LLD. Effort: 2 hours. Blocks: CTX-IF-01, any Meeting 5 DB creation task.

4. Canonicalize Protocol names (G-04). Update triage section 2 to TriageEngine; alerts section 2 to NotificationChannel; context_agent section 2.1 to ContextReasoner; context_agent section 6.4 to TokenBudgetGuard. Output: 4 LLD section edits. Effort: 30 min. Blocks: TRIAGE-IF-01, ALERTS-IF-01, CTX-IF-01.

5. Create audit_log/design.md standalone LLD (G-01, G-08). Extract server section 5.1 and context_agent section 5.1 into a new docs/design/audit_log/design.md. Own all 4 tables, retention cron, JSONL sink, and evaluation query API. Output: new LLD file. Effort: 4 hours (M). Blocks: all audit-related Meeting 5 tasks.

6. Resolve privacy scrub requirement with Dr. Segal (G-06). If required: add PrivacyScrubber class to context_agent section 3.4. If not required: add documented justification to context_agent section 11 Q2. Output: updated context_agent section 3.4 or section 11. Effort: 1 hour after Meeting 4 confirmation. Blocks: CTX-IF-01 if scrubber required.

7. Stub evaluation_procedure.md + annotation columns (G-07, G-14). Create 1-page docs/design/evaluation_procedure.md covering annotation workflow, A/B switching, McNemar script location. Add gold_label column to agent_traces schema. Output: new eval procedure doc + schema update. Effort: 2 hours. Blocks: Meeting 8 evaluation (does not block Meeting 5).

8. Add health() to OcrBackend and ContextReasoner Protocols; update /health aggregation (G-12). Implement TesseractOcrBackend.health() as binary-exists check; LlmContextAgent.health() as API-key-format check. Update server section 9.6 to call these. Output: updated ocr section 2.5, context_agent section 2.5, server section 9.6. Effort: 2 hours (M). Does not block Meeting 5 classification tasks.

---

## 8. Confirmed-Ready Scope

The following modules and Phase 1 interface tasks are unblocked and can begin immediately.

**Gatekeeper — all tasks unblocked.**
GATEKEEPER-IF-01 (RateLimitStore, TraceIdGenerator, MetricsEmitter Protocols), CFG-01 (GatekeeperSettings), and all rate-limit, trace-id, size, and timeout implementation and test tasks have no dependency on label spelling or triage confidence direction.

**OCR — all tasks unblocked.**
OCR-IF-01 (OcrBackend Protocol + OcrResult schema) through OCR-CT-01 (contract test). OcrBackend Protocol is independent of label and triage gaps.

**SDK — all tasks unblocked.**
SDK-IF-01 (ShomerApi + ShomerResult sealed hierarchy), SDK-HTTP-01 (ShomerHttpClient with OkHttp + Moshi), SDK-RETRY-01 (RetryInterceptor), SDK-CT-01 (contract test). TraceIdInterceptor (SDK-TRACE-01) can start once G-11 resolution approach is noted in the gatekeeper design.

**Classifier — unblocked after G-02 (30-min fix).**
CLASSIFIER-IF-01 (TextClassifier Protocol + ClassificationResult) and all subsequent tasks can start once the label spelling is locked.

**Triage — unblocked after G-02 + G-03 + G-04 (approximately 90 min total).**
TRIAGE-IF-01 (TriageEngine Protocol + TriageDecision enum), TRIAGE-CFG-01, TRIAGE-ROUTER-01, TRIAGE-SWITCH-01 can all start after the three naming/confidence/label fixes are applied.

**Android Client — Child flavor — unblocked.**
All ChildClassifyViewModel tasks, image compression pipeline (D7 from phase-1.decision.md: longest edge <= 1600px, JPEG quality 80), settings screen, and network security config can begin. MockClassificationSource enables ViewModel unit tests immediately without a running server.

**Server lifespan skeleton — unblocked after G-04 (30-min fix).**
SERVER-LIFESPAN-01 (composition root DI wiring in lifespan()) can be built once Protocol names are canonical across all modules.

**Do NOT start yet (blocked):**
Context Agent tasks: blocked on G-01 (conversations table schema), Q4 (same), and G-06 (privacy scrub decision).
Alerts module: architecturally unblocked, but the FCM payload contract depends on the label spelling fix (G-02).
Parent Dashboard (android_client parent flavor): blocked on Q1 (MoSCoW decision for parent screens).
Any Meeting 8 evaluation scripts: blocked on G-14 (gold_label column missing) and G-07 (evaluation procedure not written).

---

End of review. File location: C:\AIDevelopmentCourse\Shomer.AI\docs\design\review.md
Blocker count: 3. Important count: 7. Nice-to-have count: 5.
