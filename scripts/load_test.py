#!/usr/bin/env python3
"""Shomer.AI load tester — concurrent /classify driver with latency + accuracy report.

Sends every input from the golden JSONL (or a custom file) to POST /classify at
bounded concurrency, optionally repeating each input R times. Sends a unique
X-Trace-Id per request so results can be joined back to the audit DB.

Usage:
    python scripts/load_test.py                             # defaults
    python scripts/load_test.py --concurrency 5 --repeat 3
    python scripts/load_test.py --server http://10.0.2.2:8000 --out report.md
    python scripts/load_test.py --inputs scripts/golden_inputs.jsonl

Options:
    --server URL        base URL (default: $SHOMER_SERVER or http://localhost:8000)
    --inputs PATH       golden-set JSONL (default: scripts/golden_inputs.jsonl)
    --concurrency N     max parallel requests (default: 4)
    --repeat N          how many times to send each input (default: 1)
    --db PATH           audit DB for triage histogram join (default: AUDIT_DB_PATH
                        env var or server/data/audit.db)
    --out PATH          write Markdown report to this path
                        (default: docs/loadtest_report.md)
    --timeout SEC       per-request timeout in seconds (default: 30)
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any

# Windows consoles default to cp1252 — force UTF-8 on both streams.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

try:
    import httpx
except ImportError:
    sys.exit(
        "httpx is required. Activate the server venv first:\n"
        "    cd server; .\\.venv\\Scripts\\Activate.ps1\n"
        "or: pip install httpx"
    )

DEFAULT_SERVER  = os.environ.get("SHOMER_SERVER", "http://localhost:8000")
DEFAULT_GOLDEN  = Path(__file__).with_name("golden_inputs.jsonl")
DEFAULT_DB      = os.environ.get("AUDIT_DB_PATH", "server/data/audit.db")
DEFAULT_OUT     = "docs/loadtest_report.md"


# --------------------------------------------------------------------------- #
# Data loading.
# --------------------------------------------------------------------------- #


def _load_golden(path: Path) -> list[dict]:
    if not path.is_file():
        sys.exit(f"ERROR: golden-set file not found: {path}")
    items = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            sys.exit(f"ERROR: {path}:{line_no} is not valid JSON: {exc}")
    return items


# --------------------------------------------------------------------------- #
# Async driver.
# --------------------------------------------------------------------------- #


async def _send_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    item: dict,
    trace_id: str,
    timeout: float,
) -> dict[str, Any]:
    """Send one /classify request; return a result dict."""
    payload = {"text": item["text"]}
    t0 = time.perf_counter()
    async with sem:
        try:
            r = await client.post(
                "/classify",
                json=payload,
                headers={"X-Trace-Id": trace_id},
                timeout=timeout,
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                body = r.json()
                return {
                    "trace_id": trace_id,
                    "id": item.get("id"),
                    "text": item["text"],
                    "expected_category": item.get("expected_category"),
                    "predicted_category": body.get("category"),
                    "is_offensive": body.get("is_offensive"),
                    "confidence": body.get("confidence"),
                    "latency_ms": latency_ms,
                    "http_status": r.status_code,
                    "ok": True,
                    "error": None,
                }
            else:
                return {
                    "trace_id": trace_id,
                    "id": item.get("id"),
                    "text": item["text"],
                    "expected_category": item.get("expected_category"),
                    "predicted_category": None,
                    "is_offensive": None,
                    "confidence": None,
                    "latency_ms": latency_ms,
                    "http_status": r.status_code,
                    "ok": False,
                    "error": f"HTTP {r.status_code}",
                }
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            return {
                "trace_id": trace_id,
                "id": item.get("id"),
                "text": item["text"],
                "expected_category": item.get("expected_category"),
                "predicted_category": None,
                "is_offensive": None,
                "confidence": None,
                "latency_ms": latency_ms,
                "http_status": None,
                "ok": False,
                "error": str(exc),
            }


async def _run(
    server: str,
    items: list[dict],
    concurrency: int,
    repeat: int,
    timeout: float,
) -> list[dict[str, Any]]:
    """Drive all requests; return results in completion order."""
    sem = asyncio.Semaphore(concurrency)
    tasks = []

    async with httpx.AsyncClient(base_url=server) as client:
        for _rep in range(repeat):
            for item in items:
                tid = str(uuid.uuid4())
                tasks.append(_send_one(client, sem, item, tid, timeout))

        results = await asyncio.gather(*tasks, return_exceptions=False)

    return list(results)


# --------------------------------------------------------------------------- #
# Percentile computation.
# --------------------------------------------------------------------------- #


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = (len(sorted_v) - 1) * p / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_v) - 1)
    frac = idx - lo
    return sorted_v[lo] + frac * (sorted_v[hi] - sorted_v[lo])


# --------------------------------------------------------------------------- #
# Audit DB join for triage histogram.
# --------------------------------------------------------------------------- #


def _triage_histogram(db_path: str, trace_ids: list[str]) -> dict[str, int]:
    """Query the audit DB for triage_decision counts matching our trace_ids."""
    if not trace_ids or not Path(db_path).is_file():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" * len(trace_ids))
        rows = conn.execute(
            f"""
            SELECT triage_decision, COUNT(*) as n
            FROM classifications
            WHERE trace_id IN ({placeholders})
            GROUP BY triage_decision
            ORDER BY n DESC
            """,
            trace_ids,
        ).fetchall()
        conn.close()
        return {r["triage_decision"]: r["n"] for r in rows}
    except sqlite3.OperationalError:
        return {}


# --------------------------------------------------------------------------- #
# Report generator.
# --------------------------------------------------------------------------- #


def _build_report(
    results: list[dict],
    args_server: str,
    args_inputs: str,
    args_concurrency: int,
    args_repeat: int,
    db_path: str,
    started_at: str,
    duration_s: float,
) -> str:
    total = len(results)
    ok_results = [r for r in results if r["ok"]]
    err_results = [r for r in results if not r["ok"]]
    error_rate = 100.0 * len(err_results) / total if total else 0.0

    latencies = [r["latency_ms"] for r in ok_results if r["latency_ms"] is not None]
    p50  = _percentile(latencies, 50)
    p95  = _percentile(latencies, 95)
    p99  = _percentile(latencies, 99)
    pmax = max(latencies) if latencies else 0.0

    # Category histogram.
    cat_hist: dict[str, int] = {}
    for r in ok_results:
        cat = r["predicted_category"] or "?"
        cat_hist[cat] = cat_hist.get(cat, 0) + 1

    # Accuracy check vs expected_category.
    judged = [r for r in ok_results if r.get("expected_category") is not None]
    correct = [r for r in judged if r["predicted_category"] == r["expected_category"]]

    # Triage histogram from DB.
    trace_ids = [r["trace_id"] for r in ok_results]
    triage_hist = _triage_histogram(db_path, trace_ids)

    lines = [
        "# Shomer.AI Load Test Report",
        "",
        f"**Date:** {started_at}",
        f"**Server:** {args_server}",
        f"**Input file:** {args_inputs}",
        f"**Concurrency:** {args_concurrency}",
        f"**Repeat:** {args_repeat}",
        f"**Total requests:** {total}",
        f"**Wall time:** {duration_s:.1f} s",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Total requests | {total} |",
        f"| Successful (200) | {len(ok_results)} |",
        f"| Errors | {len(err_results)} ({error_rate:.1f}%) |",
        f"| Latency p50 (ms) | {p50:.1f} |",
        f"| Latency p95 (ms) | {p95:.1f} |",
        f"| Latency p99 (ms) | {p99:.1f} |",
        f"| Latency max (ms) | {pmax:.1f} |",
        f"| Throughput (req/s) | {total / duration_s:.1f} |",
    ]

    if judged:
        acc = 100.0 * len(correct) / len(judged) if judged else 0.0
        lines += [
            f"| Accuracy vs golden | {len(correct)}/{len(judged)} ({acc:.0f}%) |",
        ]

    lines += ["", "## Category histogram", "", "| Category | Count | % |", "|---|---|---|"]
    for cat, n in sorted(cat_hist.items(), key=lambda x: -x[1]):
        pct = 100.0 * n / len(ok_results) if ok_results else 0
        lines.append(f"| `{cat}` | {n} | {pct:.1f}% |")

    if triage_hist:
        lines += ["", "## Triage-decision histogram (from audit DB)", "",
                  "| Triage decision | Count | % |", "|---|---|---|"]
        db_total = sum(triage_hist.values())
        for td, n in sorted(triage_hist.items(), key=lambda x: -x[1]):
            pct = 100.0 * n / db_total if db_total else 0
            lines.append(f"| `{td}` | {n} | {pct:.1f}% |")
    else:
        lines += ["",
                  "## Triage-decision histogram",
                  "",
                  "_Audit DB not found or no matching rows — start the server with "
                  "AUDIT_DB_PATH configured to enable this section._"]

    if judged:
        lines += [
            "",
            "## Per-input accuracy",
            "",
            "| ID | Expected | Predicted | Match |",
            "|---|---|---|---|",
        ]
        seen: set[str] = set()
        for r in judged:
            key = f"{r['id']}-{r['expected_category']}"
            if key in seen:
                continue
            seen.add(key)
            match_str = "✓" if r["predicted_category"] == r["expected_category"] else "≠"
            lines.append(
                f"| {r['id']} | `{r['expected_category']}` "
                f"| `{r['predicted_category'] or '?'}` | {match_str} |"
            )

    if err_results:
        lines += ["", "## Errors", "", "| Trace | Error |", "|---|---|"]
        for r in err_results[:20]:  # cap at 20
            lines.append(f"| `{r['trace_id'][:12]}…` | {r['error']} |")
        if len(err_results) > 20:
            lines.append(f"| … | {len(err_results) - 20} more errors omitted |")

    lines += [
        "",
        "---",
        "_Generated by `scripts/load_test.py`_",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Entry point.
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="load_test.py",
        description="Shomer.AI concurrent load tester with latency + accuracy report.",
    )
    p.add_argument("--server", default=DEFAULT_SERVER,
                   help=f"server base URL (default: {DEFAULT_SERVER})")
    p.add_argument("--inputs", default=str(DEFAULT_GOLDEN),
                   help=f"golden-set JSONL (default: {DEFAULT_GOLDEN.name})")
    p.add_argument("--concurrency", type=int, default=4,
                   help="max parallel requests (default: 4)")
    p.add_argument("--repeat", type=int, default=1,
                   help="times to send each input (default: 1)")
    p.add_argument("--db", default=DEFAULT_DB,
                   help=f"audit DB path for triage join (default: {DEFAULT_DB})")
    p.add_argument("--out", default=DEFAULT_OUT,
                   help=f"output Markdown report path (default: {DEFAULT_OUT})")
    p.add_argument("--timeout", type=float, default=30.0,
                   help="per-request timeout in seconds (default: 30)")
    args = p.parse_args(argv)

    items = _load_golden(Path(args.inputs))
    total_planned = len(items) * args.repeat

    started_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[load_test] server={args.server}  inputs={len(items)}"
          f"  repeat={args.repeat}  concurrency={args.concurrency}"
          f"  planned={total_planned}")

    t0 = time.perf_counter()
    results = asyncio.run(_run(
        args.server, items, args.concurrency, args.repeat, args.timeout
    ))
    duration_s = time.perf_counter() - t0

    ok = sum(1 for r in results if r["ok"])
    errors = len(results) - ok

    report = _build_report(
        results,
        args.server,
        args.inputs,
        args.concurrency,
        args.repeat,
        args.db,
        started_at,
        duration_s,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    # One-line summary to stdout.
    error_rate = 100.0 * errors / len(results) if results else 0
    latencies = [r["latency_ms"] for r in results if r["ok"] and r["latency_ms"]]
    p95 = _percentile(latencies, 95) if latencies else 0.0
    throughput = len(results) / duration_s if duration_s > 0 else 0

    print(
        f"[load_test] DONE  {ok}/{len(results)} OK  "
        f"error_rate={error_rate:.1f}%  "
        f"p95={p95:.0f}ms  "
        f"throughput={throughput:.1f}req/s  "
        f"report→{args.out}"
    )

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
