# Context Agent Module

**Purpose:** LLM-driven contextual reasoning over borderline classifications.
This is the academic contribution of the Shomer.AI thesis — it answers Research
Question RQ3: does adding conversational context reduce the false-positive rate?

---

## Three Ports (swappable without touching server code)

| Port | Protocol | Default adapter | Swap to |
|---|---|---|---|
| Whole-module | `ContextReasoner` | `LlmContextAgent` | `RuleBasedReasoner` |
| LLM provider | `LlmClient` | `OpenAiClient` (GPT-4o-mini) | `AnthropicClient`, `MockLlmClient` |
| Budget guard | `TokenBudgetGuard` | `SqliteTokenManager` | `InMemoryTokenManager` |

---

## Environment Variables

| Variable | Default | Secret? | Description |
|---|---|---|---|
| `CONTEXT_AGENT_ENABLED` | `true` | No | A/B switch (false = context-blind baseline) |
| `OPENAI_API_KEY` | — | **YES** | GPT-4o-mini API key |
| `ANTHROPIC_API_KEY` | — | **YES** | Haiku 4.5 API key |
| `CONTEXT_AGENT_PRIMARY_LLM` | `gpt-4o-mini` | No | Primary model string |
| `CONTEXT_AGENT_FALLBACK_LLM` | `haiku-4.5` | No | Fallback model string |
| `CONTEXT_AGENT_TIMEOUT_S` | `5.0` | No | Hard LLM timeout per PRD §8.3 |
| `CONTEXT_AGENT_MAX_HISTORY_TURNS` | `5` | No | Conversation turns to fetch |
| `CONTEXT_AGENT_AUDIT_DB` | `server/audit.db` | No | SQLite path (shared with audit_log) |
| `SLANG_LEXICON_PATH` | `server/data/slang_lexicon.json` | No | Hebrew slang lexicon |
| `TOKEN_PRICES_PATH` | `server/app/context_agent/token_prices.yaml` | No | LLM pricing table |
| `CONTEXT_AGENT_DAILY_TOKEN_BUDGET` | `100000` | No | Max tokens/day |
| `CONTEXT_AGENT_DAILY_USD_BUDGET` | `0.50` | No | Max USD/day |

**Secrets management:** Never commit API keys. Keep them in `server/.env` (gitignored).

---

## Switching the LLM Provider

```python
# server/app/main.py — one-line swap
from .context_agent.clients.openai_client import OpenAiClient
from .context_agent.clients.anthropic_client import AnthropicClient
from .context_agent.clients.mock_client import MockLlmClient

# Default:
primary = OpenAiClient(settings.openai_api_key.get_secret_value())
# Swap to Haiku:
# primary = AnthropicClient(settings.anthropic_api_key.get_secret_value())
# Tests / dev without API keys:
# primary = MockLlmClient()
```

---

## Mock vs Real in Tests

All tests under `server/tests/context_agent/` use `MockLlmClient` +
`InMemoryTokenManager` + `FakeAuditStore` — no API keys, no network calls,
fully deterministic.

To run tests:
```bash
cd server
../.venv/Scripts/python.exe -m pytest tests/context_agent/ -v
```

---

## TokenManager SQLite Schema

Table: `token_usage` in `server/audit.db`

```sql
CREATE TABLE IF NOT EXISTS token_usage (
    day            TEXT    NOT NULL,
    model          TEXT    NOT NULL,
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    usd_spent      REAL    NOT NULL DEFAULT 0.0,
    PRIMARY KEY (day, model)
)
```

Budgets reset automatically at UTC midnight (based on the `day` column).

Cost math example:
- GPT-4o-mini: 380 input + 42 output tokens
- Cost = (380 × $0.15/1M) + (42 × $0.60/1M) = $0.0000570 + $0.0000252 = **$0.0000822**

Verify prices in `token_prices.yaml` before Meeting 8 — mark `[למקור]` entries.

---

## A/B Experiment (Meeting 8 ΔFPR Measurement)

The `ContextDecision` returned by `evaluate()` always carries:
- `review_flag=True` when any failure occurred (human review queued)
- `model_used` — which LLM was actually used (or `None`)

The audit log module stores both the frontline result and the context-aware
decision on every call. At Meeting 8, compute ΔFPR from the `agent_traces`
table:

```sql
-- Meeting 8 A/B evaluation query
SELECT
    classifier_label AS frontline,
    is_real_threat    AS ca_decision,
    gold_label
FROM agent_traces
WHERE gold_label IS NOT NULL;
-- Then compute FPR for each column and subtract: ΔFPR = frontline_FPR - ca_FPR
```

Target: ΔFPR ≥ 15 percentage points, p < 0.05 (McNemar's test).

---

## Safety Invariant

**The Context Agent NEVER silently suppresses an alert.**

Every failure path either:
1. Returns `ContextDecision(review_flag=True)` — human review queued.
2. Preserves the frontline `is_offensive` as `is_real_threat` — alert may still fire.

This is enforced in `_fallback_decision()` in `agent.py` and in `parse_llm_output()`
in `output_parser.py` (default `is_real_threat=True` on parse failure).
