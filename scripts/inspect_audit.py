#!/usr/bin/env python3
"""Shomer.AI audit-log inspector — read-only SQLite browser.

Opens the audit DB in read-only mode (uri=True, mode=ro) and prints
structured, human-readable output to the terminal. NEVER writes to the DB.

Usage:
    python scripts/inspect_audit.py recent            # last 20 classifications
    python scripts/inspect_audit.py recent --limit 50
    python scripts/inspect_audit.py trace <trace_id>  # full picture for one trace
    python scripts/inspect_audit.py child <child_id>  # conversation + decisions
    python scripts/inspect_audit.py alerts            # recent alert dispositions
    python scripts/inspect_audit.py stats             # aggregate counts

Options:
    --db PATH   path to the audit DB
                (default: AUDIT_DB_PATH env var → server/data/audit.db)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

# Windows consoles default to cp1252, which cannot encode Hebrew.
# Force UTF-8 on both output streams before printing anything.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

DEFAULT_DB = os.environ.get("AUDIT_DB_PATH", "server/data/audit.db")


# --------------------------------------------------------------------------- #
# Terminal helpers (ANSI colour — only on a real TTY).
# --------------------------------------------------------------------------- #


def _enable_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            return False
    return True


_COLOR = _enable_ansi()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def red(s: str) -> str:      return _c(s, "31")
def green(s: str) -> str:    return _c(s, "32")
def yellow(s: str) -> str:   return _c(s, "33")
def cyan(s: str) -> str:     return _c(s, "36")
def dim(s: str) -> str:      return _c(s, "2")
def bold(s: str) -> str:     return _c(s, "1")


def _trunc(text: str | None, n: int = 48) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _ts(epoch: float | None) -> str:
    """Format an epoch float as a human-readable timestamp."""
    if epoch is None:
        return "—"
    return datetime.datetime.fromtimestamp(float(epoch)).strftime("%Y-%m-%d %H:%M:%S")


def _triage_color(td: str | None) -> str:
    td = td or "?"
    if td == "silent":
        return green(td)
    if td == "alert_direct":
        return red(td)
    if td == "escalate_to_ca":
        return yellow(td)
    if td == "review_needed":
        return yellow(td)
    return td


# --------------------------------------------------------------------------- #
# DB connection helper.
# --------------------------------------------------------------------------- #


def _open_ro(db_path: str) -> sqlite3.Connection:
    """Open the DB read-only; exit with a friendly message on failure."""
    if not Path(db_path).is_file():
        sys.exit(
            red(f"✗ Audit DB not found: {db_path}\n")
            + dim("  Set AUDIT_DB_PATH or pass --db PATH.\n")
            + dim("  Run the integration test or the server first to create data.")
        )
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as exc:
        sys.exit(red(f"✗ Cannot open DB: {exc}"))


# --------------------------------------------------------------------------- #
# Subcommands.
# --------------------------------------------------------------------------- #


def cmd_recent(args) -> int:
    """Last N classifications: id, time, label, confidence, triage, child, text."""
    limit = args.limit
    conn = _open_ro(args.db)
    try:
        rows = conn.execute(
            """
            SELECT classification_id, created_at, classifier_label,
                   classifier_confidence, triage_decision, child_id, input_text
            FROM classifications
            ORDER BY classification_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print(dim("  (no classifications in DB)"))
        return 0

    print()
    print(bold(f"Recent classifications") + dim(f"  [{args.db}]"))
    print(dim("─" * 80))
    # Columns: id | time | label | conf | triage | child | text
    hdr = (f"  {'ID':>5}  {'Time':19}  {'Label':14}  {'Conf':5}  "
           f"{'Triage':14}  {'Child':10}  Text")
    print(bold(hdr))
    print(dim("─" * 80))
    for r in reversed(rows):  # show oldest-first in the window
        cid   = str(r["classification_id"]).rjust(5)
        ts    = _ts(r["created_at"])
        label = (r["classifier_label"] or "?").ljust(14)
        conf  = f"{float(r['classifier_confidence']):.2f}"
        td    = _triage_color((r["triage_decision"] or "?").ljust(14))
        child = _trunc(r["child_id"] or "", 10).ljust(10)
        text  = _trunc(r["input_text"] or "", 40)
        print(f"  {cid}  {dim(ts)}  {cyan(label)}  {conf}  {td}  {child}  {text}")
    print(dim("─" * 80))
    print(dim(f"  {len(rows)} row(s)  (newest first in display; showing up to {limit})"))
    print()
    return 0


def cmd_trace(args) -> int:
    """Full picture for one trace: classification + agent_traces + alerts."""
    trace_id = args.trace_id
    conn = _open_ro(args.db)
    try:
        cls_rows = conn.execute(
            """
            SELECT classification_id, trace_id, created_at,
                   input_text, classifier_label, classifier_confidence,
                   is_offensive, classifier_model_version, triage_decision,
                   context_agent_enabled, frontline_only_decision,
                   child_id, message_id, input_type,
                   ocr_extracted_text, image_hash, gold_label, alert_id
            FROM classifications
            WHERE trace_id = ?
            ORDER BY classification_id ASC
            """,
            (trace_id,),
        ).fetchall()

        at_rows = conn.execute(
            """
            SELECT agent_trace_id, model_used, tools_called_json,
                   is_real_threat, severity, explanation, review_flag,
                   tokens_input, tokens_output, cost_usd, latency_ms, created_at
            FROM agent_traces
            WHERE trace_id = ?
            ORDER BY agent_trace_id ASC
            """,
            (trace_id,),
        ).fetchall()

        alert_rows = conn.execute(
            """
            SELECT alert_id, child_id, label, severity,
                   fcm_status, explanation, quote_snippet, created_at
            FROM alerts
            WHERE trace_id = ?
            ORDER BY id ASC
            """,
            (trace_id,),
        ).fetchall()
    finally:
        conn.close()

    if not cls_rows:
        print(red(f"✗ trace_id not found: {trace_id}"))
        return 1

    print()
    print(bold(f"Trace  ") + cyan(trace_id))
    print(dim("─" * 72))

    for r in cls_rows:
        print(bold("Classification"))
        print(f"  classification_id : {r['classification_id']}")
        print(f"  created_at        : {_ts(r['created_at'])}")
        print(f"  input_type        : {r['input_type']}")
        if r["child_id"]:
            print(f"  child_id          : {r['child_id']}")
        if r["message_id"]:
            print(f"  message_id        : {r['message_id']}")
        print(f"  input_text        : {_trunc(r['input_text'] or '', 72)}")
        if r["ocr_extracted_text"]:
            print(f"  ocr_text          : {_trunc(r['ocr_extracted_text'], 72)}")
        if r["image_hash"]:
            print(f"  image_hash        : {r['image_hash']}")
        label_str = cyan(r["classifier_label"] or "?")
        print(f"  label             : {label_str}  conf={float(r['classifier_confidence']):.3f}"
              f"  is_offensive={bool(r['is_offensive'])}")
        print(f"  model             : {dim(r['classifier_model_version'] or '?')}")
        print(f"  triage_decision   : {_triage_color(r['triage_decision'])}")
        print(f"  frontline_only    : {r['frontline_only_decision'] or '—'}")
        print(f"  ca_enabled        : {bool(r['context_agent_enabled'])}")
        if r["gold_label"]:
            print(f"  gold_label        : {green(r['gold_label'])}")
        if r["alert_id"]:
            print(f"  alert_id          : {r['alert_id']}")

    if at_rows:
        print()
        print(bold("Agent traces"))
        print(dim("─" * 40))
        for at in at_rows:
            print(f"  agent_trace_id : {at['agent_trace_id']}")
            print(f"  model_used     : {cyan(at['model_used'] or '?')}")
            try:
                tools = json.loads(at["tools_called_json"] or "[]")
            except Exception:
                tools = []
            # tools_called items may be plain names (str) or {"name": ...} dicts.
            tool_names = [
                t.get("name", str(t)) if isinstance(t, dict) else str(t)
                for t in tools
            ]
            print(f"  tools_called   : {', '.join(tool_names) if tool_names else '—'}")
            print(f"  is_real_threat : {red(str(bool(at['is_real_threat']))) if at['is_real_threat'] else green('False')}")
            print(f"  review_flag    : {bool(at['review_flag'])}")
            if at["severity"]:
                print(f"  severity       : {at['severity']}")
            print(f"  explanation    : {_trunc(at['explanation'] or '', 72)}")
            tok_total = int(at["tokens_input"] or 0) + int(at["tokens_output"] or 0)
            print(f"  tokens         : in={at['tokens_input']}  out={at['tokens_output']}"
                  f"  total={tok_total}  cost=${float(at['cost_usd']):.6f}")
            print(f"  latency_ms     : {float(at['latency_ms']):.1f}")
            print(f"  created_at     : {_ts(at['created_at'])}")

    if alert_rows:
        print()
        print(bold("Alerts"))
        print(dim("─" * 40))
        for al in alert_rows:
            print(f"  alert_id    : {al['alert_id']}")
            print(f"  child_id    : {al['child_id']}")
            print(f"  label       : {cyan(al['label'])}  severity={al['severity']}")
            fcm = al["fcm_status"]
            fcm_str = green(fcm) if fcm == "sent" else yellow(fcm)
            print(f"  fcm_status  : {fcm_str}")
            if al["explanation"]:
                print(f"  explanation : {_trunc(al['explanation'], 72)}")
            if al["quote_snippet"]:
                print(f"  quote       : {_trunc(al['quote_snippet'], 72)}")
            print(f"  created_at  : {_ts(al['created_at'])}")
    else:
        print()
        print(dim("  (no alert rows for this trace)"))

    print()
    return 0


def cmd_child(args) -> int:
    """Conversation turns + classifications for a child_id."""
    child_id = args.child_id
    conn = _open_ro(args.db)
    try:
        turns = conn.execute(
            """
            SELECT turn_index, role, text, created_at
            FROM conversations
            WHERE child_id = ?
            ORDER BY turn_index ASC, id ASC
            """,
            (child_id,),
        ).fetchall()

        classifications = conn.execute(
            """
            SELECT classification_id, created_at, classifier_label,
                   classifier_confidence, triage_decision, trace_id
            FROM classifications
            WHERE child_id = ?
            ORDER BY classification_id ASC
            """,
            (child_id,),
        ).fetchall()
    finally:
        conn.close()

    if not turns and not classifications:
        print(yellow(f"  No data found for child_id: {child_id}"))
        return 0

    print()
    print(bold(f"Child  ") + cyan(child_id))

    if turns:
        print()
        print(bold("Conversation turns"))
        print(dim("─" * 64))
        for t in turns:
            role_str = cyan(t["role"]) if "child" in (t["role"] or "") else dim(t["role"] or "?")
            print(f"  [{t['turn_index']:>3}]  {role_str:30}  {_ts(t['created_at'])}")
            print(f"        {_trunc(t['text'] or '', 64)}")
    else:
        print(dim("  (no conversation turns)"))

    if classifications:
        print()
        print(bold("Classifications"))
        print(dim("─" * 64))
        for r in classifications:
            label = cyan((r["classifier_label"] or "?").ljust(14))
            conf  = f"{float(r['classifier_confidence']):.2f}"
            td    = _triage_color(r["triage_decision"] or "?")
            print(f"  {str(r['classification_id']).rjust(5)}  {_ts(r['created_at'])}"
                  f"  {label}  {conf}  {td}  {dim(r['trace_id'] or '')}")
    else:
        print(dim("  (no classifications)"))

    print()
    return 0


def cmd_alerts(args) -> int:
    """Recent alert dispositions."""
    limit = args.limit
    conn = _open_ro(args.db)
    try:
        rows = conn.execute(
            """
            SELECT id, alert_id, trace_id, child_id, label,
                   severity, fcm_status, explanation, created_at
            FROM alerts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print(dim("  (no alerts in DB)"))
        return 0

    print()
    print(bold("Recent alerts") + dim(f"  [{args.db}]"))
    print(dim("─" * 80))
    for r in reversed(rows):
        fcm = r["fcm_status"] or "?"
        fcm_str = green(fcm) if fcm == "sent" else yellow(fcm)
        label = cyan((r["label"] or "?").ljust(13))
        sev   = (r["severity"] or "?").ljust(8)
        print(f"  {dim(_ts(r['created_at']))}  {label}  sev={sev}  "
              f"fcm={fcm_str}  child={_trunc(r['child_id'] or '', 12)}")
        if r["explanation"]:
            print(f"    {dim(_trunc(r['explanation'], 70))}")
    print(dim("─" * 80))
    print(dim(f"  {len(rows)} row(s)"))
    print()
    return 0


def cmd_stats(args) -> int:
    """Aggregate counts: by triage_decision, by label, alert count, etc."""
    conn = _open_ro(args.db)
    try:
        total_cls = conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
        total_traces = conn.execute(
            "SELECT COUNT(DISTINCT trace_id) FROM classifications"
        ).fetchone()[0]
        triage_counts = conn.execute(
            """
            SELECT triage_decision, COUNT(*) as n
            FROM classifications
            GROUP BY triage_decision
            ORDER BY n DESC
            """
        ).fetchall()
        label_counts = conn.execute(
            """
            SELECT classifier_label, COUNT(*) as n
            FROM classifications
            GROUP BY classifier_label
            ORDER BY n DESC
            """
        ).fetchall()
        total_alerts = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        alert_fcm = conn.execute(
            """
            SELECT fcm_status, COUNT(*) as n
            FROM alerts
            GROUP BY fcm_status
            ORDER BY n DESC
            """
        ).fetchall()
        total_turns = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        total_agent = conn.execute("SELECT COUNT(*) FROM agent_traces").fetchone()[0]
        total_gold  = conn.execute(
            "SELECT COUNT(*) FROM classifications WHERE gold_label IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()

    print()
    print(bold("Audit stats") + dim(f"  [{args.db}]"))
    print(dim("─" * 50))
    print(f"  classifications : {bold(str(total_cls))}  (unique traces: {total_traces})")
    print(f"  agent_traces    : {total_agent}")
    print(f"  alerts          : {total_alerts}")
    print(f"  conversation    : {total_turns} turns")
    print(f"  gold-labeled    : {total_gold}")

    if triage_counts:
        print()
        print(bold("  Triage distribution"))
        for row in triage_counts:
            pct = 100.0 * int(row[1]) / total_cls if total_cls else 0
            bar = "█" * int(pct / 4)
            print(f"    {_triage_color((row[0] or '?').ljust(16))}  "
                  f"{str(row[1]).rjust(6)}  ({pct:5.1f}%)  {dim(bar)}")

    if label_counts:
        print()
        print(bold("  Label distribution"))
        for row in label_counts:
            pct = 100.0 * int(row[1]) / total_cls if total_cls else 0
            bar = "█" * int(pct / 4)
            print(f"    {cyan((row[0] or '?').ljust(16))}  "
                  f"{str(row[1]).rjust(6)}  ({pct:5.1f}%)  {dim(bar)}")

    if alert_fcm:
        print()
        print(bold("  Alert FCM status"))
        for row in alert_fcm:
            fcm = row[0] or "?"
            fcm_str = green(fcm) if fcm == "sent" else yellow(fcm)
            print(f"    {fcm_str:20}  {row[1]}")

    print()
    return 0


# --------------------------------------------------------------------------- #
# Argument parsing.
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="inspect_audit.py",
        description="Shomer.AI audit-log inspector (read-only).",
    )
    p.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=f"path to the audit DB (default: {DEFAULT_DB})",
    )

    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("recent", help="last N classifications")
    sp.add_argument("--limit", type=int, default=20, help="number of rows (default: 20)")
    sp.set_defaults(func=cmd_recent)

    sp = sub.add_parser("trace", help="full picture for one trace_id")
    sp.add_argument("trace_id", help="the trace_id to inspect")
    sp.set_defaults(func=cmd_trace)

    sp = sub.add_parser("child", help="conversation + classifications for a child_id")
    sp.add_argument("child_id", help="the child_id to inspect")
    sp.set_defaults(func=cmd_child)

    sp = sub.add_parser("alerts", help="recent alert dispositions")
    sp.add_argument("--limit", type=int, default=20, help="number of rows (default: 20)")
    sp.set_defaults(func=cmd_alerts)

    sub.add_parser("stats", help="aggregate counts").set_defaults(func=cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
