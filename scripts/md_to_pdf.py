#!/usr/bin/env python3
"""
md_to_pdf.py — convert (Hebrew RTL) Markdown docs to PDF.

Pipeline:  Markdown --(python-markdown)--> styled RTL HTML --(headless Edge)--> PDF

Why this route (not LaTeX/pandoc): the project's Hebrew docs are wrapped in
`<div dir="rtl">` and use GitHub-flavored tables. A headless Chromium/Edge
renders Hebrew + RTL + tables natively with Windows system fonts, so we get
correct output with zero LaTeX/font setup.

Usage:
    python scripts/md_to_pdf.py                 # converts the default doc list
    python scripts/md_to_pdf.py a.md b.md       # converts the given files
Output: a .pdf (and intermediate .html) next to each .md.
"""
import re
import sys
import html
import shutil
import tempfile
import subprocess
from pathlib import Path

import markdown  # pip install markdown  (already present)

REPO = Path(__file__).resolve().parents[1]

# Default deliverables (Meeting-3) if no args are given.
DEFAULT_DOCS = [
    REPO / "docs" / "preparatory_report.md",
    REPO / "docs" / "research_question.md",
    REPO / "docs" / "literature_flagship.md",
    REPO / "docs" / "prompt-book.md",
    REPO / "docs" / "next-meeting-prep-2026-05-28.md",
]

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

CSS = """
@page { size: A4; margin: 1.6cm; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: "David", "Frank Ruehl CLM", "Times New Roman", "Segoe UI", Arial, sans-serif;
  font-size: 11.5pt; line-height: 1.6; color: #1a1a1a; max-width: 100%;
}
h1 { font-size: 21pt; border-bottom: 3px solid #2c5f8a; padding-bottom: 6px; color: #1f3f5f; }
h2 { font-size: 16pt; border-bottom: 1px solid #cdd9e5; padding-bottom: 3px; color: #2c5f8a; margin-top: 1.4em; }
h3 { font-size: 13pt; color: #34618a; }
h1, h2, h3 { page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 0.8em 0; page-break-inside: avoid; font-size: 10.5pt; }
th, td { border: 1px solid #b9c4d0; padding: 5px 8px; text-align: start; vertical-align: top; }
th { background: #dee9f7; font-weight: 700; }
tr:nth-child(even) td { background: #f5f8fc; }
blockquote { border-inline-start: 4px solid #e0a800; background: #fffbe9; margin: 0.8em 0; padding: 6px 14px; }
code { background: #f0f0f3; padding: 1px 5px; border-radius: 3px; font-size: 0.9em; }
pre { background: #f6f8fa; border: 1px solid #d9dde2; border-radius: 6px; padding: 10px 14px;
      direction: ltr; text-align: left; overflow-x: auto; font-size: 9.5pt; }
pre code { background: none; padding: 0; }
a { color: #1a56c4; }
ul, ol { padding-inline-start: 1.4em; }
hr { border: none; border-top: 1px solid #d0d7de; margin: 1.4em 0; }
"""

WRAP_OPEN = re.compile(r'^\s*<div\s+dir="rtl"\s*>\s*', re.IGNORECASE)
WRAP_CLOSE = re.compile(r'\s*</div>\s*$', re.IGNORECASE)


def find_edge() -> str:
    for c in EDGE_CANDIDATES:
        if Path(c).exists():
            return c
    raise SystemExit("Microsoft Edge not found — cannot print to PDF.")


def md_to_html(md_path: Path) -> tuple[str, str]:
    raw = md_path.read_text(encoding="utf-8")
    rtl = bool(WRAP_OPEN.search(raw))
    # Strip the dir="rtl" wrapper so python-markdown processes the inner
    # tables/headings; RTL is reapplied via the <html dir> attribute below.
    body_md = WRAP_OPEN.sub("", raw)
    body_md = WRAP_CLOSE.sub("", body_md)
    html_body = markdown.markdown(
        body_md,
        extensions=["extra", "sane_lists", "toc", "admonition"],
        output_format="html5",
    )
    # Transform mermaid code blocks into mermaid divs so mermaid.js can render
    # them as actual diagrams (otherwise they appear as raw source in the PDF).
    # python-markdown wraps fenced ```mermaid blocks as <pre><code class="language-mermaid">.
    html_body = re.sub(
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        lambda m: f'<div class="mermaid">{html.unescape(m.group(1))}</div>',
        html_body,
        flags=re.DOTALL,
    )
    has_mermaid = '<div class="mermaid">' in html_body
    mermaid_head = ""
    if has_mermaid:
        # Mermaid renders LTR regardless of page direction (diagrams are LTR by
        # convention). The CDN script is small enough to load within the 25s
        # virtual-time-budget below.
        mermaid_head = (
            '<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>'
            '<script>mermaid.initialize({startOnLoad: true, theme: "default", '
            'flowchart: {useMaxWidth: true, htmlLabels: true}, '
            'sequence: {useMaxWidth: true}});</script>'
        )
    direction = "rtl" if rtl else "ltr"
    doc = f"""<!DOCTYPE html>
<html dir="{direction}" lang="he">
<head><meta charset="utf-8"><title>{md_path.stem}</title>
<style>{CSS}</style>
{mermaid_head}
</head>
<body>{html_body}</body></html>"""
    return doc, direction


def convert(md_path: Path, edge: str, user_data_dir: str) -> Path:
    html_doc, direction = md_to_html(md_path)
    # Absolute paths: headless=new Edge does not reliably honor a RELATIVE
    # --print-to-pdf target (it silently writes nothing).
    html_path = md_path.resolve().with_suffix(".html")
    pdf_path = md_path.resolve().with_suffix(".pdf")
    html_path.write_text(html_doc, encoding="utf-8")
    url = html_path.resolve().as_uri()
    # mtime before, so we can verify the PDF was actually (re)written.
    before = pdf_path.stat().st_mtime if pdf_path.exists() else 0.0
    # An isolated --user-data-dir is REQUIRED: without it, headless Edge
    # attaches to an already-running Edge instance and exits 0 WITHOUT writing
    # the PDF (silent no-op). --no-first-run keeps the temp profile quiet.
    # --headless=new (NOT the legacy --headless): the legacy mode silently
    # no-ops --print-to-pdf when another Edge instance is already running.
    subprocess.run(
        [edge, "--headless=new", "--disable-gpu", "--no-first-run",
         f"--user-data-dir={user_data_dir}",
         "--no-pdf-header-footer", "--virtual-time-budget=25000",
         f"--print-to-pdf={pdf_path}", url],
        check=True, capture_output=True,
    )
    after = pdf_path.stat().st_mtime if pdf_path.exists() else 0.0
    if after <= before:
        raise RuntimeError(
            "Edge returned success but the PDF was not updated "
            "(is the PDF open in a viewer? is Edge still no-op'ing?)."
        )
    print(f"  [{direction}] {md_path.name}  ->  {pdf_path.name}")
    return pdf_path


def main():
    args = sys.argv[1:]
    docs = [Path(a) for a in args] if args else DEFAULT_DOCS
    edge = find_edge()
    print(f"Edge: {edge}\nConverting {len(docs)} file(s):")
    ok = 0
    user_data_dir = tempfile.mkdtemp(prefix="md2pdf-edge-")
    try:
        for d in docs:
            if not d.exists():
                print(f"  SKIP (missing): {d}")
                continue
            try:
                convert(d, edge, user_data_dir)
                ok += 1
            except subprocess.CalledProcessError as e:
                print(f"  FAIL: {d.name}\n    {e.stderr.decode(errors='ignore')[:300]}")
            except RuntimeError as e:
                print(f"  FAIL: {d.name}\n    {e}")
    finally:
        shutil.rmtree(user_data_dir, ignore_errors=True)
    print(f"Done: {ok}/{len(docs)} PDF(s) generated.")


if __name__ == "__main__":
    main()
