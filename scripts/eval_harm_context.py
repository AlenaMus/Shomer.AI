#!/usr/bin/env python3
"""Harm-context reframe evaluation: does conversational context help decide
whether a message is part of a HARMFUL SITUATION worth alerting a parent?

Difference from eval_context_fp.py:
  * Target variable = ``alert_worthy`` (harmful context), NOT ``gold_is_offensive``.
  * The Context-Agent prompt is BROADENED: "is this part of a harmful situation
    requiring an alert?" (covers abuse/hate/exclusion/coercion, not only violence),
    and explicitly NOT-alert on banter / one-off jabs / friendly sarcasm.
  * Routes EVERY item through the judge with history empty (blind) vs populated
    (aware) -- so context's full effect on the harm decision is measured.

It also re-scores the SAME decisions against the OLD target (``offensive_content``,
i.e. "alarm on every offensive message") to show the reframe converts apparent
recall-loss into false-positive reduction.

Run from REPO ROOT (needs GEMINI/ANTHROPIC key + server/.env):
    server\\.venv\\Scripts\\python.exe scripts\\eval_harm_context.py
"""
from __future__ import annotations
import argparse, asyncio, json, math, sys, time
from collections import Counter
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try: _s.reconfigure(encoding="utf-8")
        except Exception: pass

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "server"

HARM_SYSTEM = """\
אתה עוזר לזיהוי מצבי פגיעה (בריונות, הטרדה, איום) בעברית עבור מערכת התראות להורים.
תפקידך: בהינתן הודעה אחת בתוך הקשר שיחה, להחליט האם זהו מצב פוגעני שמצדיק התראה להורה — או תוכן שאינו דורש התראה.

עקרון מפתח: לא כל הודעה עם מילה גסה מצדיקה התראה. בריונות מתאפיינת ב*דפוס* פגיעה: חזרתיות, הסלמה, איום ממשי,
סחיטה מינית, החרמה מתואמת, חשיפת פרטים אישיים, או פגיעה ממוקדת בקורבן במצוקה / ביחסי כוח לא-שוויוניים.

סמן התראה (is_real_threat=true) רק אם ההודעה היא חלק ממצב פוגעני כזה בהקשר.
אל תסמן (is_real_threat=false) עבור: הקנטות הדדיות בין חברים, עלבון חד-פעמי בלי דפוס, סרקזם ידידותי, סלנג חיבה,
או שיחה תמימה — גם אם המילים נשמעות גסות מחוץ להקשר. בדוק תמיד את כל ההיסטוריה.

החזר JSON תקין בלבד:
{
  "is_real_threat": true | false,
  "severity": "none" | "low" | "medium" | "high",
  "explanation": "משפט הסבר אחד בעברית להורה",
  "reasoning": "נימוק קצר"
}\
"""

GROUPS = ["harmful", "veiled_harmful", "offensive_not_harmful", "benign"]


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    import os
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def mcnemar_p(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return min(1.0, 2.0 * tail)


async def judge(client, build_user, parse, cr, message, history) -> bool:
    """Return the harm-judge alert decision (is_real_threat). Safe-default True on error."""
    try:
        user = build_user(text=message, classifier_result=cr, conversation_history=history,
                          slang_hits={}, age_info={"sensitivity_level": "moderate"}, child_age=13)
        res = await client.reason(HARM_SYSTEM, user, max_tokens=512, temperature=0.2)
        parsed, _ = parse(res["text"])
        return bool(parsed.is_real_threat)
    except Exception as exc:  # noqa: BLE001
        print(f"  [judge error] {exc} -> default True")
        return True


def rate(scores, attr, want, subset):
    hit = tot = 0
    for s in scores:
        if not subset(s):
            continue
        tot += 1
        hit += (s[attr] == want)
    return (hit / tot if tot else 0.0, hit, tot)


def paired(scores, blind, aware, want, subset):
    b = c = 0
    for s in scores:
        if not subset(s):
            continue
        bk = (s[blind] == want)
        ak = (s[aware] == want)
        if bk and not ak:
            b += 1
        elif not bk and ak:
            c += 1
    return b, c, mcnemar_p(b, c)


def metrics_for_target(scores, truth):
    """FPR + recall (blind vs aware) when scoring against ``truth`` (bool attr)."""
    neg = lambda s: not s[truth]   # items that should NOT alert
    pos = lambda s: s[truth]       # items that SHOULD alert
    fpr_b, *_ = rate(scores, "blind", True, neg)
    fpr_a, *_ = rate(scores, "aware", True, neg)
    rec_b, *_ = rate(scores, "blind", True, pos)
    rec_a, *_ = rate(scores, "aware", True, pos)
    fb, fc, fp = paired(scores, "blind", "aware", False, neg)  # FP fixed/added
    rb, rc, rp = paired(scores, "blind", "aware", True, pos)   # recall flips
    return {"fpr_blind": fpr_b, "fpr_aware": fpr_a, "fpr_delta_pp": (fpr_b - fpr_a) * 100,
            "fpr_b": fb, "fpr_c": fc, "fpr_p": fp,
            "rec_blind": rec_b, "rec_aware": rec_a, "rec_delta_pp": (rec_a - rec_b) * 100,
            "rec_b": rb, "rec_c": rc, "rec_p": rp,
            "n_neg": sum(neg(s) for s in scores), "n_pos": sum(pos(s) for s in scores)}


async def run(args) -> int:
    sys.path.insert(0, str(SERVER_DIR))
    _load_env(SERVER_DIR / ".env")
    from app.main import _build_classifier, _build_llm_clients
    from app.context_agent.settings import ContextAgentSettings
    from app.context_agent.prompt import build_user_prompt
    from app.context_agent.output_parser import parse_llm_output

    items = [json.loads(l) for l in (REPO_ROOT / args.gold).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        items = items[:args.limit]
    print(f"Loaded {len(items)} items from {args.gold}")

    classifier = _build_classifier()
    primary, _ = _build_llm_clients(ContextAgentSettings())
    if getattr(primary, "model_name", "") == "mock":
        print("[!!] LLM judge = MOCK — set GEMINI/ANTHROPIC key + CONTEXT_AGENT_ENABLED=true"); return 1

    scores = []
    for i, it in enumerate(items, 1):
        cr = await classifier.classify(it["message"])
        hist = it.get("history", [])[-args.k:] if args.k else []
        blind = await judge(primary, build_user_prompt, parse_llm_output, cr, it["message"], [])
        aware = await judge(primary, build_user_prompt, parse_llm_output, cr, it["message"], hist)
        scores.append({"id": it["id"], "group": it["group"], "subtype": it.get("subtype", ""),
                       "alert_worthy": bool(it["alert_worthy"]),
                       "offensive_content": bool(it["offensive_content"]),
                       "blind": blind, "aware": aware})
        if i % 10 == 0 or i == len(items):
            print(f"  [{i}/{len(items)}] {it['id']}")

    harm = metrics_for_target(scores, "alert_worthy")        # NEW target
    offv = metrics_for_target(scores, "offensive_content")   # OLD target

    # per-group alert counts + success (vs alert_worthy)
    pg = {g: {"n": 0, "alert_b": 0, "alert_a": 0, "ok_b": 0, "ok_a": 0} for g in GROUPS}
    for s in scores:
        d = pg[s["group"]]; d["n"] += 1
        d["alert_b"] += s["blind"]; d["alert_a"] += s["aware"]
        d["ok_b"] += (s["blind"] == s["alert_worthy"]); d["ok_a"] += (s["aware"] == s["alert_worthy"])

    meta = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "gold": args.gold, "n": len(items),
            "k": args.k, "llm": getattr(primary, "model_name", "?"),
            "n_alert_worthy": sum(s["alert_worthy"] for s in scores)}
    out = {"meta": meta, "harm_target": harm, "offensive_target": offv,
           "per_group": pg, "scores": scores}
    (REPO_ROOT / args.out_json).parent.mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / args.out_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON -> {args.out_json}")

    print("\n=== HARM target (alarm on harmful context) ===")
    print(f"FPR  {harm['fpr_blind']*100:5.1f}% -> {harm['fpr_aware']*100:5.1f}%  "
          f"(-{harm['fpr_delta_pp']:.1f}pp, fixed={harm['fpr_c']} added={harm['fpr_b']}, p={harm['fpr_p']:.4f})")
    print(f"Rec  {harm['rec_blind']*100:5.1f}% -> {harm['rec_aware']*100:5.1f}%  ({harm['rec_delta_pp']:+.1f}pp)")
    print("=== OLD target (alarm on every offensive message) — for contrast ===")
    print(f"FPR  {offv['fpr_blind']*100:5.1f}% -> {offv['fpr_aware']*100:5.1f}%  (-{offv['fpr_delta_pp']:.1f}pp)")
    print(f"Rec  {offv['rec_blind']*100:5.1f}% -> {offv['rec_aware']*100:5.1f}%  ({offv['rec_delta_pp']:+.1f}pp)")
    print("\nper-group (vs alert_worthy):")
    for g in GROUPS:
        d = pg[g]
        if d["n"]:
            print(f"  {g:22s} n={d['n']:2d}  alerts {d['alert_b']:2d}->{d['alert_a']:2d}  "
                  f"success {d['ok_b']/d['n']*100:.0f}%->{d['ok_a']/d['n']*100:.0f}%")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="data/gold/context_harm_v2.jsonl")
    ap.add_argument("--out-json", default="docs/research_question/harm_context_results.json")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--limit", type=int, default=None)
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
