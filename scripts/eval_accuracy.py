#!/usr/bin/env python3
"""Accuracy evaluation for the Shomer.AI server (baseline + Context-Agent run).

Runs the generated validation data (200 text + 300 image, stratified) through
the live server and measures the CURRENT pipeline's accuracy — no data-input
changes, no DictaBERT training (classifier = Ollama v1.0-standin; image path =
Tesseract OCR -> same classifier).

Two facets:

  * **Classifier accuracy** (predicted category vs gold) — this is independent
    of the Context Agent (the CA never changes the classifier's label).
  * **End-to-end decision** (does the system finally flag the message?). With
    ``--db`` it reads the audit DB and compares the decision BEFORE the CA ran
    (``frontline_only_decision``) vs AFTER (``triage_decision``), and reports
    which samples the Context Agent was actually invoked on (and by which LLM).

Usage (server must be running; for the CA run start it with
CONTEXT_AGENT_ENABLED=true and the LLM keys in server/.env):

    server\\.venv\\Scripts\\python.exe scripts\\eval_accuracy.py \\
        --server http://localhost:8080 --db server/data/audit_eval_ca.db \\
        --out docs/meeting6_accuracy_report.pdf
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass

try:
    import httpx
except ImportError:
    sys.exit("httpx required — use server/.venv python")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    accuracy_score, confusion_matrix, precision_recall_fscore_support,
)

REPO = Path(__file__).resolve().parent.parent
SENTENCES = REPO / "data" / "ocr_validation" / "sentences.jsonl"
OCR_ROWS = REPO / "data" / "ocr_validation" / "ocr_outputs.jsonl"
LABELS = ["non_offensive", "abusive", "hate", "violence", "pornographic"]


def gold_label(category: str) -> str:
    return "non_offensive" if category == "none" else category


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def stratified_sample(rows: list[dict], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(gold_label(r["category"]), []).append(r)
    total = len(rows)
    picked: list[dict] = []
    for cat, items in by_cat.items():
        k = max(1, round(n * len(items) / total))
        rng.shuffle(items)
        picked.extend(items[:k])
    rng.shuffle(picked)
    return picked[:n]


# --------------------------------------------------------------------------- #
# Async drivers. Each request sends a unique X-Trace-Id so audit rows join back.
# --------------------------------------------------------------------------- #
async def classify_text(client, sem, row, idx):
    tid = f"eval-txt-{idx}"
    async with sem:
        t0 = time.perf_counter()
        try:
            r = await client.post("/classify", json={"text": row["text"]},
                                  headers={"X-Trace-Id": tid})
            j = r.json()
            return {"trace_id": tid, "gold": gold_label(row["category"]),
                    "pred": j["category"], "ms": (time.perf_counter()-t0)*1000,
                    "ok": r.status_code == 200}
        except Exception as exc:
            return {"trace_id": tid, "gold": gold_label(row["category"]),
                    "pred": "ERROR", "ms": 0, "ok": False, "error": str(exc)}


async def classify_image(client, sem, row, idx):
    tid = f"eval-img-{idx}"
    img = REPO / row["image_path"].replace("\\", "/")
    gold = gold_label(row["category"])
    if not img.is_file():
        return {"trace_id": tid, "gold": gold, "pred": "MISSING", "ms": 0, "ok": False}
    async with sem:
        t0 = time.perf_counter()
        try:
            with img.open("rb") as fh:
                r = await client.post("/classify-image",
                                      files={"image": (img.name, fh)},
                                      headers={"X-Trace-Id": tid})
            j = r.json()
            return {"trace_id": tid, "gold": gold, "pred": j.get("category", "ERROR"),
                    "ms": (time.perf_counter()-t0)*1000, "ok": r.status_code == 200}
        except Exception as exc:
            return {"trace_id": tid, "gold": gold, "pred": "ERROR", "ms": 0,
                    "ok": False, "error": str(exc)}


async def run_all(server, texts, images, concurrency):
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(base_url=server, timeout=120.0) as client:
        print(f"[eval] {len(texts)} texts ...", flush=True)
        tres = await asyncio.gather(*[classify_text(client, sem, r, i) for i, r in enumerate(texts)])
        print(f"[eval] {len(images)} images ...", flush=True)
        ires = await asyncio.gather(*[classify_image(client, sem, r, i) for i, r in enumerate(images)])
    return list(tres), list(ires)


# --------------------------------------------------------------------------- #
# Audit read-back: triage decisions + Context-Agent involvement per trace.
# --------------------------------------------------------------------------- #
def read_audit(db: Path, results: list[dict]) -> None:
    """Annotate each result in-place with audit fields (triage + CA)."""
    if not db.exists():
        return
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cls = {r["trace_id"]: r for r in con.execute(
        "SELECT trace_id, triage_decision, frontline_only_decision FROM classifications")}
    at = {r["trace_id"]: r for r in con.execute(
        "SELECT trace_id, model_used, is_real_threat FROM agent_traces")}
    con.close()
    for res in results:
        c = cls.get(res["trace_id"])
        res["triage"] = c["triage_decision"] if c else None
        res["frontline"] = c["frontline_only_decision"] if c else None
        a = at.get(res["trace_id"])
        res["ca_involved"] = a is not None
        res["ca_model"] = a["model_used"] if a else None
        res["ca_threat"] = bool(a["is_real_threat"]) if a else None


# --------------------------------------------------------------------------- #
# Metrics.
# --------------------------------------------------------------------------- #
def compute(results):
    valid = [r for r in results if r["ok"] and r["pred"] in LABELS]
    y_true = [r["gold"] for r in valid]
    y_pred = [r["pred"] for r in valid]
    acc = accuracy_score(y_true, y_pred) if valid else 0.0
    bt = [(g != "non_offensive") for g in y_true]
    bp = [(p != "non_offensive") for p in y_pred]
    bin_acc = accuracy_score(bt, bp) if valid else 0.0
    p, rc, f1, sup = precision_recall_fscore_support(y_true, y_pred, labels=LABELS, zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=LABELS)
    return {
        "n_total": len(results), "n_valid": len(valid), "n_failed": len(results)-len(valid),
        "accuracy": acc, "binary_accuracy": bin_acc, "macro_f1": float(np.mean(f1)) if len(f1) else 0.0,
        "per_class": {LABELS[i]: {"precision": float(p[i]), "recall": float(rc[i]),
                                  "f1": float(f1[i]), "support": int(sup[i])} for i in range(len(LABELS))},
        "confusion": cm.tolist(),
        "mean_ms": float(np.mean([r["ms"] for r in valid])) if valid else 0.0,
    }


def _flagged(decision: str | None) -> bool:
    """A decision counts as 'flagged offensive' if it alerts or surfaces for review."""
    return decision in ("alert_direct", "review_needed")


def decision_metrics(results) -> dict:
    """End-to-end binary decision accuracy: frontline-only vs after-CA, vs gold."""
    scored = [r for r in results if r.get("triage") is not None]
    gold = [r["gold"] != "non_offensive" for r in scored]
    front = [_flagged(r.get("frontline")) for r in scored]
    final = [_flagged(r.get("triage")) for r in scored]

    def stats(pred):
        if not scored:
            return {"accuracy": 0, "recall_off": 0, "fpr": 0}
        acc = accuracy_score(gold, pred)
        # recall on offensive
        off = [(g, p) for g, p in zip(gold, pred) if g]
        rec = (sum(1 for g, p in off if p) / len(off)) if off else 0.0
        # false-positive rate on non-offensive
        non = [(g, p) for g, p in zip(gold, pred) if not g]
        fpr = (sum(1 for g, p in non if p) / len(non)) if non else 0.0
        return {"accuracy": acc, "recall_off": rec, "fpr": fpr}

    return {"n_scored": len(scored), "frontline": stats(front), "with_ca": stats(final)}


def ca_involvement(results) -> dict:
    inv = [r for r in results if r.get("ca_involved")]
    return {
        "n_invoked": len(inv),
        "by_model": dict(Counter(r.get("ca_model") for r in inv)),
        "threat_yes": sum(1 for r in inv if r.get("ca_threat") is True),
        "threat_no": sum(1 for r in inv if r.get("ca_threat") is False),
        "on_gold": dict(Counter(r["gold"] for r in inv)),
    }


# --------------------------------------------------------------------------- #
# PDF report.
# --------------------------------------------------------------------------- #
def _text_page(pdf, title, lines):
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.07, 0.96, title, fontsize=15, fontweight="bold", va="top")
    fig.text(0.07, 0.91, "\n".join(lines), fontsize=9, family="monospace", va="top")
    pdf.savefig(fig); plt.close(fig)


def _bar_f1(pdf, tm, im):
    fig, ax = plt.subplots(figsize=(8.27, 5.5))
    x = np.arange(len(LABELS)); w = 0.38
    ax.bar(x-w/2, [tm["per_class"][l]["f1"] for l in LABELS], w, label="text", color="#4C78A8")
    ax.bar(x+w/2, [im["per_class"][l]["f1"] for l in LABELS], w, label="image (OCR)", color="#F58518")
    ax.set_xticks(x); ax.set_xticklabels(LABELS, rotation=20, ha="right")
    ax.set_ylim(0, 1); ax.set_ylabel("F1"); ax.set_title("Per-class F1 — classifier (CA-independent)")
    ax.legend(); ax.grid(axis="y", alpha=0.3); fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def _dist_from_metrics(pdf, title, m):
    """Gold vs predicted label distribution, derived from support + confusion."""
    gold = [m["per_class"][l]["support"] for l in LABELS]      # row totals = gold
    pred = np.array(m["confusion"]).sum(axis=0).tolist()       # col totals = predicted
    fig, ax = plt.subplots(figsize=(8.27, 5.0))
    x = np.arange(len(LABELS)); w = 0.38
    ax.bar(x-w/2, gold, w, label="gold", color="#54A24B")
    ax.bar(x+w/2, pred, w, label="predicted", color="#B279A2")
    ax.set_xticks(x); ax.set_xticklabels(LABELS, rotation=20, ha="right")
    ax.set_ylabel("count"); ax.set_title(title); ax.legend(); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def _decision_bars(pdf, dm_text, dm_image):
    """Grouped bars: frontline vs with-CA, for accuracy/recall/FPR, text & image."""
    fig, axes = plt.subplots(1, 2, figsize=(8.27, 5.0))
    for ax, dm, title in ((axes[0], dm_text, "TEXT"), (axes[1], dm_image, "IMAGE")):
        metrics = ["accuracy", "recall_off", "fpr"]
        x = np.arange(len(metrics)); w = 0.38
        ax.bar(x-w/2, [dm["frontline"][m] for m in metrics], w, label="frontline-only", color="#B0B0B0")
        ax.bar(x+w/2, [dm["with_ca"][m] for m in metrics], w, label="with Context Agent", color="#54A24B")
        ax.set_xticks(x); ax.set_xticklabels(["acc", "recall(off)", "FPR"]); ax.set_ylim(0, 1)
        ax.set_title(f"End-to-end decision — {title}"); ax.grid(axis="y", alpha=0.3)
    axes[0].legend(); fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def _confusion(pdf, title, m):
    cm = np.array(m["confusion"])
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(LABELS))); ax.set_xticklabels(LABELS, rotation=40, ha="right")
    ax.set_yticks(range(len(LABELS))); ax.set_yticklabels(LABELS)
    ax.set_xlabel("predicted"); ax.set_ylabel("gold"); ax.set_title(title)
    for i in range(len(LABELS)):
        for j in range(len(LABELS)):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center",
                    color="white" if cm[i, j] > cm.max()/2 else "black", fontsize=9)
    fig.colorbar(im, fraction=0.046, pad=0.04); fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def _fmt_cls(name, m):
    out = [f"{name}:",
           f"  scored {m['n_valid']}/{m['n_total']} (failed {m['n_failed']})",
           f"  5-class accuracy : {m['accuracy']*100:5.1f} %   binary {m['binary_accuracy']*100:5.1f} %   macroF1 {m['macro_f1']:.3f}",
           "  per-class  P     R     F1    n"]
    for l in LABELS:
        c = m["per_class"][l]
        out.append(f"    {l:<14} {c['precision']:.2f}  {c['recall']:.2f}  {c['f1']:.2f}  {c['support']}")
    return out


def build_pdf(out_pdf, server, model, tm, im, dm_text, dm_image, inv_text, inv_image, baseline):
    with PdfPages(out_pdf) as pdf:
        # Page 1 — classifier accuracy + CA-vs-baseline statement.
        cmp_lines = []
        if baseline:
            cmp_lines = [
                "Comparison to the previous run WITHOUT the real Context Agent:",
                f"  TEXT  5-class accuracy : {baseline['text']['accuracy']*100:.1f} % (no-CA)  ->  {tm['accuracy']*100:.1f} % (with-CA)",
                f"  IMAGE 5-class accuracy : {baseline['image']['accuracy']*100:.1f} % (no-CA)  ->  {im['accuracy']*100:.1f} % (with-CA)",
                "  => the classifier label accuracy is unchanged by the CA (any diff is",
                "     Ollama stand-in run-to-run noise). The CA changes the FINAL DECISION",
                "     on escalated cases only — see the end-to-end decision page.",
                "",
            ]
        _text_page(pdf, "Accuracy — classifier (with real Context Agent enabled)", [
            f"server={server}   classifier={model}   Context Agent: ENABLED (real LLM)",
            "Gold: none->non_offensive; abusive/hate/violence/pornographic identical.",
            "",
            *cmp_lines,
            *_fmt_cls("TEXT  (/classify)", tm),
            "",
            *_fmt_cls("IMAGE (/classify-image)", im),
        ])
        _bar_f1(pdf, tm, im)
        _dist_from_metrics(pdf, "Label distribution — TEXT (gold vs predicted)", tm)
        _dist_from_metrics(pdf, "Label distribution — IMAGE (gold vs predicted)", im)

        # Page — Context Agent involvement + end-to-end decision effect.
        def fmt_inv(name, inv, dm):
            return [
                f"{name}:",
                f"  CA invoked on        : {inv['n_invoked']} samples  (only escalated cases run the CA)",
                f"  by LLM               : {inv['by_model'] or '-'}",
                f"  CA verdict           : real_threat=YES {inv['threat_yes']}, NO {inv['threat_no']}",
                f"  escalated gold labels: {inv['on_gold'] or '-'}",
                f"  end-to-end decision  (n={dm['n_scored']}):",
                f"     frontline-only : acc {dm['frontline']['accuracy']*100:5.1f} %  recall(off) {dm['frontline']['recall_off']*100:5.1f} %  FPR {dm['frontline']['fpr']*100:4.1f} %",
                f"     with CA        : acc {dm['with_ca']['accuracy']*100:5.1f} %  recall(off) {dm['with_ca']['recall_off']*100:5.1f} %  FPR {dm['with_ca']['fpr']*100:4.1f} %",
                f"     delta (CA-front): acc {(dm['with_ca']['accuracy']-dm['frontline']['accuracy'])*100:+5.1f} pp  recall {(dm['with_ca']['recall_off']-dm['frontline']['recall_off'])*100:+5.1f} pp",
                "",
            ]
        _text_page(pdf, "Context Agent — involvement & decision effect", [
            "The Context Agent runs ONLY on escalated cases (violence always escalates;",
            "borderline confidences would too). It does not change the classifier's label;",
            "it resolves escalated cases into ALERT / SILENT / REVIEW. 'flagged' = alert or",
            "review. recall(off)=offensive caught; FPR=non-offensive wrongly flagged.",
            "",
            *fmt_inv("TEXT", inv_text, dm_text),
            *fmt_inv("IMAGE", inv_image, dm_image),
        ])
        _decision_bars(pdf, dm_text, dm_image)
        _confusion(pdf, "Confusion matrix — TEXT (classifier)", tm)
        _confusion(pdf, "Confusion matrix — IMAGE (classifier)", im)
    print(f"[eval] PDF -> {out_pdf}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:8080")
    ap.add_argument("--db", default=None, help="audit DB to read triage + CA involvement from")
    ap.add_argument("--n-text", type=int, default=200)
    ap.add_argument("--n-image", type=int, default=300)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="docs/meeting6_accuracy_report.pdf")
    ap.add_argument("--baseline", default="docs/accuracy_eval/results.json",
                    help="previous no-CA results.json for comparison")
    args = ap.parse_args()

    try:
        model = httpx.get(f"{args.server}/model/info", timeout=5).json().get("model", "?")
    except Exception as exc:
        sys.exit(f"server not reachable at {args.server}: {exc}")

    texts = stratified_sample(load_jsonl(SENTENCES), args.n_text, args.seed)
    images = stratified_sample(load_jsonl(OCR_ROWS), args.n_image, args.seed)
    print(f"[eval] sampled {len(texts)} texts, {len(images)} images  (model={model})", flush=True)

    t0 = time.time()
    tres, ires = asyncio.run(run_all(args.server, texts, images, args.concurrency))
    print(f"[eval] requests done in {time.time()-t0:.0f}s", flush=True)

    if args.db:
        db = Path(args.db)
        read_audit(db, tres); read_audit(db, ires)

    tm, im = compute(tres), compute(ires)
    dm_text, dm_image = decision_metrics(tres), decision_metrics(ires)
    inv_text, inv_image = ca_involvement(tres), ca_involvement(ires)

    baseline = None
    bpath = REPO / args.baseline
    if bpath.exists():
        try:
            baseline = json.loads(bpath.read_text(encoding="utf-8"))
        except Exception:
            baseline = None

    outdir = REPO / "docs" / "accuracy_eval"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "results_with_ca.json").write_text(json.dumps({
        "model": model, "context_agent": "enabled",
        "text": tm, "image": im,
        "decision": {"text": dm_text, "image": dm_image},
        "ca_involvement": {"text": inv_text, "image": inv_image},
    }, indent=2), encoding="utf-8")

    build_pdf(REPO / args.out, args.server, model, tm, im, dm_text, dm_image,
              inv_text, inv_image, baseline)

    print(f"\nTEXT  classifier acc={tm['accuracy']*100:.1f}%  | CA invoked on {inv_text['n_invoked']} "
          f"| decision acc frontline {dm_text['frontline']['accuracy']*100:.1f}% -> with-CA {dm_text['with_ca']['accuracy']*100:.1f}%")
    print(f"IMAGE classifier acc={im['accuracy']*100:.1f}%  | CA invoked on {inv_image['n_invoked']} "
          f"| decision acc frontline {dm_image['frontline']['accuracy']*100:.1f}% -> with-CA {dm_image['with_ca']['accuracy']*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
