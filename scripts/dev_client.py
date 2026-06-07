#!/usr/bin/env python3
"""Shomer.AI dev client — a thin terminal client over the FastAPI server.

This is the Python counterpart of the planned Kotlin ``:sdk-cli`` (SDK-CLI-01/02
in docs/design/sdk/design.md §3.5). It speaks the same wire protocol and shares
the same ``golden_inputs.jsonl`` schema, so the two can later be checked for
output parity (the cross-language contract test, SDK-CT parity).

It is intentionally dependency-light: just ``httpx`` + the stdlib. It does NOT
re-implement any classification logic — every command is a single HTTP call to
a running server.

Usage (server must be running — `uvicorn app.main:app` from server/):
    python scripts/dev_client.py health
    python scripts/dev_client.py info
    python scripts/dev_client.py classify "אתה טמבל מטומטם"
    python scripts/dev_client.py classify-image path/to/screenshot.png
    python scripts/dev_client.py demo
    python scripts/dev_client.py demo --json          # machine-readable

Options common to all commands:
    --server URL    base URL of the server (default: $SHOMER_SERVER or
                    http://localhost:8000)
    --timeout SEC   per-request timeout in seconds (default: 30)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover - clear message beats a stack trace
    sys.exit(
        "httpx is required. Activate the server venv first:\n"
        "    cd server; .\\.venv\\Scripts\\Activate.ps1\n"
        "or: pip install httpx"
    )

# Windows consoles default to cp1252, which cannot encode Hebrew or the status
# glyphs below. Force UTF-8 on the output streams before anything is printed.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
        pass

DEFAULT_SERVER = os.environ.get("SHOMER_SERVER", "http://localhost:8000")
DEFAULT_GOLDEN = Path(__file__).with_name("golden_inputs.jsonl")

# 5 canonical labels — kept in sync with schemas.py Category.
CATEGORY_EN = {
    "abusive": "פוגעני",
    "hate": "שנאה",
    "violence": "אלימות",
    "pornographic": "מיני",
    "non_offensive": "תקין",
}


# --------------------------------------------------------------------------- #
# Terminal helpers (ANSI colour, enabled only on a real TTY).
# --------------------------------------------------------------------------- #
def _enable_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004 on STD_OUTPUT_HANDLE
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            return False
    return True


_COLOR = _enable_ansi()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def red(s: str) -> str:
    return _c(s, "31")


def green(s: str) -> str:
    return _c(s, "32")


def yellow(s: str) -> str:
    return _c(s, "33")


def cyan(s: str) -> str:
    return _c(s, "36")


def dim(s: str) -> str:
    return _c(s, "2")


def bold(s: str) -> str:
    return _c(s, "1")


def _truncate(text: str, n: int = 48) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


# --------------------------------------------------------------------------- #
# HTTP plumbing.
# --------------------------------------------------------------------------- #
def _client(args) -> httpx.Client:
    return httpx.Client(base_url=args.server, timeout=args.timeout)


def _die_unreachable(args, exc: Exception) -> None:
    sys.exit(
        red(f"✗ Could not reach the server at {args.server}\n")
        + dim(f"  {type(exc).__name__}: {exc}\n")
        + dim("  Is it running?  cd server; uvicorn app.main:app --reload")
    )


# --------------------------------------------------------------------------- #
# Commands.
# --------------------------------------------------------------------------- #
def cmd_health(args) -> int:
    try:
        with _client(args) as c:
            r = c.get("/health")
    except httpx.HTTPError as exc:
        _die_unreachable(args, exc)
    body = r.json()
    ok = body.get("status") == "ok"
    badge = green("● OK") if ok else yellow("● DEGRADED")
    print(f"{badge}   model={cyan(body.get('model', '?'))}   "
          f"ollama_reachable={body.get('ollama_reachable')}")
    return 0 if ok else 1


def cmd_info(args) -> int:
    try:
        with _client(args) as c:
            r = c.get("/model/info")
    except httpx.HTTPError as exc:
        _die_unreachable(args, exc)
    body = r.json()
    print(bold("Model:  ") + cyan(body.get("model", "?")))
    if body.get("base"):
        print(bold("Base:   ") + body["base"])
    print(bold("Labels: ") + ", ".join(body.get("labels", [])))
    return 0


def _print_classification(body: dict) -> None:
    offensive = body.get("is_offensive")
    cat = body.get("category", "?")
    cat_he = CATEGORY_EN.get(cat, "")
    conf = body.get("confidence", 0.0)
    flag = red("⚠ OFFENSIVE") if offensive else green("✓ clean")
    label = f"{cat} ({cat_he})" if cat_he else cat
    print(f"  {flag}   {bold(label)}   conf={conf:.2f}   "
          f"{dim(str(body.get('latency_ms', '?')) + 'ms')}   "
          f"{dim('model=' + body.get('model', '?'))}")


def cmd_classify(args) -> int:
    trace_id = args.trace_id or str(uuid.uuid4())
    payload = {"text": args.text}
    if args.child_id:
        payload["child_id"] = args.child_id
    if args.message_id:
        payload["message_id"] = args.message_id
    try:
        with _client(args) as c:
            r = c.post("/classify", json=payload,
                       headers={"X-Trace-Id": trace_id})
    except httpx.HTTPError as exc:
        _die_unreachable(args, exc)
    if r.status_code != 200:
        print(red(f"✗ HTTP {r.status_code}: {r.text}"))
        return 1
    print(dim("  text:     ") + args.text)
    if args.child_id:
        print(dim("  child_id: ") + args.child_id)
    print(dim("  trace_id: ") + trace_id
          + dim(f"   (inspect: inspect_audit.py trace {trace_id})"))
    _print_classification(r.json())
    return 0


def cmd_classify_image(args) -> int:
    path = Path(args.path)
    if not path.is_file():
        sys.exit(red(f"✗ No such file: {path}"))
    trace_id = args.trace_id or str(uuid.uuid4())
    data = {"child_id": args.child_id} if args.child_id else None
    try:
        with _client(args) as c, path.open("rb") as fh:
            r = c.post("/classify-image", files={"image": (path.name, fh)},
                       data=data, headers={"X-Trace-Id": trace_id})
    except httpx.HTTPError as exc:
        _die_unreachable(args, exc)
    if r.status_code != 200:
        print(red(f"✗ HTTP {r.status_code}: {r.text}"))
        return 1
    body = r.json()
    print(dim("  image: ") + str(path.name))
    print(dim("  trace_id: ") + trace_id)
    if body.get("extracted_text"):
        print(dim("  OCR:   ") + _truncate(body["extracted_text"], 60)
              + dim(f"   [backend={body.get('backend')}]"))
    _print_classification(body)
    return 0


def _load_golden(path: Path) -> list[dict]:
    if not path.is_file():
        sys.exit(red(f"✗ Golden set not found: {path}"))
    items = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            sys.exit(red(f"✗ {path}:{line_no} is not valid JSON: {exc}"))
    return items


def cmd_demo(args) -> int:
    golden = _load_golden(Path(args.file))
    results = []
    transport_failures = 0

    try:
        with _client(args) as c:
            for item in golden:
                started = time.perf_counter()
                try:
                    r = c.post("/classify", json={"text": item["text"]})
                    r.raise_for_status()
                    body = r.json()
                    ok = True
                except httpx.HTTPError as exc:
                    if not results and not args.json:
                        _die_unreachable(args, exc)
                    body, ok = {}, False
                    transport_failures += 1
                rtt_ms = int((time.perf_counter() - started) * 1000)

                expected_cat = item.get("expected_category")
                agree = (
                    body.get("category") == expected_cat
                    if (ok and expected_cat is not None)
                    else None
                )
                results.append({
                    "id": item.get("id"),
                    "text": item["text"],
                    "note": item.get("note", ""),
                    "expected_category": expected_cat,
                    "predicted_category": body.get("category") if ok else None,
                    "is_offensive": body.get("is_offensive") if ok else None,
                    "confidence": body.get("confidence") if ok else None,
                    "latency_ms": body.get("latency_ms") if ok else None,
                    "rtt_ms": rtt_ms,
                    "model": body.get("model") if ok else None,
                    "transport_ok": ok,
                    "agrees_with_expected": agree,
                })
    except httpx.HTTPError as exc:
        _die_unreachable(args, exc)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        _render_demo_table(results, args.server)

    # The demo PASSES on transport: every request got a valid 200 response.
    # Label agreement is reported but does NOT gate (the stand-in model is not
    # the trained DictaBERT yet — agreement becomes meaningful post-training).
    return 0 if transport_failures == 0 else 1


def _render_demo_table(results: list[dict], server: str) -> None:
    print()
    print(bold(f"Shomer.AI golden-set demo  ") + dim(f"→ {server}"))
    print(dim("─" * 72))
    # Columns are numeric/ASCII and come BEFORE the Hebrew text, so RTL glyphs
    # at the end of the line don't misalign the leading fields.
    for row in results:
        if not row["transport_ok"]:
            mark = red("✗ NO-RESPONSE")
            print(f"  {row['id']}  {mark}  {dim(_truncate(row['text']))}")
            continue
        off = row["is_offensive"]
        decision = red("OFFENSIVE") if off else green("clean    ")
        cat = (row["predicted_category"] or "?").ljust(13)
        conf = f"{row['confidence']:.2f}" if row["confidence"] is not None else " -- "
        lat = f"{row['latency_ms']}ms".rjust(7)

        agree = row["agrees_with_expected"]
        if agree is True:
            chk = green("✓")
        elif agree is False:
            chk = yellow("≠")
        else:
            chk = dim("·")
        print(f"  {row['id']}  {chk} {decision}  {cyan(cat)}  conf={conf}  "
              f"{dim(lat)}   {row['text']}")

    print(dim("─" * 72))
    n = len(results)
    transport_ok = sum(1 for r in results if r["transport_ok"])
    judged = [r for r in results if r["agrees_with_expected"] is not None]
    agreed = sum(1 for r in judged if r["agrees_with_expected"])
    lats = [r["latency_ms"] for r in results if r["latency_ms"] is not None]
    mean_lat = int(sum(lats) / len(lats)) if lats else 0
    model = next((r["model"] for r in results if r["model"]), "?")

    print(f"  transport : {green(str(transport_ok))}/{n} requests returned 200")
    if judged:
        agree_str = f"{agreed}/{len(judged)}"
        color = green if agreed == len(judged) else yellow
        print(f"  agreement : {color(agree_str)} matched expected_category "
              + dim("(label quality — meaningful once DictaBERT is trained)"))
    print(f"  latency   : mean {mean_lat}ms")
    print(f"  model     : {cyan(model)}")
    print()
    if model and "standin" in str(model):
        print(dim("  Note: serving the v1.0 stand-in. Flip CLASSIFIER_MODEL_VERSION="
                  "v1.1-dictabert in server/.env once the checkpoint lands —"))
        print(dim("        this same command then becomes the accuracy demo."))
        print()


# --------------------------------------------------------------------------- #
# Argument parsing.
# --------------------------------------------------------------------------- #
def cmd_replay(args) -> int:
    """Re-issue the original request for a trace_id; compare stored vs fresh."""
    import sqlite3
    import datetime

    db_path = args.db or os.environ.get("AUDIT_DB_PATH", "server/data/audit.db")
    if not Path(db_path).is_file():
        sys.exit(red(f"✗ Audit DB not found: {db_path}"))

    # --- Read original row from DB (read-only) ---
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT trace_id, input_text, child_id, input_type,
                   classifier_label, classifier_confidence, triage_decision,
                   created_at
            FROM classifications
            WHERE trace_id = ?
            ORDER BY classification_id DESC
            LIMIT 1
            """,
            (args.trace_id,),
        )
        row = cur.fetchone()
        conn.close()
    except sqlite3.OperationalError as exc:
        sys.exit(red(f"✗ DB error: {exc}"))

    if row is None:
        sys.exit(red(f"✗ trace_id not found in DB: {args.trace_id}"))

    original_text = row["input_text"] or ""
    child_id = row["child_id"]
    input_type = row["input_type"] or "text"
    orig_label = row["classifier_label"]
    orig_conf = float(row["classifier_confidence"])
    orig_triage = row["triage_decision"]
    orig_ts = float(row["created_at"])
    orig_time = datetime.datetime.fromtimestamp(orig_ts).strftime("%Y-%m-%d %H:%M:%S")

    print()
    print(bold("Replay") + f"  trace={cyan(args.trace_id)}")
    print(dim("─" * 68))
    print(f"  stored at    : {orig_time}")
    print(f"  input_type   : {input_type}")
    if child_id:
        print(f"  child_id     : {child_id}")
    print(f"  text         : {_truncate(original_text, 60)}")
    print(dim("─" * 68))
    print(f"  original     : {bold(cyan(orig_label))}  conf={orig_conf:.2f}  triage={orig_triage}")

    if input_type != "text":
        print(yellow(f"  ⚠ input_type={input_type!r}; replay only re-classifies OCR-extracted text."))
        print(yellow("    Image bytes are not stored in the audit DB — replaying the text only."))

    if not original_text.strip():
        sys.exit(red("✗ No stored input_text in this row (image with unreadable OCR?). Cannot replay."))

    # --- Re-issue to live server ---
    replay_trace_id = f"{args.trace_id}-replay"
    payload: dict = {"text": original_text}
    if child_id:
        payload["child_id"] = child_id

    try:
        with _client(args) as c:
            r = c.post(
                "/classify",
                json=payload,
                headers={"X-Trace-Id": replay_trace_id},
            )
    except httpx.HTTPError as exc:
        _die_unreachable(args, exc)

    if r.status_code != 200:
        print(red(f"✗ HTTP {r.status_code}: {r.text}"))
        return 1

    body = r.json()
    fresh_label = body.get("category", "?")
    fresh_conf = body.get("confidence", 0.0)
    fresh_off = body.get("is_offensive", False)

    # --- Side-by-side comparison ---
    label_match = fresh_label == orig_label
    conf_delta = abs(fresh_conf - orig_conf)

    chk_label = green("✓ same") if label_match else yellow("≠ changed")
    chk_conf  = green(f"Δ={conf_delta:.3f}") if conf_delta < 0.05 else yellow(f"Δ={conf_delta:.3f}")

    print(f"  replay       : {bold(cyan(fresh_label))}  conf={fresh_conf:.2f}  "
          f"is_offensive={fresh_off}")
    print(dim("─" * 68))
    print(f"  label        : {chk_label}")
    print(f"  confidence   : {chk_conf}")
    print(f"  replay trace : {dim(replay_trace_id)}")
    print()
    return 0 if label_match else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dev_client.py",
        description="Shomer.AI terminal dev client (Python counterpart of :sdk-cli).",
    )
    p.add_argument("--server", default=DEFAULT_SERVER,
                   help=f"server base URL (default: {DEFAULT_SERVER})")
    p.add_argument("--timeout", type=float, default=30.0,
                   help="per-request timeout in seconds (default: 30)")

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="GET /health").set_defaults(func=cmd_health)
    sub.add_parser("info", help="GET /model/info").set_defaults(func=cmd_info)

    sp = sub.add_parser("classify", help="POST /classify with Hebrew text")
    sp.add_argument("text", help="the Hebrew text to classify")
    sp.add_argument("--child-id", default=None,
                    help="optional child_id → persists a conversation turn + per-child alert bucket")
    sp.add_argument("--message-id", default=None,
                    help="optional message_id (alert idempotency)")
    sp.add_argument("--trace-id", default=None,
                    help="X-Trace-Id to send (default: fresh uuid4); echoed for inspect/replay")
    sp.set_defaults(func=cmd_classify)

    sp = sub.add_parser("classify-image", help="POST /classify-image with a file")
    sp.add_argument("path", help="path to the image file")
    sp.add_argument("--child-id", default=None, help="optional child_id (form field)")
    sp.add_argument("--trace-id", default=None,
                    help="X-Trace-Id to send (default: fresh uuid4); echoed for inspect/replay")
    sp.set_defaults(func=cmd_classify_image)

    sp = sub.add_parser("demo", help="run the curated Hebrew golden set")
    sp.add_argument("--file", default=str(DEFAULT_GOLDEN),
                    help=f"golden-set JSONL (default: {DEFAULT_GOLDEN.name})")
    sp.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON instead of a table")
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser(
        "replay",
        help="re-issue the original request for a trace_id and compare",
    )
    sp.add_argument("trace_id", help="the X-Trace-Id / trace_id to replay")
    sp.add_argument(
        "--db",
        default=None,
        help="path to the audit DB (default: AUDIT_DB_PATH env or server/data/audit.db)",
    )
    sp.set_defaults(func=cmd_replay)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
