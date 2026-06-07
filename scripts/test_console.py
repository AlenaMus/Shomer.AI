#!/usr/bin/env python3
"""Shomer.AI — interactive server test console.

A friendly, self-contained menu program for manually exercising the full server
flow. It speaks the same HTTP wire protocol as ``dev_client.py`` / the Shomer
SDK, and on top of that it:

  * starts its OWN server subprocess (isolated, on a chosen port),
  * isolates a per-session audit DB and server-log FILE under ``test-sessions/``,
  * runs a health check before showing the menu,
  * after each classify, reads the audit DB back and shows the triage decision,
    the Context-Agent verdict (if it ran), and **what alert was sent** (or why
    not),
  * exposes audit/log inspection from the menu.

Run from the repo root:

    server\\.venv\\Scripts\\python.exe scripts\\test_console.py
    server\\.venv\\Scripts\\python.exe scripts\\test_console.py --port 8010
    server\\.venv\\Scripts\\python.exe scripts\\test_console.py --attach http://localhost:8000   # use a running server
    server\\.venv\\Scripts\\python.exe scripts\\test_console.py --selftest                        # non-interactive smoke

Prerequisite: Ollama running (it backs the v1.0-standin classifier).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# UTF-8 stdio so Hebrew never crashes the console on Windows cp1252.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass

try:
    import httpx
except ImportError:
    sys.exit(
        "httpx is required. Use the server venv:\n"
        "    server\\.venv\\Scripts\\python.exe scripts\\test_console.py"
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).resolve().parent / "golden_inputs.jsonl"

# --------------------------------------------------------------------------- #
# Colours (ANSI; enabled on Windows via the VT trick, with a --no-color flag).
# --------------------------------------------------------------------------- #
_COLOR = True


def _enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


def red(s):    return _c("31", s)
def green(s):  return _c("32", s)
def yellow(s): return _c("33", s)
def cyan(s):   return _c("36", s)
def bold(s):   return _c("1", s)
def dim(s):    return _c("2", s)


def hr(ch: str = "─", n: int = 64) -> str:
    return dim(ch * n)


# --------------------------------------------------------------------------- #
# Hebrew RTL display. Most Windows terminals render text in logical order
# left-to-right, so Hebrew comes out reversed/wrong. python-bidi reorders a
# Hebrew string into VISUAL order so it reads correctly right-to-left when the
# terminal prints it LTR. Disable with --no-bidi if your terminal already does
# bidi (then it would double-reverse).
# --------------------------------------------------------------------------- #
_HEBREW = re.compile(r"[֐-׿]")
try:
    from bidi.algorithm import get_display as _get_display
    _BIDI_AVAILABLE = True
except Exception:
    _BIDI_AVAILABLE = False

_USE_BIDI = True


def he(s) -> str:
    """Reorder a Hebrew string to visual order for correct RTL terminal display."""
    if s is None:
        return ""
    s = str(s)
    if not _USE_BIDI or not _BIDI_AVAILABLE or not _HEBREW.search(s):
        return s
    return _get_display(s)


# --------------------------------------------------------------------------- #
# Server subprocess management.
# --------------------------------------------------------------------------- #
class TestServer:
    """Spawns and supervises an isolated server for one test session."""

    def __init__(self, port: int, audit_db: Path, log_file: Path) -> None:
        self.port = port
        self.audit_db = audit_db
        self.log_file = log_file
        self.base_url = f"http://127.0.0.1:{port}"
        self._proc: subprocess.Popen | None = None
        self._log_fh = None

    def start(self) -> None:
        env = dict(os.environ)
        env["AUDIT_DB_PATH"] = str(self.audit_db)
        env["CONTEXT_AGENT_ENABLED"] = "true"
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        self._log_fh = open(self.log_file, "w", encoding="utf-8")
        self._proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "app.main:app",
                "--app-dir", "server", "--port", str(self.port),
                "--log-level", "info",
            ],
            cwd=str(REPO_ROOT),
            stdout=self._log_fh,
            stderr=subprocess.STDOUT,
            env=env,
        )

    def wait_healthy(self, timeout: float = 60.0) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc and self._proc.poll() is not None:
                return None  # process died — caller shows the log tail
            try:
                r = httpx.get(f"{self.base_url}/health", timeout=2.0)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                pass
            time.sleep(1.0)
        return None

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.kill()
        if self._log_fh:
            self._log_fh.close()


# --------------------------------------------------------------------------- #
# API client (same wire protocol as dev_client.py / the SDK).
# --------------------------------------------------------------------------- #
class Api:
    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def health(self) -> dict:
        with self._client() as c:
            return c.get("/health").json()

    def info(self) -> dict:
        with self._client() as c:
            return c.get("/model/info").json()

    def classify(self, text: str, child_id: str | None, trace_id: str) -> dict:
        payload = {"text": text}
        if child_id:
            payload["child_id"] = child_id
        with self._client() as c:
            r = c.post("/classify", json=payload, headers={"X-Trace-Id": trace_id})
            r.raise_for_status()
            return r.json()

    def classify_image(self, path: Path, child_id: str | None, trace_id: str) -> dict:
        data = {"child_id": child_id} if child_id else None
        with self._client() as c, path.open("rb") as fh:
            r = c.post(
                "/classify-image",
                files={"image": (path.name, fh)},
                data=data,
                headers={"X-Trace-Id": trace_id},
            )
            r.raise_for_status()
            return r.json()


# --------------------------------------------------------------------------- #
# Audit read-back (read-only on the session DB).
# --------------------------------------------------------------------------- #
def _ro(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def summarize_trace(db: Path, trace_id: str) -> dict:
    """Return {classification, agent_trace, alert} for one trace_id."""
    out: dict = {"classification": None, "agent_trace": None, "alert": None}
    if not db.exists():
        return out
    try:
        with _ro(db) as c:
            row = c.execute(
                "SELECT * FROM classifications WHERE trace_id=? ORDER BY classification_id DESC LIMIT 1",
                (trace_id,),
            ).fetchone()
            out["classification"] = dict(row) if row else None
            at = c.execute(
                "SELECT * FROM agent_traces WHERE trace_id=? ORDER BY agent_trace_id DESC LIMIT 1",
                (trace_id,),
            ).fetchone()
            out["agent_trace"] = dict(at) if at else None
            al = c.execute(
                "SELECT * FROM alerts WHERE trace_id=? ORDER BY id DESC LIMIT 1",
                (trace_id,),
            ).fetchone()
            out["alert"] = dict(al) if al else None
    except Exception as exc:
        out["error"] = str(exc)
    return out


def _print_outcome(cls: dict, at: dict | None, al: dict | None) -> None:
    """Print the audited triage decision + Context-Agent verdict + alert."""
    decision = cls.get("triage_decision", "?")
    frontline = cls.get("frontline_only_decision")
    dtxt = decision.upper() if isinstance(decision, str) else decision
    color = {"alert_direct": red, "silent": green,
             "escalate_to_ca": yellow, "review_needed": yellow}.get(decision, cyan)
    extra = f"  (frontline: {frontline})" if frontline and frontline != decision else ""
    print(f"  triage   : {color(dtxt)}{dim(extra)}")

    if at:
        threat = at.get("is_real_threat")
        try:
            names = [t.get("name", t) if isinstance(t, dict) else t
                     for t in json.loads(at.get("tools_called_json") or "[]")]
        except Exception:
            names = []
        print(f"  context  : model={at.get('model_used')}  "
              f"real_threat={red('YES') if threat else green('no')}  "
              f"tools=[{', '.join(str(n) for n in names)}]")
        if at.get("explanation"):
            print(dim("           reason: ") + he(at.get("explanation")))

    if al:
        status = al.get("fcm_status")
        sc = green if status == "sent" else (yellow if status in ("rate_limited", "queued") else red)
        print(f"  ALERT    : {sc(str(status).upper())}  "
              f"{bold(str(al.get('label')))} sev={al.get('severity')}  "
              f"child={al.get('child_id')}")
        if al.get("explanation"):
            print(dim("           message: ") + he(al.get("explanation")))
    else:
        print(f"  alert    : {dim('none sent')}  "
              + dim("(decision did not warrant an alert, or CA judged it safe)"))


def print_result(resp: dict, summary: dict) -> None:
    """Pretty-print a classify response + its audited triage/alert outcome."""
    cls = summary.get("classification") or {}
    offensive = resp.get("is_offensive")
    head = red("⚠ OFFENSIVE") if offensive else green("✓ clean")
    print(hr())
    print(f"  {head}   "
          f"{bold(str(resp.get('category')))}   "
          f"conf={resp.get('confidence')}   "
          f"{resp.get('latency_ms')}ms   "
          f"model={dim(str(resp.get('model')))}")
    if resp.get("extracted_text") is not None:
        print(dim("  OCR text : ") + he(resp.get("extracted_text") or "(none)"))
    _print_outcome(cls, summary.get("agent_trace"), summary.get("alert"))
    print(hr())


def print_trace(summary: dict) -> None:
    """Pretty-print a stored audit record (no live response needed)."""
    cls = summary.get("classification") or {}
    offensive = bool(cls.get("is_offensive"))
    head = red("⚠ OFFENSIVE") if offensive else green("✓ clean")
    print(hr())
    print(f"  {head}   {bold(str(cls.get('classifier_label')))}   "
          f"conf={cls.get('classifier_confidence')}   "
          f"child={cls.get('child_id') or '-'}")
    print(dim("  input    : ") + he(cls.get("input_text")))
    _print_outcome(cls, summary.get("agent_trace"), summary.get("alert"))
    print(hr())


# --------------------------------------------------------------------------- #
# Audit inspection helpers (menu items 4-7).
# --------------------------------------------------------------------------- #
def show_recent(db: Path, limit: int = 15) -> None:
    if not db.exists():
        print(dim("  (no audit DB yet)"))
        return
    with _ro(db) as c:
        rows = c.execute(
            "SELECT classification_id, trace_id, classifier_label, classifier_confidence, "
            "triage_decision, child_id, input_text FROM classifications "
            "ORDER BY classification_id DESC LIMIT ?", (limit,),
        ).fetchall()
    print(hr())
    for r in rows:
        print(f"  #{r['classification_id']:<3} {r['triage_decision']:<14} "
              f"{r['classifier_label']:<14} conf={r['classifier_confidence']:.2f}  "
              f"{dim((r['child_id'] or '-')[:12]):<12}  {he((r['input_text'] or '')[:40])}")
    print(hr())


def show_alerts(db: Path, limit: int = 20) -> None:
    if not db.exists():
        print(dim("  (no audit DB yet)")); return
    with _ro(db) as c:
        rows = c.execute(
            "SELECT label, severity, fcm_status, child_id, explanation, trace_id "
            "FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        print(dim("  (no alerts recorded)")); return
    print(hr())
    for r in rows:
        st = r["fcm_status"]
        sc = green if st == "sent" else yellow
        print(f"  {sc(st):<12} {bold(r['label']):<14} sev={r['severity']:<7} "
              f"child={r['child_id']:<12} {dim(r['trace_id'][:12])}")
        print(dim("    ") + he(r["explanation"] or ""))
    print(hr())


def show_stats(db: Path) -> None:
    if not db.exists():
        print(dim("  (no audit DB yet)")); return
    with _ro(db) as c:
        def n(q, args=()):
            return c.execute(q, args).fetchone()[0]
        n_cls = n("SELECT COUNT(*) FROM classifications")
        n_at = n("SELECT COUNT(*) FROM agent_traces")
        n_al = n("SELECT COUNT(*) FROM alerts")
        n_sent = n("SELECT COUNT(*) FROM alerts WHERE fcm_status=?", ("sent",))
        n_rl = n("SELECT COUNT(*) FROM alerts WHERE fcm_status=?", ("rate_limited",))
        n_turns = n("SELECT COUNT(*) FROM conversations")
        print(hr())
        print(f"  classifications : {n_cls}")
        print(f"  agent_traces    : {n_at}")
        print(f"  alerts          : {n_al}  (sent={n_sent}, rate_limited={n_rl})")
        print(f"  conversations   : {n_turns} turns")
        print(dim("  triage distribution:"))
        for r in c.execute("SELECT triage_decision, COUNT(*) n FROM classifications "
                           "GROUP BY triage_decision ORDER BY n DESC"):
            print(f"    {r['triage_decision']:<16} {r['n']}")
        print(hr())


def show_conversation(db: Path, child_id: str) -> None:
    if not db.exists():
        print(dim("  (no audit DB yet)")); return
    with _ro(db) as c:
        rows = c.execute(
            "SELECT turn_index, role, text FROM conversations WHERE child_id=? "
            "ORDER BY turn_index", (child_id,)).fetchall()
    if not rows:
        print(dim(f"  (no turns for child '{child_id}')")); return
    print(hr())
    for r in rows:
        print(f"  [{r['turn_index']:>2}] {dim(r['role']):<18} {he(r['text'])}")
    print(hr())


def tail_log(log_file: Path, n: int = 40) -> None:
    if not log_file.exists():
        print(dim("  (no server log)")); return
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    print(hr())
    for ln in lines[-n:]:
        print("  " + ln)
    print(hr())


# --------------------------------------------------------------------------- #
# Menu actions.
# --------------------------------------------------------------------------- #
def _new_trace() -> str:
    return f"ui-{uuid.uuid4().hex[:8]}"


# Curated test sentences (one per triage branch). Picking these avoids typing
# Hebrew, which most Windows terminals echo reversed on the INPUT line (a
# terminal limitation — the data the program receives is still correct).
SAMPLE_TEXTS = [
    ("clean → SILENT",                         "שלום אמא, אני בדרך הביתה"),
    ("abusive → ALERT_DIRECT",                 "אתה טמבל מטומטם, כולם שונאים אותך"),
    ("hate → ALERT_DIRECT",                    "אני שונא את כל הזרים האלה, שייעלמו מהמדינה"),
    ("violence → ESCALATE to Context Agent",   "אני אשבור לך את העצמות אחרי בית הספר"),
    ("pornographic → ALERT_DIRECT",            "תשלחי לי תמונות עירום שלך עכשיו"),
]


def action_classify_text(api: Api, db: Path) -> None:
    print(dim("  Pick a sample (Hebrew typed at the prompt echoes reversed in this terminal):"))
    for i, (label, txt) in enumerate(SAMPLE_TEXTS, 1):
        print(f"   {cyan(str(i))}  {he(txt)}   {dim('(' + label + ')')}")
    print(f"   {cyan('t')}  type your own  {dim('(input line may look reversed; the result is still correct)')}")
    choice = input(cyan("  pick #/t> ")).strip().lower()
    if choice == "t":
        text = input(cyan("  Hebrew text> ")).strip()
    elif choice.isdigit() and 1 <= int(choice) <= len(SAMPLE_TEXTS):
        text = SAMPLE_TEXTS[int(choice) - 1][1]
    else:
        print(dim("  (cancelled)")); return
    if not text:
        print(dim("  (cancelled)")); return
    print(dim("  text: ") + he(text))  # confirm correct RTL ordering
    child = input(cyan("  child_id (optional, Enter to skip)> ")).strip() or None
    tid = _new_trace()
    try:
        resp = api.classify(text, child, tid)
    except Exception as exc:
        print(red(f"  request failed: {exc}")); return
    time.sleep(0.1)  # audit writes are awaited server-side; tiny cushion for WAL read
    print_result(resp, summarize_trace(db, tid))
    print(dim(f"  trace_id={tid}"))


def action_classify_image(api: Api, db: Path) -> None:
    p = input(cyan("  image path> ")).strip().strip('"')
    if not p:
        print(dim("  (cancelled)")); return
    path = Path(p)
    if not path.is_file():
        print(red(f"  no such file: {path}")); return
    child = input(cyan("  child_id (optional)> ")).strip() or None
    tid = _new_trace()
    try:
        resp = api.classify_image(path, child, tid)
    except Exception as exc:
        print(red(f"  request failed: {exc}")); return
    time.sleep(0.1)
    print_result(resp, summarize_trace(db, tid))
    print(dim(f"  trace_id={tid}"))


def action_demo(api: Api, db: Path) -> None:
    if not GOLDEN.is_file():
        print(red(f"  golden set not found: {GOLDEN}")); return
    items = [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(hr())
    for it in items:
        tid = _new_trace()
        try:
            resp = api.classify(it["text"], it.get("id"), tid)
        except Exception as exc:
            print(red(f"  {it['id']}: failed {exc}")); continue
        cls = summarize_trace(db, tid)["classification"] or {}
        ok = resp.get("category") == it.get("expected_category")
        mark = green("✓") if ok else yellow("≠")
        head = red("OFFENSIVE") if resp.get("is_offensive") else green("clean   ")
        print(f"  {it['id']} {mark} {head} {resp.get('category'):<14} "
              f"{cls.get('triage_decision',''):<14} {he(it['text'][:34])}")
    print(hr())


def action_conversation(api: Api, db: Path) -> None:
    child = input(cyan("  child_id> ")).strip()
    if child:
        show_conversation(db, child)


def action_replay(api: Api, db: Path) -> None:
    tid = input(cyan("  trace_id to replay> ")).strip()
    if not tid:
        return
    if not db.exists():
        print(dim("  (no audit DB)")); return
    with _ro(db) as c:
        row = c.execute("SELECT input_text, child_id FROM classifications WHERE trace_id=?",
                        (tid,)).fetchone()
    if not row or not row["input_text"]:
        print(red(f"  no stored input for trace {tid}")); return
    new_tid = tid + "-replay"
    resp = api.classify(row["input_text"], row["child_id"], new_tid)
    time.sleep(0.1)
    print(dim(f"  replaying: {row['input_text'][:50]}"))
    print_result(resp, summarize_trace(db, new_tid))


def action_inspect_trace(api: Api, db: Path) -> None:
    tid = input(cyan("  trace_id> ")).strip()
    if not tid:
        return
    s = summarize_trace(db, tid)
    if not s.get("classification"):
        print(red(f"  no audit record for trace '{tid}'")); return
    print_trace(s)


def action_metrics(api: Api) -> None:
    try:
        with httpx.Client(base_url=api.base_url, timeout=10) as c:
            txt = c.get("/metrics").text
    except Exception as exc:
        print(red(f"  /metrics failed: {exc}")); return
    lines = [l for l in txt.splitlines() if l.startswith("shomer_")]
    print(hr())
    if not lines:
        print(dim("  (no shomer_ metrics yet — make some requests first)"))
    for l in lines[:30]:
        print("  " + l)
    print(hr())


def action_loadtest(api: Api, db: Path, session_dir: Path) -> None:
    rep = session_dir / "loadtest_report.md"
    print(dim("  running load test (concurrency 4, repeat 1 over golden set)..."))
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "load_test.py"),
         "--server", api.base_url, "--db", str(db), "--out", str(rep),
         "--concurrency", "4", "--repeat", "1"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
    )
    last = (r.stdout.strip().splitlines() or [""])[-1]
    print("  " + last)
    if r.returncode != 0:
        print(red("  load test error:")); print(dim((r.stderr or "")[-400:]))
    else:
        print(green(f"  report → {rep}"))


# Each item: (key, title, one-line full-flow role). The role text is the
# "hover" explanation — shown inline in the menu and expanded by '?'.
MENU_ITEMS = [
    ("1", "Classify TEXT",
     "text → classifier → triage → (Context Agent if borderline) → alert? → audit"),
    ("2", "Classify IMAGE",
     "image → OCR → classifier → triage → (Context Agent) → alert? → audit"),
    ("3", "Golden-set demo",
     "push 10 curated Hebrew samples through the whole pipeline at once"),
    ("4", "Conversation history",
     "show a child's stored turns — exactly what the CA's read_history tool sees"),
    ("5", "Recent classifications",
     "last audit rows: label, confidence, triage decision, child"),
    ("6", "Alerts sent",
     "alert dispositions the Notifier produced: SENT vs rate_limited, severity, message"),
    ("7", "Audit stats",
     "totals + triage-branch distribution for this session"),
    ("8", "Replay a trace",
     "re-send a stored input and compare the fresh decision (regression check)"),
    ("9", "Tail server log",
     "last 40 lines of THIS session's server.log (gatekeeper, classifier, triage, alerts)"),
    ("t", "Inspect a trace",
     "full audit record for one trace_id: classification + CA trace + alert"),
    ("m", "Gateway metrics",
     "Prometheus shomer_* series from /metrics (the Gatekeeper edge layer)"),
    ("L", "Load test",
     "concurrent /classify burst → p50/p95/p99 latency report in the session folder"),
    ("i", "Health / info",
     "/health (ollama reachability) + /model/info (labels)"),
    ("p", "Session paths",
     "where this session's audit.db and server.log live"),
    ("?", "Help — full flow",
     "explain every function's place in the end-to-end pipeline"),
    ("q", "Quit",
     "stop the spawned server (session files are kept)"),
]

FLOW_HELP = f"""
{bold('How the full flow works — and what each menu function exercises')}
{hr()}
  Request → {cyan('Gatekeeper')} (trace-id, rate-limit, size, /metrics)
          → {cyan('Classifier')} (Ollama v1.0-standin: label + confidence)
          → {cyan('Triage')} (SILENT / ALERT_DIRECT / ESCALATE_TO_CA / REVIEW_NEEDED;
                     violence→always escalate, pornographic→always alert)
          → {cyan('Context Agent')} (only on ESCALATE; mock unless LLM keys set → tends to 'safe')
          → {cyan('Alerts')} (LogNotifier on ALERT_DIRECT; per-child rate-limit bucket)
          → {cyan('Audit')} (SQLite: classification + agent trace + alert + conversation turn)
{hr()}
  1/2  drive the WHOLE chain (text / image). The result line shows the classifier
       verdict; the lines under it show the triage decision, the CA verdict (if it
       ran), and the ALERT that was sent — or why none was.
  3    same chain ×10 samples — quick coverage of every label.
  4    the conversation memory the CA reads (send several msgs with one child_id).
  5/6/7/t  read back the audit DB: rows / alerts / stats / one full trace.
  8    replay = re-run a past input to see if the decision is stable.
  9    raw server log for this session (every stage logs here).
  m    the Gatekeeper's Prometheus metrics. L  load/latency test.
{hr()}
  Tips: use a distinct child_id per offensive message to see an alert 'SENT'
  (shared/blank child_id collapses into one rate-limit bucket). 'violence' always
  escalates to the CA, which (as a mock) usually ends 'silent' → no alert.
"""


def render_menu() -> None:
    print()
    print(bold("  Shomer.AI — Server Test Console") + dim("   (type a key; '?' for full-flow help)"))
    print(hr())
    for key, title, role in MENU_ITEMS:
        print(f"  {cyan(key)}  {title:<24}{dim(role)}")
    print(hr())


def menu_loop(api: Api, db: Path, log_file: Path, session_dir: Path) -> None:
    actions = {
        "1": lambda: action_classify_text(api, db),
        "2": lambda: action_classify_image(api, db),
        "3": lambda: action_demo(api, db),
        "4": lambda: action_conversation(api, db),
        "5": lambda: show_recent(db),
        "6": lambda: show_alerts(db),
        "7": lambda: show_stats(db),
        "8": lambda: action_replay(api, db),
        "9": lambda: tail_log(log_file),
        "t": lambda: action_inspect_trace(api, db),
        "m": lambda: action_metrics(api),
        "l": lambda: action_loadtest(api, db, session_dir),
        "i": lambda: print("  " + json.dumps(
            {**api.health(), "labels": api.info().get("labels")}, ensure_ascii=False)),
        "p": lambda: print(f"  session : {session_dir}\n  audit   : {db}\n  log     : {log_file}"),
        "?": lambda: print(FLOW_HELP),
        "h": lambda: print(FLOW_HELP),
    }
    while True:
        render_menu()
        choice = input(bold("  choose> ")).strip().lower()
        if choice in ("q", "quit", "exit"):
            return
        fn = actions.get(choice)
        if not fn:
            print(dim("  (unknown option — type '?' for help)")); continue
        try:
            fn()
        except (KeyboardInterrupt, EOFError):
            return
        except Exception as exc:
            print(red(f"  error: {exc}"))


# --------------------------------------------------------------------------- #
# Selftest (non-interactive smoke).
# --------------------------------------------------------------------------- #
def run_selftest(api: Api, db: Path) -> int:
    print(bold("[selftest] driving a few requests..."))
    cases = [
        ("שלום אמא, אני בדרך הביתה", "alon"),
        ("אתה טמבל מטומטם, כולם שונאים אותך", "danny"),
        ("תשלחי לי תמונות עירום שלך עכשיו", "rina"),
    ]
    for text, child in cases:
        tid = _new_trace()
        resp = api.classify(text, child, tid)
        time.sleep(0.1)
        print_result(resp, summarize_trace(db, tid))
    show_stats(db)
    return 0


# --------------------------------------------------------------------------- #
# Main.
# --------------------------------------------------------------------------- #
def check_ollama() -> bool:
    try:
        return httpx.get("http://localhost:11434/api/tags", timeout=3).status_code == 200
    except Exception:
        return False


def main() -> int:
    global _COLOR, _USE_BIDI
    ap = argparse.ArgumentParser(description="Shomer.AI interactive server test console")
    ap.add_argument("--port", type=int, default=8000, help="port for the spawned server (default 8000)")
    ap.add_argument("--attach", default=None, help="attach to an already-running server URL instead of spawning")
    ap.add_argument("--selftest", action="store_true", help="non-interactive smoke run, then exit")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--no-bidi", action="store_true",
                    help="disable Hebrew RTL reordering (use if your terminal already does bidi)")
    args = ap.parse_args()
    _COLOR = not args.no_color
    _USE_BIDI = not args.no_bidi
    if _COLOR:
        _enable_windows_ansi()
    if _USE_BIDI and not _BIDI_AVAILABLE:
        print(yellow("  ! python-bidi not installed — Hebrew may display left-to-right.\n"
                     "    Fix: server\\.venv\\Scripts\\python.exe -m pip install python-bidi"))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    session_dir = REPO_ROOT / "test-sessions" / f"session-{stamp}"
    session_dir.mkdir(parents=True, exist_ok=True)
    audit_db = session_dir / "audit.db"
    log_file = session_dir / "server.log"

    print(bold("\nShomer.AI — Server Test Console"))
    print(dim(f"  session: {session_dir}"))

    if not check_ollama():
        print(yellow("  ! Ollama not reachable on :11434 — the classifier will report errors.\n"
                     "    Start Ollama, then retry for meaningful results.\n"))

    server: TestServer | None = None
    if args.attach:
        base_url = args.attach
        print(dim(f"  attaching to {base_url} (server log capture N/A in attach mode)"))
        # In attach mode we can still read the audit DB the running server uses,
        # if it is the default path. Point at it for read-back.
        audit_db = Path(os.environ.get("AUDIT_DB_PATH", "server/data/audit.db"))
        api = Api(base_url)
        try:
            health = api.health()
        except Exception as exc:
            print(red(f"  cannot reach {base_url}: {exc}")); return 1
    else:
        print(dim(f"  starting server on :{args.port} ... "), end="", flush=True)
        server = TestServer(args.port, audit_db, log_file)
        server.start()
        health = server.wait_healthy()
        if not health:
            print(red("FAILED"))
            print(red("  server did not become healthy. Last log lines:"))
            tail_log(log_file, 25)
            print(yellow(f"  (is port {args.port} already in use? try --port 8010)"))
            if server:
                server.stop()
            return 1
        print(green("ready"))
        api = Api(server.base_url)

    print(f"  health: {green('ok') if health.get('status')=='ok' else yellow(health.get('status'))}  "
          f"ollama_reachable={health.get('ollama_reachable')}  model={health.get('model')}")
    print(dim(f"  audit DB : {audit_db}"))
    print(dim(f"  server log: {log_file}"))

    try:
        if args.selftest:
            run_selftest(api, audit_db)
        else:
            menu_loop(api, audit_db, log_file, session_dir)
    finally:
        if server:
            print(dim("\n  stopping server..."))
            server.stop()
        print(green("  done. session files kept at:"))
        print(f"    {session_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
