#!/usr/bin/env python3
"""
05_analysis_charts.py — produce 5 analysis charts from T4 metrics.

USAGE:
    python 05_analysis_charts.py

INPUTS:
    data/ocr_validation/metrics.csv
    data/ocr_validation/metrics_summary.csv

OUTPUTS (PNG, ≥150 DPI):
    01_cer_histogram_by_style.png       — 4 overlaid CER distributions
    02_cosine_histogram_by_style.png    — 4 overlaid cosine-similarity distributions
    03_mean_cer_by_style_bar.png        — bar chart with pre-registered 15%/25% lines
    04_cer_vs_cosine_scatter.png        — semantic-vs-character degradation per sample
    05_confusion_chart.png              — which characters Tesseract substitutes most
"""
import json
import sys
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[2]
METRICS_CSV = REPO / "data" / "ocr_validation" / "metrics.csv"
SUMMARY_CSV = REPO / "data" / "ocr_validation" / "metrics_summary.csv"
CHARTS_DIR = REPO / "data" / "ocr_validation" / "charts"

STYLE_COLORS = {
    "A": "#28a745",  # green
    "B": "#fd7e14",  # orange
    "C": "#0d6efd",  # blue
    "D": "#dc3545",  # red
}
STYLE_NAMES = {
    "A": "A — Clear Hebrew",
    "B": "B — Children's mistakes",
    "C": "C — Code-switching",
    "D": "D — Poor spelling (phonetic)",
}

PASS_THRESHOLDS = {"A": 0.15, "B": 0.15, "C": 0.15, "D": 0.25}


def chart_1_cer_histogram(df, out):
    fig, ax = plt.subplots(figsize=(10, 6))
    for label in ["A", "B", "C", "D"]:
        data = df[df["style_label"] == label]["cer"]
        ax.hist(data, bins=15, alpha=0.5, label=STYLE_NAMES[label],
                color=STYLE_COLORS[label], edgecolor="black", linewidth=0.5)
    ax.axvline(0.15, color="red", linestyle="--", linewidth=2,
               label="15% threshold (pre-registered, A/B/C)")
    ax.axvline(0.25, color="darkred", linestyle=":", linewidth=2,
               label="25% threshold (pre-registered, D)")
    ax.set_xlabel("CER (Character Error Rate)", fontsize=12)
    ax.set_ylabel("Frequency (number of sentences)", fontsize=12)
    ax.set_title("OCR Character Error Rate Distribution by Style", fontsize=14)
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()


def chart_2_cosine_histogram(df, out):
    fig, ax = plt.subplots(figsize=(10, 6))
    for label in ["A", "B", "C", "D"]:
        data = df[df["style_label"] == label]["cosine_sim"]
        ax.hist(data, bins=15, alpha=0.5, label=STYLE_NAMES[label],
                color=STYLE_COLORS[label], edgecolor="black", linewidth=0.5)
    ax.axvline(0.85, color="red", linestyle="--", linewidth=2,
               label="0.85 semantic-similarity threshold")
    ax.set_xlabel("DictaBERT cosine similarity (semantic preservation)", fontsize=12)
    ax.set_ylabel("Frequency", fontsize=12)
    ax.set_title("Semantic Preservation Distribution by Style", fontsize=14)
    ax.legend(loc="upper left", fontsize=10)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()


def chart_3_mean_cer_bar(summary, out):
    fig, ax = plt.subplots(figsize=(10, 6))
    labels = summary["style_label"].tolist()
    means = summary["cer_mean"].tolist()
    stds = summary["cer_std"].tolist()
    colors = [STYLE_COLORS[l] for l in labels]
    bars = ax.bar(labels, means, yerr=stds, capsize=10,
                  color=colors, edgecolor="black", alpha=0.85)
    # Add threshold lines
    ax.axhline(0.15, color="red", linestyle="--", linewidth=2,
               label="15% threshold (A/B/C)")
    ax.axhline(0.25, color="darkred", linestyle=":", linewidth=2,
               label="25% threshold (D)")
    # Value labels above bars
    for bar, m in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                f"{m:.1%}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels([STYLE_NAMES[l] for l in labels], rotation=15, ha="right")
    ax.set_ylabel("Mean CER (lower is better)", fontsize=12)
    ax.set_title("Mean Character Error Rate by Style — PASS/FAIL vs. Threshold", fontsize=14)
    ax.legend(loc="upper left", fontsize=10)
    ax.grid(True, alpha=0.3, axis="y")
    ax.set_ylim(0, max(max(means) * 1.5, 0.3))
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()


def chart_4_cer_vs_cosine(df, out):
    fig, ax = plt.subplots(figsize=(10, 7))
    for label in ["A", "B", "C", "D"]:
        sub = df[df["style_label"] == label]
        ax.scatter(sub["cer"], sub["cosine_sim"], label=STYLE_NAMES[label],
                   color=STYLE_COLORS[label], s=80, alpha=0.7, edgecolor="black")
    ax.axvline(0.15, color="red", linestyle="--", alpha=0.5)
    ax.axhline(0.85, color="red", linestyle="--", alpha=0.5)
    ax.set_xlabel("CER (lower is better)", fontsize=12)
    ax.set_ylabel("DictaBERT cosine similarity (higher is better)", fontsize=12)
    ax.set_title("Character-level vs Semantic Degradation\n(top-left quadrant = ideal)", fontsize=14)
    ax.legend(loc="lower left", fontsize=10)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()


def chart_5_confusion(df, out, top_n=15):
    """Top character substitutions Tesseract makes (per-style)."""
    from difflib import SequenceMatcher
    counter = Counter()
    for _, row in df.iterrows():
        a = row["original_text"]
        b = row["ocr_clean"]
        if not isinstance(b, str):
            continue
        sm = SequenceMatcher(None, a, b)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "replace":
                for ca in a[i1:i2]:
                    for cb in b[j1:j2]:
                        if ca.strip() and cb.strip():
                            counter[(ca, cb)] += 1
                            break
    top = counter.most_common(top_n)
    if not top:
        # Empty figure
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.text(0.5, 0.5, "No character substitutions detected (excellent OCR)",
                ha="center", va="center", fontsize=14)
        ax.axis("off")
        plt.tight_layout()
        plt.savefig(out, dpi=150)
        plt.close()
        return

    labels = [f"{a} → {b}" for (a, b), _ in top]
    counts = [c for _, c in top]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(labels, counts, color="#6c757d", edgecolor="black")
    ax.set_xlabel("Frequency", fontsize=12)
    ax.set_title(f"Top {top_n} Character Substitutions by Tesseract", fontsize=14)
    ax.invert_yaxis()
    ax.grid(True, alpha=0.3, axis="x")
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()


def main():
    if not METRICS_CSV.exists():
        sys.exit(f"ERROR: {METRICS_CSV} not found. Run 04_compute_metrics.py first.")
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(METRICS_CSV, encoding="utf-8")
    summary = pd.read_csv(SUMMARY_CSV, encoding="utf-8")

    print(f"Generating 5 charts from {len(df)} records...")
    chart_1_cer_histogram(df, CHARTS_DIR / "01_cer_histogram_by_style.png")
    print("  [1/5] 01_cer_histogram_by_style.png")
    chart_2_cosine_histogram(df, CHARTS_DIR / "02_cosine_histogram_by_style.png")
    print("  [2/5] 02_cosine_histogram_by_style.png")
    chart_3_mean_cer_bar(summary, CHARTS_DIR / "03_mean_cer_by_style_bar.png")
    print("  [3/5] 03_mean_cer_by_style_bar.png")
    chart_4_cer_vs_cosine(df, CHARTS_DIR / "04_cer_vs_cosine_scatter.png")
    print("  [4/5] 04_cer_vs_cosine_scatter.png")
    chart_5_confusion(df, CHARTS_DIR / "05_confusion_chart.png")
    print("  [5/5] 05_confusion_chart.png")
    print(f"\n[OK] All charts in {CHARTS_DIR.relative_to(REPO)}/")


if __name__ == "__main__":
    main()
