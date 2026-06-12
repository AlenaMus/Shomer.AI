#!/usr/bin/env python3
"""Generate high-resolution, English-labelled visual assets for the Shomer.AI deck.

  assets/hero_shield.png      - title-slide guardian illustration (no text)
  assets/dataset_classes.png  - 5-class train distribution (donut)
  assets/dataset_sources.png  - provenance of training data (bars)
  assets/model_quality.png    - DictaBERT vs off-the-shelf + per-class F1 (2 panels)

All labels are English/numeric on purpose (Hebrew lives in the slide text, not the images).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, PathPatch, Circle
from matplotlib.path import Path as MPath

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets"; OUT.mkdir(parents=True, exist_ok=True)
DPI = 220
plt.rcParams.update({"font.family": "DejaVu Sans"})

NAVY = "#1B2A4A"; TEAL = "#028090"; MINT = "#02C39A"; ICE = "#CADCFC"
CORAL = "#E45756"; GOLD = "#F2B705"; BLIND = "#E45756"; AWARE = "#1C6FA8"

# ---------------------------------------------------------------- hero shield
fig, ax = plt.subplots(figsize=(6, 6), dpi=DPI)
ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off"); fig.patch.set_alpha(0)
ax.add_patch(Circle((5, 5.2), 4.6, color=TEAL, alpha=0.08))
ax.add_patch(Circle((5, 5.2), 3.7, color=TEAL, alpha=0.10))
sx, sy = 5.0, 5.4
verts = [(sx, sy+3.0), (sx+2.4, sy+2.1), (sx+2.4, sy-0.6), (sx, sy-3.0),
         (sx-2.4, sy-0.6), (sx-2.4, sy+2.1), (sx, sy+3.0)]
codes = [MPath.MOVETO] + [MPath.LINETO]*5 + [MPath.CLOSEPOLY]
ax.add_patch(PathPatch(MPath(verts, codes), facecolor=NAVY, edgecolor=TEAL, lw=6, joinstyle="round"))
verts2 = [(sx, sy+2.5), (sx+1.95, sy+1.75), (sx+1.95, sy-0.45), (sx, sy-2.45),
          (sx-1.95, sy-0.45), (sx-1.95, sy+1.75), (sx, sy+2.5)]
ax.add_patch(PathPatch(MPath(verts2, codes), facecolor=TEAL, edgecolor="none", alpha=0.18))
ax.plot([sx-1.1, sx-0.25, sx+1.35], [sy+0.1, sy-1.0, sy+1.5],
        color=MINT, lw=14, solid_capstyle="round", solid_joinstyle="round")
def bubble(cx, cy, w, h, color, tail_dir=1):
    ax.add_patch(FancyBboxPatch((cx, cy), w, h, boxstyle="round,pad=0.02,rounding_size=0.35",
                 facecolor=color, edgecolor="white", lw=2.5))
    tx = cx + (0.35 if tail_dir > 0 else w-0.35)
    ax.add_patch(plt.Polygon([(tx, cy+0.05), (tx+0.45*tail_dir, cy-0.45), (tx+0.55*tail_dir, cy+0.1)],
                 closed=True, facecolor=color, edgecolor="none"))
bubble(0.5, 7.4, 2.4, 1.3, ICE, 1)
for dx in [0.7, 1.25, 1.8]:
    ax.add_patch(Circle((0.5+dx, 8.05), 0.12, color=NAVY))
bubble(7.0, 1.4, 2.4, 1.3, GOLD, -1)
ax.text(8.2, 2.05, "!", ha="center", va="center", fontsize=30, fontweight="bold", color=NAVY)
fig.savefig(OUT / "hero_shield.png", transparent=True, bbox_inches="tight", dpi=DPI)
plt.close(fig); print("wrote hero_shield.png")

# ---------------------------------------------------------------- class donut
classes = ["non-offensive", "hate", "pornographic", "violence", "abusive"]
counts = [3856, 1035, 1029, 1028, 1026]
cols = [TEAL, CORAL, "#8E5572", GOLD, "#C44E00"]
fig, ax = plt.subplots(figsize=(6.4, 5.4), dpi=DPI)
w, _, _ = ax.pie(counts, colors=cols, startangle=90, counterclock=False,
                 wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2),
                 autopct=lambda p: f"{p:.0f}%", pctdistance=0.79,
                 textprops=dict(color="white", fontweight="bold", fontsize=14))
ax.text(0, 0, "7,974\ntrain rows", ha="center", va="center", fontsize=18, fontweight="bold", color=NAVY)
ax.legend(w, [f"{c}  ({n:,})" for c, n in zip(classes, counts)],
          loc="lower center", bbox_to_anchor=(0.5, -0.16), ncol=2, frameon=False, fontsize=12.5)
ax.set_title("Training set — 5 classes", fontweight="bold", color=NAVY, fontsize=17)
fig.savefig(OUT / "dataset_classes.png", transparent=True, bbox_inches="tight", dpi=DPI)
plt.close(fig); print("wrote dataset_classes.png")

# ---------------------------------------------------------------- sources bars
prov = {"Real Hebrew\n(SinaLab tweets)": 3924, "Gemini-synthesized\nHebrew": 2001,
        "Other synthetic": 856, "Real Hebrew\n(textDetox)": 645, "Translated EN→HE\n(Jigsaw)": 548}
labels = list(prov.keys()); vals = list(prov.values())
pct = [v/sum(vals)*100 for v in vals]
bcols = [TEAL, MINT, "#7FB7BE", "#1C7293", GOLD]
fig, ax = plt.subplots(figsize=(7.6, 5.2), dpi=DPI)
y = np.arange(len(labels))[::-1]
bars = ax.barh(y, pct, color=bcols, edgecolor="white", height=0.62)
for b, p, v in zip(bars, pct, vals):
    ax.text(p+0.9, b.get_y()+b.get_height()/2, f"{p:.0f}%  ({v:,})", va="center",
            fontsize=13, fontweight="bold", color=NAVY)
ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=13)
ax.set_xlim(0, 64); ax.set_xlabel("share of training rows (%)", color=NAVY, fontsize=13)
ax.set_title("Where the training data comes from", fontweight="bold", color=NAVY, fontsize=17)
for s in ["top", "right"]: ax.spines[s].set_visible(False)
ax.grid(axis="x", alpha=0.2)
fig.tight_layout()
fig.savefig(OUT / "dataset_sources.png", transparent=True, bbox_inches="tight", dpi=DPI)
plt.close(fig); print("wrote dataset_sources.png")

# ---------------------------------------------------------------- model quality (2 panels)
fig, (axA, axB) = plt.subplots(1, 2, figsize=(13.5, 5.6), dpi=DPI)
fig.suptitle("DictaBERT model quality", fontsize=20, fontweight="bold", color=NAVY, y=1.0)

# Panel A: DictaBERT vs off-the-shelf (macro-F1)
mlabels = ["Ollama\n(off-the-shelf)", "DictaBERT\n(ours, fine-tuned)"]
f1 = [0.373, 0.836]
bars = axA.bar(mlabels, f1, color=["#9AA5B1", TEAL], width=0.6, edgecolor="black", linewidth=1.0)
for b, v in zip(bars, f1):
    axA.text(b.get_x()+b.get_width()/2, v+0.02, f"{v:.3f}", ha="center", fontweight="bold",
             fontsize=18, color=NAVY)
axA.set_ylim(0, 1.0)
axA.set_ylabel("macro-F1  (higher = better)", fontsize=14)
axA.set_title("Accuracy vs. off-the-shelf model\n(same 445 Hebrew test rows)", fontsize=15, color=NAVY)
axA.text(0.5, 0.62, "2.4x more accurate\n424x faster", ha="center", fontsize=15, fontweight="bold",
         color="#0E9F6E", bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#0E9F6E", lw=1.5))
axA.grid(axis="y", alpha=0.2); [axA.spines[s].set_visible(False) for s in ["top", "right"]]

# Panel B: per-class F1
pc = {"non-offensive": 0.931, "pornographic": 0.970, "abusive": 0.831, "hate": 0.739, "violence": 0.712}
pl = list(pc.keys()); pv = list(pc.values())
pcols = [TEAL, "#8E5572", "#C44E00", CORAL, GOLD]
yb = np.arange(len(pl))[::-1]
bars = axB.barh(yb, pv, color=pcols, edgecolor="white", height=0.6)
for b, v in zip(bars, pv):
    axB.text(v+0.012, b.get_y()+b.get_height()/2, f"{v:.2f}", va="center", fontweight="bold",
             fontsize=14, color=NAVY)
axB.set_yticks(yb); axB.set_yticklabels(pl, fontsize=13)
axB.set_xlim(0, 1.05); axB.set_xlabel("F1 score per class", fontsize=14)
axB.set_title("Performance on each of the 5 classes", fontsize=15, color=NAVY)
axB.grid(axis="x", alpha=0.2); [axB.spines[s].set_visible(False) for s in ["top", "right"]]

fig.tight_layout(rect=[0, 0, 1, 0.95])
fig.savefig(OUT / "model_quality.png", transparent=True, bbox_inches="tight", dpi=DPI)
plt.close(fig); print("wrote model_quality.png")
