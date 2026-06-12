#!/usr/bin/env python3
"""Context -> False-Positive paired experiment runner.

Answers the headline research question:
    Does adding conversational context to Hebrew bullying classification reduce
    the false-positive rate, vs. classifying the message in isolation — without
    hurting recall?

It runs the gold set through BOTH A/B levels (see
plan-docs/decisions/context-fp-experiment.decision.md):

  * F2 — prompt-level (SCIENTIFIC PRIMARY): the same LLM judge sees the same
    message + classifier result; the ONLY difference is the conversation-history
    block (empty vs. populated). Isolates context as the sole variable.
  * F1 — product-level (DEPLOYMENT VALIDATION): the real triage decision with
    context_agent_enabled = False vs. True (escalated borderline items get the
    judge with history).

The design is PAIRED (every gold item scored by both arms), so significance is
tested with McNemar (exact binomial for small discordant counts). Metrics are
sliced by the 3 gold categories (A repairs-FP / B reveals-TP / C controls).

Usage (from REPO ROOT):

    server\\.venv\\Scripts\\python.exe scripts\\eval_context_fp.py \\
        --gold data/gold/context_eval_seed.jsonl \\
        --out-md docs/research_question/context_fp_results.md \\
        --out-json docs/research_question/context_fp_results.json

Requirements:
  * LLM keys in server/.env (GEMINI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY)
    + CONTEXT_AGENT_ENABLED=true — otherwise the judge is the MockLlmClient and
    the CA arms are meaningless (the script warns loudly).
  * A working classifier per CLASSIFIER_MODEL_VERSION in server/.env
    (v1.0-standin needs Ollama running; v1.1-dictabert needs the checkpoint).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# --- stdout UTF-8 (Hebrew rationales) --------------------------------------- #
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "server"

# Pre-registered defaults (decision D-CFP-3). CLI can override k only.
X_MIN_FPR_DROP_PP = 10.0   # success threshold (percentage points)
Y_MAX_RECALL_LOSS_PP = 3.0  # non-inferiority margin (percentage points)
ALPHA = 0.05


# --------------------------------------------------------------------------- #
# Bootstrap: env + import path                                                 #
# --------------------------------------------------------------------------- #
def _load_env_file(path: Path) -> None:
    """Load server/.env into os.environ WITHOUT clobbering already-set vars.

    pydantic-settings' ``env_file='.env'`` is resolved relative to CWD, which is
    the repo root here — not server/. So we load server/.env ourselves.
    """
    if not path.exists():
        print(f"[warn] {path} not found — relying on process environment only")
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _bootstrap() -> None:
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))
    _load_env_file(SERVER_DIR / ".env")


# --------------------------------------------------------------------------- #
# Gold item                                                                    #
# --------------------------------------------------------------------------- #
@dataclass
class GoldItem:
    id: str
    category: str          # A_context_repairs_fp | B_context_reveals_tp | C_control_*
    subtype: str
    history: list[dict]    # [{"role":..., "text":...}, ...] oldest→newest
    message: str
    gold_is_offensive: bool
    gold_label: str
    isolated_appearance: str  # how it reads with NO context

    @property
    def cat(self) -> str:
        """Coarse category bucket: 'A' | 'B' | 'C'."""
        return self.category[0].upper()


def load_gold(path: Path, limit: int | None) -> list[GoldItem]:
    items: list[GoldItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        items.append(
            GoldItem(
                id=d["id"],
                category=d["category"],
                subtype=d.get("subtype", ""),
                history=d.get("history", []),
                message=d["message"],
                gold_is_offensive=bool(d["gold_is_offensive"]),
                gold_label=d.get("gold_label", ""),
                isolated_appearance=d.get("isolated_appearance", ""),
            )
        )
    if limit:
        items = items[:limit]
    return items


# --------------------------------------------------------------------------- #
# Per-item scoring result                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class ItemScore:
    item: GoldItem
    label: str = ""
    confidence: float = 0.0
    # final binary "did the system flag it?" per arm/level
    f2_blind: bool = False   # prompt-level, history empty
    f2_aware: bool = False   # prompt-level, history populated
    f1_blind: bool = False   # product, CONTEXT_AGENT_ENABLED=false
    f1_aware: bool = False   # product, CONTEXT_AGENT_ENABLED=true
    notes: str = ""


# --------------------------------------------------------------------------- #
# The LLM judge (prompt-level context toggle)                                  #
# --------------------------------------------------------------------------- #
async def judge_is_threat(client, build_system, build_user, parse, cr, message, history) -> bool:
    """Run the context-agent LLM judge and return is_real_threat (bool).

    history=[] -> context-blind judge; history=turns -> context-aware judge.
    On any failure, safe-default to True (never silently drop a threat).
    """
    try:
        system_prompt = build_system()
        user_prompt = build_user(
            text=message,
            classifier_result=cr,
            conversation_history=history,
            slang_hits={},
            age_info={"sensitivity_level": "moderate"},
            child_age=13,
        )
        res = await client.reason(system_prompt, user_prompt, max_tokens=512, temperature=0.2)
        parsed, ok = parse(res["text"])
        return bool(parsed.is_real_threat)
    except Exception as exc:  # noqa: BLE001
        print(f"  [judge error] {exc} -> safe-default True")
        return True


# --------------------------------------------------------------------------- #
# McNemar (paired) + helpers                                                   #
# --------------------------------------------------------------------------- #
def mcnemar_exact_p(b: int, c: int) -> float:
    """Two-sided exact-binomial McNemar p-value over discordant pairs (b, c)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) * (0.5 ** n)
    return min(1.0, 2.0 * tail)


def paired_table(scores: list[ItemScore], blind_attr: str, aware_attr: str,
                 want_flag: bool, subset) -> dict:
    """Build a paired 2x2 over ``subset`` items.

    want_flag=False (benign items): 'correct' = NOT flagged. b/c count FP flips.
    want_flag=True  (offensive items): 'correct' = flagged. b/c count miss flips.
    """
    a = b = c = d = 0  # a=both correct, b=blind correct/aware wrong, c=blind wrong/aware correct, d=both wrong
    for s in scores:
        if not subset(s):
            continue
        blind_flag = getattr(s, blind_attr)
        aware_flag = getattr(s, aware_attr)
        blind_ok = (blind_flag == want_flag)
        aware_ok = (aware_flag == want_flag)
        if blind_ok and aware_ok:
            a += 1
        elif blind_ok and not aware_ok:
            b += 1
        elif not blind_ok and aware_ok:
            c += 1
        else:
            d += 1
    n = a + b + c + d
    return {"a": a, "b": b, "c": c, "d": d, "n": n,
            "p": mcnemar_exact_p(b, c)}


def rate(scores, attr, want_flag, subset) -> tuple[float, int, int]:
    """Return (rate, hits, total) where rate = fraction with flag==want_flag."""
    hits = total = 0
    for s in scores:
        if not subset(s):
            continue
        total += 1
        if getattr(s, attr) == want_flag:
            hits += 1
    return (hits / total if total else 0.0, hits, total)


# --------------------------------------------------------------------------- #
# Metrics block for one A/B level (F1 or F2)                                   #
# --------------------------------------------------------------------------- #
def compute_level(scores: list[ItemScore], blind_attr: str, aware_attr: str) -> dict:
    benign = lambda s: not s.item.gold_is_offensive
    offensive = lambda s: s.item.gold_is_offensive

    # FPR: among benign items, fraction flagged (flag=True is the error).
    fpr_blind, fp_blind, n_benign = rate(scores, blind_attr, True, benign)
    fpr_aware, fp_aware, _ = rate(scores, aware_attr, True, benign)
    fpr_table = paired_table(scores, blind_attr, aware_attr, want_flag=False, subset=benign)

    # Recall: among offensive items, fraction flagged (flag=True is correct).
    rec_blind, tp_blind, n_off = rate(scores, blind_attr, True, offensive)
    rec_aware, tp_aware, _ = rate(scores, aware_attr, True, offensive)
    rec_table = paired_table(scores, blind_attr, aware_attr, want_flag=True, subset=offensive)

    delta_fpr_pp = (fpr_blind - fpr_aware) * 100.0
    delta_recall_pp = (rec_aware - rec_blind) * 100.0

    # Per-category ΔFPR (benign items only) and per-category recall (offensive only).
    cat_fpr = {}
    cat_recall = {}
    for cat in ("A", "B", "C"):
        in_cat = lambda s, _c=cat: s.item.cat == _c
        fb, _, nb = rate(scores, blind_attr, True, lambda s, _c=cat: benign(s) and s.item.cat == _c)
        fa, _, _ = rate(scores, aware_attr, True, lambda s, _c=cat: benign(s) and s.item.cat == _c)
        if nb:
            cat_fpr[cat] = {"blind": fb, "aware": fa, "delta_pp": (fb - fa) * 100.0, "n": nb}
        rb, _, no = rate(scores, blind_attr, True, lambda s, _c=cat: offensive(s) and s.item.cat == _c)
        ra, _, _ = rate(scores, aware_attr, True, lambda s, _c=cat: offensive(s) and s.item.cat == _c)
        if no:
            cat_recall[cat] = {"blind": rb, "aware": ra, "delta_pp": (ra - rb) * 100.0, "n": no}

    # Verdicts vs pre-registered thresholds.
    h1_pass = (delta_fpr_pp >= X_MIN_FPR_DROP_PP) and (fpr_table["p"] < ALPHA)
    recall_non_inferior = (-delta_recall_pp) <= Y_MAX_RECALL_LOSS_PP  # loss <= Y

    return {
        "n_benign": n_benign, "n_offensive": n_off,
        "fpr_blind": fpr_blind, "fpr_aware": fpr_aware, "delta_fpr_pp": delta_fpr_pp,
        "fpr_mcnemar": fpr_table,
        "recall_blind": rec_blind, "recall_aware": rec_aware, "delta_recall_pp": delta_recall_pp,
        "recall_mcnemar": rec_table,
        "cat_fpr": cat_fpr, "cat_recall": cat_recall,
        "h1_fpr_pass": h1_pass, "recall_non_inferior": recall_non_inferior,
    }


# --------------------------------------------------------------------------- #
# Report rendering                                                             #
# --------------------------------------------------------------------------- #
def _fmt_level(name: str, primary: bool, m: dict) -> str:
    tag = " (SCIENTIFIC PRIMARY)" if primary else " (deployment validation)"
    fp = m["fpr_mcnemar"]
    rc = m["recall_mcnemar"]
    lines = [
        f"### {name}{tag}",
        "",
        f"- Benign items: {m['n_benign']} · Offensive items: {m['n_offensive']}",
        "",
        "| Metric | context-blind | context-aware | Δ | McNemar p |",
        "|---|---|---|---|---|",
        f"| **FPR** | {m['fpr_blind']*100:.1f}% | {m['fpr_aware']*100:.1f}% | "
        f"**−{m['delta_fpr_pp']:.1f} pp** | {fp['p']:.4f} |",
        f"| **Recall** | {m['recall_blind']*100:.1f}% | {m['recall_aware']*100:.1f}% | "
        f"{m['delta_recall_pp']:+.1f} pp | {rc['p']:.4f} |",
        "",
        f"- FPR discordant pairs: blind-wrong/aware-right (the win) **c={fp['c']}**, "
        f"blind-right/aware-wrong (the cost) **b={fp['b']}**",
        f"- Recall discordant pairs: c={rc['c']} (aware recovers), b={rc['b']} (aware misses)",
        "",
        f"- **H1 (ΔFPR ≥ {X_MIN_FPR_DROP_PP:.0f}pp & p<{ALPHA}):** "
        f"{'✅ PASS' if m['h1_fpr_pass'] else '❌ not met'}",
        f"- **Recall non-inferiority (loss ≤ {Y_MAX_RECALL_LOSS_PP:.0f}pp):** "
        f"{'✅ PASS' if m['recall_non_inferior'] else '❌ FAIL'}",
        "",
        "**ΔFPR by category** (proves H2 — the drop should concentrate in A):",
        "",
        "| Cat | n (benign) | FPR blind | FPR aware | Δ |",
        "|---|---|---|---|---|",
    ]
    cat_names = {"A": "A repairs-FP", "B": "B reveals-TP", "C": "C control"}
    for cat in ("A", "B", "C"):
        if cat in m["cat_fpr"]:
            cf = m["cat_fpr"][cat]
            lines.append(
                f"| {cat_names[cat]} | {cf['n']} | {cf['blind']*100:.1f}% | "
                f"{cf['aware']*100:.1f}% | −{cf['delta_pp']:.1f} pp |"
            )
    lines.append("")
    lines.append("**Recall by category** (proves the recall guard — B must stay high):")
    lines.append("")
    lines.append("| Cat | n (offensive) | Recall blind | Recall aware | Δ |")
    lines.append("|---|---|---|---|---|")
    for cat in ("A", "B", "C"):
        if cat in m["cat_recall"]:
            cr = m["cat_recall"][cat]
            lines.append(
                f"| {cat_names[cat]} | {cr['n']} | {cr['blind']*100:.1f}% | "
                f"{cr['aware']*100:.1f}% | {cr['delta_pp']:+.1f} pp |"
            )
    lines.append("")
    return "\n".join(lines)


def render_report(scores, f2, f1, meta) -> str:
    out = [
        "# Context → False-Positive experiment — results",
        "",
        f"**Run:** {meta['timestamp']} · **gold:** `{meta['gold']}` "
        f"({meta['n_items']} items) · **k:** {meta['k']} turns",
        f"**Classifier:** `{meta['model_version']}` · **LLM judge:** "
        f"`{meta['llm_primary']}` (fallback `{meta['llm_fallback']}`)",
        "",
        f"Pre-registered (decision D-CFP-3): X≥{X_MIN_FPR_DROP_PP:.0f}pp FPR drop, "
        f"Y≤{Y_MAX_RECALL_LOSS_PP:.0f}pp recall loss, α={ALPHA}, McNemar exact.",
        "",
    ]
    if meta["mock_warning"]:
        out += [
            "> ⚠️ **WARNING — LLM judge is the MockLlmClient (no API keys).** The CA "
            "arms are canned (always not-threat); these numbers are NOT valid. Set "
            "GEMINI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY in `server/.env` and "
            "`CONTEXT_AGENT_ENABLED=true`, then re-run.",
            "",
        ]
    out.append("---\n")
    out.append(_fmt_level("F2 — prompt-level (history empty vs. populated)", True, f2))
    out.append("\n---\n")
    out.append(_fmt_level("F1 — product-level (CONTEXT_AGENT_ENABLED false vs. true)", False, f1))
    out.append("\n---\n")
    out.append("## Headline sentence (fill into thesis)")
    out.append("")
    out.append(
        f"> On {f2['n_benign']} benign + {f2['n_offensive']} offensive Hebrew "
        f"conversational items, adding ≤{meta['k']} turns of context reduced the "
        f"false-positive rate from {f2['fpr_blind']*100:.1f}% to {f2['fpr_aware']*100:.1f}% "
        f"(−{f2['delta_fpr_pp']:.1f} pp, McNemar p={f2['fpr_mcnemar']['p']:.4f}), while "
        f"recall changed by {f2['delta_recall_pp']:+.1f} pp "
        f"({'non-inferior' if f2['recall_non_inferior'] else 'INFERIOR'} at "
        f"Y={Y_MAX_RECALL_LOSS_PP:.0f}pp)."
    )
    out.append("")
    out.append("## Per-item dump")
    out.append("")
    out.append("| id | cat | gold | isolated | F2 blind→aware | F1 blind→aware |")
    out.append("|---|---|---|---|---|---|")
    f = lambda b: "🚩" if b else "·"
    for s in scores:
        g = "OFF" if s.item.gold_is_offensive else "ben"
        out.append(
            f"| {s.item.id} | {s.item.cat} | {g} | {s.item.isolated_appearance[:4]} | "
            f"{f(s.f2_blind)}→{f(s.f2_aware)} | {f(s.f1_blind)}→{f(s.f1_aware)} |"
        )
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #
async def run(args) -> int:
    _bootstrap()

    # Imports (after sys.path bootstrap).
    from app.main import _build_classifier, _build_llm_clients
    from app.context_agent.settings import ContextAgentSettings
    from app.context_agent.prompt import build_system_prompt, build_user_prompt
    from app.context_agent.output_parser import parse_llm_output
    from app.classifier.settings import ClassifierSettings
    from app.triage.settings import TriageSettings
    from app.triage.threshold_engine import ThresholdTriageEngine
    from app.schemas import TriageDecision

    gold_path = REPO_ROOT / args.gold
    items = load_gold(gold_path, args.limit)
    print(f"Loaded {len(items)} gold items from {gold_path}")

    classifier = _build_classifier()
    ca_settings = ContextAgentSettings()
    primary, fallback = _build_llm_clients(ca_settings)
    mock_warning = getattr(primary, "model_name", "") == "mock"
    if mock_warning:
        print("\n[!!] LLM judge = MockLlmClient — CA arms will be MEANINGLESS. "
              "Set keys in server/.env + CONTEXT_AGENT_ENABLED=true.\n")

    triage = ThresholdTriageEngine(TriageSettings())
    k = args.k

    scores: list[ItemScore] = []
    for i, item in enumerate(items, 1):
        cr = await classifier.classify(item.message)
        s = ItemScore(item=item, label=cr.label, confidence=cr.confidence)

        hist = item.history[-k:] if k else []

        # --- F2 prompt-level: judge with empty vs populated history ---------- #
        s.f2_blind = await judge_is_threat(
            primary, build_system_prompt, build_user_prompt, parse_llm_output, cr, item.message, [])
        s.f2_aware = await judge_is_threat(
            primary, build_system_prompt, build_user_prompt, parse_llm_output, cr, item.message, hist)

        # --- F1 product-level: triage decision per arm ---------------------- #
        d_blind = triage.decide(cr, context_agent_enabled=False)
        s.f1_blind = d_blind in (TriageDecision.ALERT_DIRECT, TriageDecision.REVIEW_NEEDED)

        d_aware = triage.decide(cr, context_agent_enabled=True)
        if d_aware == TriageDecision.SILENT:
            s.f1_aware = False
        elif d_aware == TriageDecision.ALERT_DIRECT:
            s.f1_aware = True
        elif d_aware == TriageDecision.REVIEW_NEEDED:
            s.f1_aware = True
        else:  # ESCALATE_TO_CA → reuse the F2-aware judge verdict (same prompt)
            s.f1_aware = s.f2_aware

        scores.append(s)
        print(f"[{i}/{len(items)}] {item.id} {item.cat} {cr.label}({cr.confidence:.2f}) "
              f"F2 {s.f2_blind}->{s.f2_aware} | F1 {s.f1_blind}->{s.f1_aware}")

    f2 = compute_level(scores, "f2_blind", "f2_aware")
    f1 = compute_level(scores, "f1_blind", "f1_aware")

    meta = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gold": str(args.gold), "n_items": len(items), "k": k,
        "model_version": ClassifierSettings().model_version,
        "llm_primary": getattr(primary, "model_name", "?"),
        "llm_fallback": getattr(fallback, "model_name", "?"),
        "mock_warning": mock_warning,
    }

    report = render_report(scores, f2, f1, meta)
    out_md = REPO_ROOT / args.out_md
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(report, encoding="utf-8")
    print(f"\nReport → {out_md}")

    out_json = REPO_ROOT / args.out_json
    out_json.write_text(json.dumps({"meta": meta, "f2": f2, "f1": f1}, ensure_ascii=False,
                                   indent=2, default=str), encoding="utf-8")
    print(f"JSON   → {out_json}")

    # Console summary.
    print("\n=== F2 (prompt-level, primary) ===")
    print(f"FPR  {f2['fpr_blind']*100:.1f}% → {f2['fpr_aware']*100:.1f}%  "
          f"(−{f2['delta_fpr_pp']:.1f}pp, p={f2['fpr_mcnemar']['p']:.4f})  "
          f"H1 {'PASS' if f2['h1_fpr_pass'] else 'no'}")
    print(f"Rec  {f2['recall_blind']*100:.1f}% → {f2['recall_aware']*100:.1f}%  "
          f"({f2['delta_recall_pp']:+.1f}pp)  "
          f"non-inferior {'PASS' if f2['recall_non_inferior'] else 'FAIL'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Context→FP paired experiment runner")
    ap.add_argument("--gold", default="data/gold/context_eval_seed.jsonl")
    ap.add_argument("--out-md", default="docs/research_question/context_fp_results.md")
    ap.add_argument("--out-json", default="docs/research_question/context_fp_results.json")
    ap.add_argument("--k", type=int, default=5, help="context window (prior turns)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
