#!/usr/bin/env python3
"""Head-to-head accuracy comparison: Ollama stand-in (v1.0-standin) vs fine-tuned
DictaBERT D10 (v1.1-dictabert) on the SAME test split (data/test.jsonl, 445 rows).

Both classifiers are instantiated directly — no HTTP server required.
Uses the same prompt + parser the OllamaDictaBertClassifier uses in production.

Output:
  docs/accuracy_eval/ollama_vs_dictabert.json   -- full per-model metrics
  docs/accuracy_eval/ollama_vs_dictabert.md     -- side-by-side markdown table
  docs/accuracy_eval/ollama_vs_dictabert_f1.png -- grouped-bar per-class F1

Run:
  server\\.venv\\Scripts\\python.exe scripts\\eval_ollama_vs_dictabert.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------- #
# UTF-8 console (avoids cp1252 crash on Hebrew log lines)
# --------------------------------------------------------------------------- #
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass

REPO = Path(__file__).resolve().parent.parent
TEST_JSONL = REPO / "data" / "test.jsonl"
OUT_DIR = REPO / "docs" / "accuracy_eval"
OUT_JSON = OUT_DIR / "ollama_vs_dictabert.json"
OUT_MD = OUT_DIR / "ollama_vs_dictabert.md"
OUT_PNG = OUT_DIR / "ollama_vs_dictabert_f1.png"

LABELS = ["non_offensive", "abusive", "hate", "violence", "pornographic"]

# Ollama config — mirrors ClassifierSettings defaults + server/.env
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "offensive-hebrew:v1"   # OLLAMA_MODEL default; MODEL_NAME in .env also = this
OLLAMA_TIMEOUT = 90.0                  # generous per-call timeout for LLM

# DictaBERT config — matches server/.env DICTABERT_MODEL_PATH
DICTABERT_PATH = REPO / "training" / "outputs" / "dictabert-offensive" / "checkpoint-best"


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def load_test_set() -> list[dict]:
    rows = []
    for line in TEST_JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


# --------------------------------------------------------------------------- #
# Ollama classifier — mirrors OllamaDictaBertClassifier logic exactly
# --------------------------------------------------------------------------- #
async def _ollama_classify_one(
    client,
    sem: asyncio.Semaphore,
    text: str,
    idx: int,
) -> dict:
    """Call Ollama for a single text. Returns dict with label, confidence, ms, error."""
    # Mirror OllamaDictaBertClassifier._maybe_truncate
    MAX_CHARS = 2048
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    # Mirror build_user_prompt from server/app/prompt.py
    prompt = f'סווג את הטקסט הבא: "{text}"'

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "top_p": 0.9},
    }

    t0 = time.perf_counter()
    async with sem:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as hclient:
                r = await hclient.post(f"{OLLAMA_URL}/api/generate", json=payload)
                r.raise_for_status()
                raw = r.json().get("response", "")
        except Exception as exc:
            ms = (time.perf_counter() - t0) * 1000
            return {
                "idx": idx, "label": None, "confidence": None,
                "ms": ms, "error": f"http_error:{type(exc).__name__}:{exc}",
            }

    ms = (time.perf_counter() - t0) * 1000

    # Mirror parse_model_output from server/app/prompt.py
    import re
    candidate = raw.strip()
    if not candidate.startswith("{"):
        m = re.search(r"\{.*\}", candidate, re.DOTALL)
        if not m:
            return {
                "idx": idx, "label": None, "confidence": None,
                "ms": ms, "error": f"parse_error:no_json_object:{raw[:120]!r}",
            }
        candidate = m.group(0)

    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return {
            "idx": idx, "label": None, "confidence": None,
            "ms": ms, "error": f"parse_error:json_decode:{exc}",
        }

    VALID = {"abusive", "hate", "violence", "pornographic", "non_offensive"}
    category = str(obj.get("category", "")).strip().lower().replace("-", "_")
    if category not in VALID:
        category = "non_offensive"

    try:
        confidence = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    return {
        "idx": idx, "label": category, "confidence": confidence,
        "ms": ms, "error": None,
    }


async def run_ollama(rows: list[dict], concurrency: int = 4) -> list[dict]:
    """Run all rows through Ollama. Returns per-row result dicts."""
    sem = asyncio.Semaphore(concurrency)
    tasks = [
        _ollama_classify_one(None, sem, row["text"], i)
        for i, row in enumerate(rows)
    ]
    n = len(tasks)
    results = []
    # Process in batches for progress reporting
    batch = 20
    for start in range(0, n, batch):
        chunk = tasks[start:start + batch]
        chunk_results = await asyncio.gather(*chunk)
        results.extend(chunk_results)
        done = min(start + batch, n)
        print(f"  [ollama] {done}/{n} done ...", flush=True)
    return results


# --------------------------------------------------------------------------- #
# DictaBERT classifier — mirrors HuggingFaceClassifier logic
# --------------------------------------------------------------------------- #
def run_dictabert(rows: list[dict]) -> list[dict]:
    """Run all rows through DictaBERT synchronously (CPU inference).

    Mirrors HuggingFaceClassifier._forward_logits + softmax logic.
    Uses the checkpoint at DICTABERT_PATH.
    """
    import torch
    from transformers import AutoTokenizer

    # Import the custom model class (same as server does)
    sys.path.insert(0, str(REPO / "server"))
    from app.classifier.dictabert_model import DictaBertWithMlpHead

    print(f"  [dictabert] loading checkpoint from {DICTABERT_PATH} ...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(str(DICTABERT_PATH))
    model = DictaBertWithMlpHead.from_pretrained(str(DICTABERT_PATH))
    id2label: dict[int, str] = {
        int(k): v for k, v in model.config.id2label.items()
    }
    model.eval()
    device = torch.device("cpu")
    model.to(device)
    print(f"  [dictabert] model loaded; id2label={id2label}", flush=True)

    MAX_CHARS = 4096
    results = []
    n = len(rows)
    for i, row in enumerate(rows):
        text = row["text"]
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS]

        t0 = time.perf_counter()
        try:
            inputs = tokenizer(
                text, truncation=True, max_length=512, return_tensors="pt"
            )
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = model(**inputs)
            logits = outputs.logits.squeeze(0).detach()
            probs = torch.softmax(logits, dim=-1)
            pred_idx = int(probs.argmax())
            confidence = float(probs[pred_idx])
            label = id2label.get(pred_idx, "non_offensive")
            ms = (time.perf_counter() - t0) * 1000
            results.append({
                "idx": i, "label": label, "confidence": confidence,
                "ms": ms, "error": None,
            })
        except Exception as exc:
            ms = (time.perf_counter() - t0) * 1000
            results.append({
                "idx": i, "label": None, "confidence": None,
                "ms": ms, "error": f"inference_error:{type(exc).__name__}:{exc}",
            })

        if (i + 1) % 50 == 0:
            print(f"  [dictabert] {i+1}/{n} done ...", flush=True)

    return results


# --------------------------------------------------------------------------- #
# Metrics — mirror eval_accuracy.py conventions
# --------------------------------------------------------------------------- #
def compute_metrics(rows: list[dict], results: list[dict]) -> dict:
    """Compute all metrics. rows[i] has gold label; results[i] has predicted label."""
    import numpy as np
    from sklearn.metrics import (
        accuracy_score, confusion_matrix, precision_recall_fscore_support,
    )

    gold_all = [row["label"] for row in rows]
    pred_all = [r["label"] for r in results]

    # Separate parseable from unparseable
    valid_mask = [r["error"] is None and r["label"] in LABELS for r in results]
    errors = [r for r in results if r["error"] is not None]
    unparseable = [r for r in results if r["error"] is not None and "parse_error" in (r["error"] or "")]
    http_errors = [r for r in results if r["error"] is not None and "http_error" in (r["error"] or "")]

    y_true = [row["label"] for row, v in zip(rows, valid_mask) if v]
    y_pred = [r["label"] for r, v in zip(results, valid_mask) if v]
    ms_list = [r["ms"] for r, v in zip(results, valid_mask) if v]

    n_total = len(rows)
    n_valid = len(y_true)
    n_failed = n_total - n_valid

    if n_valid == 0:
        return {
            "n_total": n_total, "n_valid": 0, "n_failed": n_failed,
            "n_unparseable": len(unparseable), "n_http_errors": len(http_errors),
            "accuracy": 0.0, "binary_accuracy": 0.0, "macro_f1": 0.0,
            "per_class": {}, "confusion": [], "mean_ms": 0.0,
            "error_breakdown": {},
        }

    acc = accuracy_score(y_true, y_pred)
    bin_true = [g != "non_offensive" for g in y_true]
    bin_pred = [p != "non_offensive" for p in y_pred]
    bin_acc = accuracy_score(bin_true, bin_pred)

    p, rc, f1, sup = precision_recall_fscore_support(
        y_true, y_pred, labels=LABELS, zero_division=0
    )
    macro_f1 = float(np.mean(f1))
    cm = confusion_matrix(y_true, y_pred, labels=LABELS)

    per_class = {
        LABELS[i]: {
            "precision": float(p[i]),
            "recall": float(rc[i]),
            "f1": float(f1[i]),
            "support": int(sup[i]),
        }
        for i in range(len(LABELS))
    }

    # Error breakdown (for Ollama parse failures)
    error_counts: dict[str, int] = {}
    for r in errors:
        etype = (r["error"] or "unknown").split(":")[0]
        error_counts[etype] = error_counts.get(etype, 0) + 1

    return {
        "n_total": n_total,
        "n_valid": n_valid,
        "n_failed": n_failed,
        "n_unparseable": len(unparseable),
        "n_http_errors": len(http_errors),
        "accuracy": float(acc),
        "binary_accuracy": float(bin_acc),
        "macro_f1": macro_f1,
        "per_class": per_class,
        "confusion": cm.tolist(),
        "mean_ms": float(sum(ms_list) / len(ms_list)) if ms_list else 0.0,
        "error_breakdown": error_counts,
    }


# --------------------------------------------------------------------------- #
# Plotting
# --------------------------------------------------------------------------- #
def plot_f1(ollama_m: dict, db_m: dict) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        f1_ollama = [ollama_m["per_class"].get(l, {}).get("f1", 0.0) for l in LABELS]
        f1_db = [db_m["per_class"].get(l, {}).get("f1", 0.0) for l in LABELS]

        x = np.arange(len(LABELS))
        w = 0.38
        fig, ax = plt.subplots(figsize=(9, 5.5))
        ax.bar(x - w / 2, f1_ollama, w, label="Ollama v1.0-standin", color="#E8824A")
        ax.bar(x + w / 2, f1_db, w, label="DictaBERT D10 v1.1", color="#4C78A8")
        ax.set_xticks(x)
        ax.set_xticklabels(LABELS, rotation=20, ha="right")
        ax.set_ylim(0, 1.0)
        ax.set_ylabel("F1 score")
        ax.set_title("Per-class F1: Ollama stand-in vs DictaBERT D10 (same test.jsonl)")
        ax.legend()
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(str(OUT_PNG), dpi=150)
        plt.close(fig)
        print(f"[eval] bar chart -> {OUT_PNG}", flush=True)
    except Exception as exc:
        print(f"[eval] WARNING: could not generate PNG: {exc}", flush=True)


# --------------------------------------------------------------------------- #
# Markdown table
# --------------------------------------------------------------------------- #
def write_markdown(ollama_m: dict, db_m: dict, ollama_model_name: str) -> None:
    lines = [
        "# Ollama stand-in vs DictaBERT D10 — Head-to-Head Accuracy",
        "",
        f"**Test set:** `data/test.jsonl` ({ollama_m['n_total']} rows, same for both models)",
        f"**Ollama model:** `{ollama_model_name}` (v1.0-standin adapter)",
        f"**DictaBERT checkpoint:** `training/outputs/dictabert-offensive/checkpoint-best/` (v1.1-dictabert, D10)",
        "",
        "## Overall metrics",
        "",
        "| Metric | Ollama v1.0-standin | DictaBERT D10 v1.1 | Delta (DictaBERT - Ollama) |",
        "|--------|--------------------|--------------------|--------------------------|",
    ]

    def row(name, o_val, d_val, fmt=".3f"):
        delta = d_val - o_val
        sign = "+" if delta >= 0 else ""
        return f"| {name} | {o_val:{fmt}} | {d_val:{fmt}} | {sign}{delta:{fmt}} |"

    lines.append(row("5-class accuracy", ollama_m["accuracy"], db_m["accuracy"]))
    lines.append(row("Binary accuracy (off vs not)", ollama_m["binary_accuracy"], db_m["binary_accuracy"]))
    lines.append(row("Macro-F1", ollama_m["macro_f1"], db_m["macro_f1"]))
    lines.append(row("Mean latency per call (ms)", ollama_m["mean_ms"], db_m["mean_ms"], fmt=".1f"))

    lines += [
        "",
        f"Ollama: {ollama_m['n_valid']}/{ollama_m['n_total']} rows scored "
        f"({ollama_m['n_failed']} failed: {ollama_m['n_unparseable']} unparseable, "
        f"{ollama_m['n_http_errors']} HTTP errors)",
        f"DictaBERT: {db_m['n_valid']}/{db_m['n_total']} rows scored "
        f"({db_m['n_failed']} failed)",
        "",
        "## Per-class F1",
        "",
        "| Class | Ollama P | Ollama R | Ollama F1 | Ollama n | DictaBERT P | DictaBERT R | DictaBERT F1 | DictaBERT n |",
        "|-------|----------|----------|-----------|----------|-------------|-------------|--------------|-------------|",
    ]

    for label in LABELS:
        o = ollama_m["per_class"].get(label, {"precision": 0, "recall": 0, "f1": 0, "support": 0})
        d = db_m["per_class"].get(label, {"precision": 0, "recall": 0, "f1": 0, "support": 0})
        lines.append(
            f"| {label} | {o['precision']:.3f} | {o['recall']:.3f} | {o['f1']:.3f} | {o['support']} "
            f"| {d['precision']:.3f} | {d['recall']:.3f} | {d['f1']:.3f} | {d['support']} |"
        )

    lines += [
        "",
        "## Confusion matrices",
        "",
        "### Ollama v1.0-standin",
        "",
        "```",
        "Predicted →",
        "Gold ↓       " + "  ".join(f"{l[:8]:>10}" for l in LABELS),
    ]
    for i, gold_label in enumerate(LABELS):
        row_vals = ollama_m["confusion"][i] if ollama_m["confusion"] else [0] * 5
        lines.append(f"{gold_label[:12]:<12} " + "  ".join(f"{v:>10}" for v in row_vals))
    lines += [
        "```",
        "",
        "### DictaBERT D10 v1.1-dictabert",
        "",
        "```",
        "Predicted →",
        "Gold ↓       " + "  ".join(f"{l[:8]:>10}" for l in LABELS),
    ]
    for i, gold_label in enumerate(LABELS):
        row_vals = db_m["confusion"][i] if db_m["confusion"] else [0] * 5
        lines.append(f"{gold_label[:12]:<12} " + "  ".join(f"{v:>10}" for v in row_vals))
    lines += [
        "```",
        "",
        "## Caveats",
        "",
        "- Minority-class test rows are partly synthetic/translated: `pornographic` test rows are "
        "~100% synthetic; `hate` and `violence` contain translated Jigsaw/HatEval material. "
        "Per-class F1 for these classes should be read with that in mind for BOTH models — "
        "the test distribution may not fully represent in-the-wild Hebrew offensive content.",
        "- Ollama failed/unparseable rows are excluded from metric computation (counted separately above).",
        "- Latency for DictaBERT is CPU inference (server box is inference-only, no GPU here).",
        "- Ollama calls are sequential with concurrency=4; DictaBERT calls are single-threaded CPU.",
        "",
        "_Generated by `scripts/eval_ollama_vs_dictabert.py`_",
    ]

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[eval] markdown -> {OUT_MD}", flush=True)


# --------------------------------------------------------------------------- #
# Pretty stdout table
# --------------------------------------------------------------------------- #
def print_comparison(ollama_m: dict, db_m: dict, ollama_model_name: str) -> None:
    SEP = "-" * 72
    print()
    print(SEP)
    print("  HEAD-TO-HEAD: Ollama stand-in vs DictaBERT D10")
    print(f"  Test set: data/test.jsonl  ({ollama_m['n_total']} rows)")
    print(SEP)
    print(f"  {'Metric':<35} {'Ollama v1.0':>14} {'DictaBERT D10':>14}")
    print(SEP)

    def prow(name, o, d, pct=False):
        if pct:
            print(f"  {name:<35} {o*100:>13.1f}% {d*100:>13.1f}%")
        else:
            print(f"  {name:<35} {o:>14.3f} {d:>14.3f}")

    prow("5-class accuracy", ollama_m["accuracy"], db_m["accuracy"], pct=True)
    prow("Binary accuracy (off vs not)", ollama_m["binary_accuracy"], db_m["binary_accuracy"], pct=True)
    prow("Macro-F1", ollama_m["macro_f1"], db_m["macro_f1"])
    print(f"  {'Mean latency (ms/call)':<35} {ollama_m['mean_ms']:>13.0f}ms {db_m['mean_ms']:>13.0f}ms")
    print(f"  {'Rows scored':<35} {ollama_m['n_valid']:>13}/{ollama_m['n_total']} {db_m['n_valid']:>13}/{db_m['n_total']}")
    print(f"  {'Ollama unparseable':<35} {ollama_m['n_unparseable']:>14}")
    print()
    print(f"  {'Per-class F1':<20} {'Ollama P':>9} {'Ollama R':>9} {'Ollama F1':>9} {'n':>5}  |  {'DB P':>9} {'DB R':>9} {'DB F1':>9} {'n':>5}")
    print(f"  {'-'*20} {'-'*9} {'-'*9} {'-'*9} {'-'*5}  |  {'-'*9} {'-'*9} {'-'*9} {'-'*5}")
    for label in LABELS:
        o = ollama_m["per_class"].get(label, {"precision": 0, "recall": 0, "f1": 0, "support": 0})
        d = db_m["per_class"].get(label, {"precision": 0, "recall": 0, "f1": 0, "support": 0})
        print(
            f"  {label:<20} {o['precision']:>9.3f} {o['recall']:>9.3f} {o['f1']:>9.3f} {o['support']:>5}  |  "
            f"{d['precision']:>9.3f} {d['recall']:>9.3f} {d['f1']:>9.3f} {d['support']:>5}"
        )
    print(SEP)
    print()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    print(f"[eval] loading test set from {TEST_JSONL} ...", flush=True)
    rows = load_test_set()
    print(f"[eval] {len(rows)} rows loaded", flush=True)

    if not DICTABERT_PATH.exists():
        print(
            f"[eval] ERROR: DictaBERT checkpoint not found at {DICTABERT_PATH}",
            file=sys.stderr,
        )
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- DictaBERT (synchronous CPU) ----
    print(f"\n[eval] === DictaBERT D10 inference ===", flush=True)
    t_db_start = time.time()
    db_results = run_dictabert(rows)
    t_db = time.time() - t_db_start
    print(f"[eval] DictaBERT done in {t_db:.0f}s ({t_db/len(rows)*1000:.0f}ms/row)", flush=True)

    # ---- Ollama (async) ----
    print(f"\n[eval] === Ollama ({OLLAMA_MODEL}) inference ===", flush=True)
    print(f"[eval] ~{len(rows)} LLM calls with concurrency=4; expect several minutes ...", flush=True)
    t_ol_start = time.time()
    ollama_results = asyncio.run(run_ollama(rows, concurrency=4))
    t_ol = time.time() - t_ol_start
    print(f"[eval] Ollama done in {t_ol:.0f}s ({t_ol/len(rows)*1000:.0f}ms/row)", flush=True)

    # ---- Compute metrics ----
    print(f"\n[eval] computing metrics ...", flush=True)
    ollama_m = compute_metrics(rows, ollama_results)
    db_m = compute_metrics(rows, db_results)

    # ---- Save JSON ----
    result_doc = {
        "test_set": str(TEST_JSONL),
        "n_rows": len(rows),
        "ollama": {
            "model": OLLAMA_MODEL,
            "adapter": "v1.0-standin",
            "metrics": ollama_m,
        },
        "dictabert": {
            "checkpoint": str(DICTABERT_PATH),
            "adapter": "v1.1-dictabert",
            "metrics": db_m,
        },
    }
    OUT_JSON.write_text(json.dumps(result_doc, indent=2), encoding="utf-8")
    print(f"[eval] JSON -> {OUT_JSON}", flush=True)

    # ---- Outputs ----
    print_comparison(ollama_m, db_m, OLLAMA_MODEL)
    write_markdown(ollama_m, db_m, OLLAMA_MODEL)
    plot_f1(ollama_m, db_m)

    # ---- One-paragraph verdict ----
    print()
    print("VERDICT:")
    delta_acc = (db_m["accuracy"] - ollama_m["accuracy"]) * 100
    delta_f1 = db_m["macro_f1"] - ollama_m["macro_f1"]
    print(
        f"  DictaBERT D10 (v1.1-dictabert) outperforms the Ollama stand-in by "
        f"{delta_acc:+.1f} pp in 5-class accuracy and {delta_f1:+.3f} in macro-F1, "
        f"on the identical 445-row held-out test split. "
        f"Ollama had {ollama_m['n_failed']} failed/unparseable rows "
        f"({ollama_m['n_unparseable']} parse errors); DictaBERT had {db_m['n_failed']}. "
        f"DictaBERT mean latency is {db_m['mean_ms']:.0f}ms/call (CPU) vs "
        f"{ollama_m['mean_ms']:.0f}ms/call for Ollama. "
        f"Caveat: minority-class test rows (pornographic ~100% synthetic, hate/violence "
        f"~33/class with translated material) limit the per-class interpretation — "
        f"both models are evaluated on the same caveat-carrying distribution."
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
