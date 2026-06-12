#!/usr/bin/env python3
"""One presentation 'money graph': the two ways conversational context helps.

Left  : Experiment 1 (per-message) -> context CUTS false alarms (FPR 55.9 -> 26.5).
Right : Experiment 2 (harm-reframe) -> context RECOVERS hidden harm (recall 58.9 -> 82.1).

Renders docs/research_question/plots/contribution_two_axes.png -- a single,
self-explanatory slide图 that ties the whole research story together.
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
AWARE = "#4C78A8"   # context-aware (blue) -> reads the CONVERSATION
GOOD = "#54A24B"
plt.rcParams.update({"font.size": 12, "axes.titleweight": "bold", "figure.dpi": 140,
                     "axes.grid": True, "grid.alpha": .25, "axes.axisbelow": True})

fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 6))
fig.suptitle("Two ways conversational context helps Hebrew bullying detection",
             fontsize=16, fontweight="bold", y=0.98)

# ---- LEFT: false alarms drop (Experiment 1, n=61) ----
labels = ["context-blind\n(reads 1 message)", "context-aware\n(reads conversation)"]
fpr = [55.9, 26.5]
bars = axL.bar(labels, fpr, color=[BLIND, AWARE], width=0.6, edgecolor="black", linewidth=.8)
for b, v in zip(bars, fpr):
    axL.text(b.get_x() + b.get_width()/2, v + 1.2, f"{v:.1f}%", ha="center",
             fontweight="bold", fontsize=13)
axL.annotate("", xy=(1, 26.5), xytext=(1, 55.9),
             arrowprops=dict(arrowstyle="->", color=GOOD, lw=2.5))
axL.text(1.05, 41, "-29.4 pp\np = 0.002 ✓", color=GOOD, fontweight="bold", fontsize=12)
axL.set_ylabel("False-alarm rate (lower = better)")
axL.set_ylim(0, 65)
axL.set_title("Experiment 1 — cuts FALSE ALARMS\n(61 conversations)")

# ---- RIGHT: harm recall up (Experiment 2, n=143) ----
rec = [58.9, 82.1]
bars2 = axR.bar(labels, rec, color=[BLIND, AWARE], width=0.6, edgecolor="black", linewidth=.8)
for b, v in zip(bars2, rec):
    axR.text(b.get_x() + b.get_width()/2, v + 1.2, f"{v:.1f}%", ha="center",
             fontweight="bold", fontsize=13)
axR.annotate("", xy=(1, 82.1), xytext=(1, 58.9),
             arrowprops=dict(arrowstyle="->", color=GOOD, lw=2.5))
axR.text(1.05, 68, "+23 pp\n(veiled threats\n0% → 100%)", color=GOOD, fontweight="bold", fontsize=12)
axR.set_ylabel("Catches real harm (higher = better)")
axR.set_ylim(0, 100)
axR.set_title("Experiment 2 — RECOVERS hidden harm\n(143 conversations)")

fig.text(0.5, 0.01,
         "Red = judges one message in isolation (the baseline).  Blue = also reads the previous turns of the chat.  "
         "Left: context removes false alarms on offensive-LOOKING but innocent messages.  "
         "Right: context catches threats that look harmless alone.",
         ha="center", fontsize=10, style="italic", wrap=True)
fig.tight_layout(rect=[0, 0.04, 1, 0.95])
path = OUT / "contribution_two_axes.png"
fig.savefig(path, bbox_inches="tight")
print(f"wrote {path}")
