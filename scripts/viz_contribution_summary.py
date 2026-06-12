#!/usr/bin/env python3
"""High-resolution presentation 'money graph': the two ways conversational context helps.

Left  : Experiment 1 (per-message) -> context CUTS false alarms (FPR 55.9 -> 26.5).
Right : Experiment 2 (harm-reframe) -> context RECOVERS hidden harm (recall 58.9 -> 82.1).

Renders docs/research_question/plots/contribution_two_axes.png at 200 DPI with large,
slide-legible English labels.
"""
from __future__ import annotations
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "research_question" / "plots"
OUT.mkdir(parents=True, exist_ok=True)

BLIND = "#E45756"   # context-blind (red)  -> reads ONE message
AWARE = "#1C6FA8"   # context-aware (blue) -> reads the CONVERSATION
GOOD = "#0E9F6E"
plt.rcParams.update({"font.size": 16, "axes.titleweight": "bold", "figure.dpi": 200,
                     "axes.grid": True, "grid.alpha": .22, "axes.axisbelow": True,
                     "font.family": "DejaVu Sans"})

fig, (axL, axR) = plt.subplots(1, 2, figsize=(13.5, 6.6))
fig.suptitle("Two ways conversational context helps Hebrew bullying detection",
             fontsize=21, fontweight="bold", y=0.99, color="#1B2A4A")

labels = ["context-blind\n(reads 1 message)", "context-aware\n(reads conversation)"]

# ---- LEFT: false alarms drop (Experiment 1, n=61) ----
fpr = [55.9, 26.5]
bars = axL.bar(labels, fpr, color=[BLIND, AWARE], width=0.62, edgecolor="black", linewidth=1.0)
for b, v in zip(bars, fpr):
    axL.text(b.get_x() + b.get_width()/2, v + 1.4, f"{v:.1f}%", ha="center",
             fontweight="bold", fontsize=18, color="#1B2A4A")
axL.annotate("", xy=(1, 26.5), xytext=(1, 55.9),
             arrowprops=dict(arrowstyle="-|>", color=GOOD, lw=3))
axL.text(0.5, 64, "-29.4 points   (p = 0.002)", color=GOOD, fontweight="bold",
         fontsize=16, ha="center")
axL.set_ylabel("False-alarm rate  (lower = better)", fontsize=15)
axL.set_ylim(0, 70)
axL.set_title("Experiment 1 — cuts FALSE ALARMS\n61 conversations", fontsize=17, color="#1B2A4A")

# ---- RIGHT: harm recall up (Experiment 2, n=143) ----
rec = [58.9, 82.1]
bars2 = axR.bar(labels, rec, color=[BLIND, AWARE], width=0.62, edgecolor="black", linewidth=1.0)
for b, v in zip(bars2, rec):
    axR.text(b.get_x() + b.get_width()/2, v + 1.4, f"{v:.1f}%", ha="center",
             fontweight="bold", fontsize=18, color="#1B2A4A")
axR.annotate("", xy=(1, 82.1), xytext=(1, 58.9),
             arrowprops=dict(arrowstyle="-|>", color=GOOD, lw=3))
axR.text(0.5, 99, "+23 points   (veiled threats 0% -> 100%)", color=GOOD, fontweight="bold",
         fontsize=15, ha="center", va="top")
axR.set_ylabel("Catches real harm  (higher = better)", fontsize=15)
axR.set_ylim(0, 105)
axR.set_title("Experiment 2 — RECOVERS hidden harm\n143 conversations", fontsize=17, color="#1B2A4A")

fig.text(0.5, 0.015,
         "Red = judges one message in isolation (the baseline).   Blue = also reads the previous turns of the chat.",
         ha="center", fontsize=13, style="italic", color="#5B6B7B")
fig.tight_layout(rect=[0, 0.05, 1, 0.95])
path = OUT / "contribution_two_axes.png"
fig.savefig(path, bbox_inches="tight", dpi=200)
print(f"wrote {path}")
