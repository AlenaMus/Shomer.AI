#!/usr/bin/env python3
"""
07_category_analysis.py — analyse OCR success rates per offensive category.

USAGE:
    python 07_category_analysis.py

Inputs:
    data/ocr_validation/metrics.csv   (one row per sentence, has style + category)

Outputs (saved to data/ocr_validation/charts/):
    06_cer_histogram_by_category.png   — overlaid distributions per category
    07_success_rate_by_category.png    — bar chart of % pass per (style, category)
    08_category_summary_table.png      — text-table image with all numbers

Also prints a console summary table.

DEFINITION of success:
    "PASS" = CER ≤ pre-registered threshold (15% for A/B/C, 25% for D).
    "HIGH-QUALITY" = CER ≤ 10% (stricter).
"""
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[2]
METRICS_CSV = REPO / "data" / "ocr_validation" / "metrics.csv"
CHARTS_DIR = REPO / "data" / "ocr_validation" / "charts"

CATEGORY_COLORS = {
    "none":         "#28a745",  # green
    "abusive":      "#fd7e14",  # orange
    "hate":         "#dc3545",  # red
    "violence":     "#6f42c1",  # purple
    "pornographic": "#0d6efd",  # blue
}
CATEGORY_ORDER = ["none", "abusive", "hate", "violence", "pornographic"]
CATEGORY_NAMES_HE = {
    "none": "לא-פוגעני",
    "abusive": "מתעלל",
    "hate": "שנאה",
    "violence": "אלימות",
    "pornographic": "מיני",
}

STYLE_THRESHOLDS = {"A": 0.15, "B": 0.15, "C": 0.15, "D": 0.25}
HIGH_QUALITY_THRESHOLD = 0.10


def chart_cer_histogram_by_category(df, out):
    fig, ax = plt.subplots(figsize=(11, 6))
    for cat in CATEGORY_ORDER:
        data = df[df["category"] == cat]["cer"]
        if len(data) == 0:
            continue
        ax.hist(data, bins=25, alpha=0.55, label=f"{cat} (N={len(data)})",
                color=CATEGORY_COLORS[cat], edgecolor="black", linewidth=0.4)
    ax.axvline(0.15, color="red", linestyle="--", linewidth=2, label="15% threshold (A/B/C)")
    ax.axvline(0.25, color="darkred", linestyle=":", linewidth=2, label="25% threshold (D)")
    ax.set_xlabel("CER (Character Error Rate)", fontsize=12)
    ax.set_ylabel("Frequency", fontsize=12)
    ax.set_title("OCR CER Distribution by Offensive Category — All N=1040 Records", fontsize=14)
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(0, 0.6)
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()


def chart_success_rate_by_category(df, out):
    """Stacked bar: success rate per (style, category)."""
    fig, ax = plt.subplots(figsize=(13, 7))

    style_labels = ["A", "B", "C", "D"]
    x = np.arange(len(style_labels))
    width = 0.16

    for i, cat in enumerate(CATEGORY_ORDER):
        rates = []
        for s in style_labels:
            sub = df[(df["style_label"] == s) & (df["category"] == cat)]
            if len(sub) == 0:
                rates.append(0)
                continue
            thr = STYLE_THRESHOLDS[s]
            pct = (sub["cer"] <= thr).mean() * 100
            rates.append(pct)
        offset = (i - 2) * width
        bars = ax.bar(x + offset, rates, width, label=f"{cat}",
                       color=CATEGORY_COLORS[cat], edgecolor="black", linewidth=0.5)
        for bar, r in zip(bars, rates):
            if r > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                        f"{r:.0f}%", ha="center", va="bottom", fontsize=8, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels([f"Style {s}" for s in style_labels], fontsize=12)
    ax.set_ylabel("Success rate (% with CER ≤ threshold)", fontsize=12)
    ax.set_title("OCR Success Rate by (Style × Offensive Category) — N=1040", fontsize=14)
    ax.legend(loc="lower left", fontsize=10, ncol=5)
    ax.set_ylim(0, 115)
    ax.axhline(50, color="gray", linestyle="--", alpha=0.4)
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()


def chart_overall_success_per_category(df, out):
    """Single bar chart: overall success rate per category (across all styles)."""
    fig, ax = plt.subplots(figsize=(10, 6))
    rates = []
    counts = []
    high_quality = []
    for cat in CATEGORY_ORDER:
        sub = df[df["category"] == cat]
        if len(sub) == 0:
            rates.append(0)
            high_quality.append(0)
            counts.append(0)
            continue
        # Pre-registered threshold per style
        sub = sub.copy()
        sub["threshold"] = sub["style_label"].map(STYLE_THRESHOLDS)
        pass_count = (sub["cer"] <= sub["threshold"]).sum()
        hq_count = (sub["cer"] <= HIGH_QUALITY_THRESHOLD).sum()
        rates.append(pass_count / len(sub) * 100)
        high_quality.append(hq_count / len(sub) * 100)
        counts.append(len(sub))

    x = np.arange(len(CATEGORY_ORDER))
    width = 0.4
    b1 = ax.bar(x - width / 2, rates, width, label="PASS (≤ threshold)",
                color=[CATEGORY_COLORS[c] for c in CATEGORY_ORDER], edgecolor="black")
    b2 = ax.bar(x + width / 2, high_quality, width, label="HIGH-QUALITY (CER ≤ 10%)",
                color="#666", alpha=0.85, edgecolor="black")
    for bar, r in zip(b1, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{r:.0f}%", ha="center", va="bottom", fontsize=10, fontweight="bold")
    for bar, h in zip(b2, high_quality):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{h:.0f}%", ha="center", va="bottom", fontsize=9, color="black")

    ax.set_xticks(x)
    ax.set_xticklabels([f"{c}\n(N={n})" for c, n in zip(CATEGORY_ORDER, counts)], fontsize=10)
    ax.set_ylabel("Success rate (%)", fontsize=12)
    ax.set_title("Overall OCR Success Rate by Offensive Category — N=1040", fontsize=14)
    ax.legend(loc="lower right", fontsize=11)
    ax.set_ylim(0, 115)
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()


def print_console_table(df):
    print("\n" + "=" * 102)
    print(f"{'Category':<14} {'N':>5} {'CER mean':>10} {'CER med':>10} {'PASS%':>8} {'HQ%(CER≤10%)':>14} {'Cosine':>9}")
    print("-" * 102)
    for cat in CATEGORY_ORDER:
        sub = df[df["category"] == cat]
        if len(sub) == 0:
            print(f"{cat:<14} {'-':>5}")
            continue
        sub = sub.copy()
        sub["threshold"] = sub["style_label"].map(STYLE_THRESHOLDS)
        pass_pct = (sub["cer"] <= sub["threshold"]).mean() * 100
        hq_pct = (sub["cer"] <= HIGH_QUALITY_THRESHOLD).mean() * 100
        print(f"{cat:<14} {len(sub):>5} {sub['cer'].mean():>9.1%} "
              f"{sub['cer'].median():>9.1%} {pass_pct:>7.1f}% {hq_pct:>13.1f}% "
              f"{sub['cosine_sim'].mean():>9.3f}")
    print("=" * 102)

    print("\nPer (style × category) success rate:")
    print(f"{'Style':<6} " + " ".join(f"{c:>13}" for c in CATEGORY_ORDER))
    print("-" * 80)
    for s in ["A", "B", "C", "D"]:
        thr = STYLE_THRESHOLDS[s]
        cells = []
        for c in CATEGORY_ORDER:
            sub = df[(df["style_label"] == s) & (df["category"] == c)]
            if len(sub) == 0:
                cells.append("-")
            else:
                pct = (sub["cer"] <= thr).mean() * 100
                cells.append(f"{pct:>5.1f}% (N={len(sub):>3})")
        print(f"{s:<6} " + " ".join(f"{cell:>13}" for cell in cells))


def main():
    if not METRICS_CSV.exists():
        sys.exit(f"ERROR: {METRICS_CSV} not found. Run T4 first.")
    df = pd.read_csv(METRICS_CSV, encoding="utf-8")
    print(f"Loaded {len(df)} records from {METRICS_CSV.relative_to(REPO)}")

    if "category" not in df.columns:
        sys.exit("ERROR: metrics.csv missing 'category' column — re-run T4.")

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    chart_cer_histogram_by_category(df, CHARTS_DIR / "06_cer_histogram_by_category.png")
    print("  [1/3] 06_cer_histogram_by_category.png")
    chart_success_rate_by_category(df, CHARTS_DIR / "07_success_rate_by_style_category.png")
    print("  [2/3] 07_success_rate_by_style_category.png")
    chart_overall_success_per_category(df, CHARTS_DIR / "08_overall_success_per_category.png")
    print("  [3/3] 08_overall_success_per_category.png")

    print_console_table(df)


if __name__ == "__main__":
    main()
