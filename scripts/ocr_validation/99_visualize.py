#!/usr/bin/env python3
"""
99_visualize.py — build an HTML page for visual OCR verification.

Generates data/ocr_validation/verification.html showing each image side-by-side
with its original text and Tesseract's OCR output. Designed for fast eyeball
review — open in browser, scroll, spot bad rows.

USAGE:
    python 99_visualize.py
"""
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[2]
OCR_OUT = REPO / "data" / "ocr_validation" / "ocr_outputs.jsonl"
HTML_OUT = REPO / "data" / "ocr_validation" / "verification.html"

STYLE_COLORS = {
    "clear_hebrew":      "#d4edda",  # green
    "children_mistakes": "#fff3cd",  # yellow
    "code_switching":    "#cce5ff",  # blue
    "poor_spelling":     "#f8d7da",  # red
}


def char_diff(original: str, ocr: str) -> str:
    """Inline diff: characters present in original but missing/changed in OCR are highlighted.
    Simple approximation: highlights at the character-position level."""
    if not ocr:
        return f'<span style="color:red">(empty OCR output)</span>'
    # Use a very simple ratio for color
    from difflib import SequenceMatcher
    ratio = SequenceMatcher(None, original, ocr).ratio()
    if ratio >= 0.95:
        badge_color = "#28a745"  # green
        label = "good"
    elif ratio >= 0.80:
        badge_color = "#ffc107"  # yellow
        label = "ok"
    else:
        badge_color = "#dc3545"  # red
        label = "poor"
    return f'<span style="background:{badge_color};color:white;padding:2px 6px;border-radius:3px;font-size:10pt">{ratio*100:.0f}% {label}</span>'


def main():
    if not OCR_OUT.exists():
        sys.exit(f"ERROR: {OCR_OUT} not found. Run 03_run_ocr.py first.")

    records = [json.loads(line) for line in OCR_OUT.read_text(encoding="utf-8").splitlines()]
    print(f"Building verification HTML for {len(records)} records...")

    rows = []
    for r in records:
        img_rel = r["image_path"].replace("\\", "/")
        # Image lives at data/.../images/{style}/{id}.png; HTML is at data/.../verification.html
        img_html_path = "/".join(img_rel.split("/")[2:])  # strip leading "data/ocr_validation/"
        bg = STYLE_COLORS.get(r["style"], "#fff")
        diff_badge = char_diff(r["original_text"], r.get("ocr_text", "") or "")
        conf = r.get("confidence")
        conf_str = f"{conf:.2f}" if conf is not None else "n/a"
        rows.append(f"""
        <tr style="background:{bg}">
            <td style="font-weight:bold;text-align:center;padding:8px;">{r['style_label']}</td>
            <td style="padding:8px;font-size:9pt;color:#666;">{r['id']}</td>
            <td style="padding:8px;text-align:center;"><img src="images/{img_html_path}" style="max-height:60px;border:1px solid #ccc"></td>
            <td style="padding:8px;font-size:11pt;line-height:1.6;direction:rtl;">{r['original_text']}</td>
            <td style="padding:8px;font-size:11pt;line-height:1.6;direction:rtl;background:#fff;">{(r.get('ocr_text') or '<i>(empty)</i>')}</td>
            <td style="padding:8px;text-align:center;font-size:9pt;">{conf_str}</td>
            <td style="padding:8px;text-align:center;">{diff_badge}</td>
        </tr>
        """)

    html = f"""<!DOCTYPE html>
<html lang="he"><head><meta charset="utf-8"><title>OCR Verification — Shomer.AI</title>
<style>
body {{ font-family: David, Arial, sans-serif; max-width: 1400px; margin: 20px auto; padding: 0 20px; }}
h1 {{ border-bottom: 3px solid #2c5f8a; color: #1f3f5f; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1em; }}
th {{ background: #2c5f8a; color: white; padding: 10px; text-align: center; font-weight: bold; }}
td {{ border-bottom: 1px solid #ddd; vertical-align: middle; }}
tr:hover {{ background: rgba(0,0,0,0.03) !important; }}
.legend {{ margin-top: 1em; padding: 10px; background: #f8f9fa; border-radius: 5px; font-size: 10pt; }}
</style></head><body>
<h1>OCR Verification — {len(records)} records</h1>
<div class="legend">
    <strong>Styles:</strong>
    <span style="background:#d4edda;padding:2px 8px">A clear</span>
    <span style="background:#fff3cd;padding:2px 8px">B children</span>
    <span style="background:#cce5ff;padding:2px 8px">C code-switch</span>
    <span style="background:#f8d7da;padding:2px 8px">D poor-spelling</span>
    &nbsp;|&nbsp;
    <strong>Match badge:</strong>
    <span style="background:#28a745;color:white;padding:2px 6px">good ≥95%</span>
    <span style="background:#ffc107;color:white;padding:2px 6px">ok 80–95%</span>
    <span style="background:#dc3545;color:white;padding:2px 6px">poor &lt;80%</span>
</div>
<table>
    <thead><tr>
        <th>Style</th><th>ID</th><th>Image</th>
        <th style="text-align:right">Original (RTL)</th>
        <th style="text-align:right">OCR output (RTL)</th>
        <th>Conf</th><th>Match</th>
    </tr></thead>
    <tbody>{"".join(rows)}</tbody>
</table>
</body></html>
"""
    HTML_OUT.write_text(html, encoding="utf-8")
    print(f"[OK] Wrote {HTML_OUT.relative_to(REPO)}")
    print(f"     Open in browser: file:///{HTML_OUT.resolve().as_posix()}")


if __name__ == "__main__":
    main()
