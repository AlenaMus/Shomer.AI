#!/usr/bin/env python3
"""Visualize the Context -> False-Positive MVP results as SELF-EXPLANATORY figures.

Reads the runner outputs:
  * docs/research_question/context_fp_mvp_results.json  (aggregate F1/F2 metrics)
  * docs/research_question/context_fp_mvp_results.md     (per-item flag dump table)

and renders, into docs/research_question/plots/:
  * mvp_dashboard.png          - the 6-panel overview
  * fig_fpr.png                - false alarms (headline)        + explanation box
  * fig_accuracy.png           - overall accuracy               + explanation box
  * fig_recall.png             - catching real offensive        + explanation box
  * fig_alerts_per_group.png   - alerts per classification group + explanation box
  * fig_success_per_group.png  - success rate per group         + explanation box
  * fig_fpr_by_category.png    - where the FP drop comes from   + explanation box
  * fig_mcnemar.png            - wins vs costs (significance)    + explanation box

Every individual figure carries a caption that explains the groups, what is
plotted, which direction is "good", and the takeaway -- so it stands alone.
"""
from __future__ import annotations
import json, re, sys, textwrap
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
RQ = ROOT / "docs" / "research_question"
OUT = RQ / "plots"; OUT.mkdir(parents=True, exist_ok=True)

BLIND = "#E45756"   # context-blind  (red)   -> reads ONE message only
AWARE = "#4C78A8"   # context-aware  (blue)  -> reads the CONVERSATION
GOOD  = "#54A24B"
COST  = "#B25400"
plt.rcParams.update({"font.size": 11, "axes.titleweight": "bold", "figure.dpi": 130,
                     "axes.grid": True, "grid.alpha": .25, "axes.axisbelow": True})

# --------------------------------------------------------------------------- #
# Load aggregate metrics + per-item flags                                      #
# --------------------------------------------------------------------------- #
J = json.loads((RQ / "context_fp_mvp_results.json").read_text(encoding="utf-8"))
F1, F2, META = J["f1"], J["f2"], J["meta"]
flagged = lambda c: "🚩" in c
items = []
for line in (RQ / "context_fp_mvp_results.md").read_text(encoding="utf-8").splitlines():
    m = re.match(r"\|\s*([\w-]+)\s*\|\s*([ABC])\s*\|\s*(OFF|ben)\s*\|\s*\w+\s*\|"
                 r"\s*(.+?)→(.+?)\s*\|\s*(.+?)→(.+?)\s*\|", line)
    if not m:
        continue
    _id, cat, gold, f2b, f2a, f1b, f1a = m.groups()
    items.append({"id": _id, "cat": cat, "off": gold == "OFF",
                  "f1_blind": flagged(f1b), "f1_aware": flagged(f1a)})
assert len(items) == META["n_items"], f"parsed {len(items)} != {META['n_items']}"

G_A, G_B, G_CB, G_CO = "A\ncontext-flip", "B\nhidden threat", "C-benign\ncontrol", "C-offensive\ncontrol"
GROUPS = [G_A, G_B, G_CB, G_CO]
WANT_ALERT = {G_A: False, G_B: True, G_CB: False, G_CO: True}
def group(it):
    if it["cat"] == "A": return G_A
    if it["cat"] == "B": return G_B
    return G_CO if it["off"] else G_CB

g_n = {g: 0 for g in GROUPS}; g_alert_b = dict(g_n); g_alert_a = dict(g_n)
g_ok_b = dict(g_n); g_ok_a = dict(g_n)
for it in items:
    g = group(it); g_n[g] += 1
    g_alert_b[g] += it["f1_blind"]; g_alert_a[g] += it["f1_aware"]
    g_ok_b[g] += (it["f1_blind"] == it["off"]); g_ok_a[g] += (it["f1_aware"] == it["off"])
acc_b = sum(g_ok_b.values()) / len(items) * 100
acc_a = sum(g_ok_a.values()) / len(items) * 100

# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def label_bars(ax, bars, fmt="{:.0f}"):
    for b in bars:
        h = b.get_height()
        ax.annotate(fmt.format(h), (b.get_x()+b.get_width()/2, h), ha="center", va="bottom",
                    fontsize=10, fontweight="bold", xytext=(0, 2), textcoords="offset points")

def caption(fig, text, height=0.30):
    """Reserve bottom space and draw a wrapped explanation box."""
    fig.subplots_adjust(bottom=height)
    fig.text(0.5, 0.015, text, ha="center", va="bottom", fontsize=9.6, linespacing=1.45,
             bbox=dict(boxstyle="round,pad=0.6", fc="#F4F6FA", ec="#C7CEDB"))

LEGEND = ("🟥 context-blind = system reads ONE message    "
          "🟦 context-aware = system also reads the CONVERSATION")

# --------------------------------------------------------------------------- #
# 1 — FPR headline                                                             #
# --------------------------------------------------------------------------- #
fig, ax = plt.subplots(figsize=(8.2, 6.6))
bars = ax.bar(["context-blind\n(one message)", "context-aware\n(reads conversation)"],
              [F1["fpr_blind"]*100, F1["fpr_aware"]*100], color=[BLIND, AWARE],
              edgecolor="white", width=.6)
label_bars(ax, bars, "{:.1f}%")
ax.set_title("FALSE ALARMS  —  the headline result"); ax.set_ylabel("False-Positive Rate (%)"); ax.set_ylim(0, 70)
ax.annotate(f"−{F1['delta_fpr_pp']:.1f} pp\np={F1['fpr_mcnemar']['p']:.3f} ✓", (0.5, .80),
            xycoords="axes fraction", ha="center", fontsize=12, fontweight="bold", color=GOOD,
            bbox=dict(boxstyle="round", fc="#EAF5E8", ec=GOOD))
caption(fig,
    "WHAT THIS SHOWS:  False-Positive Rate = of the 34 HARMLESS messages, the % the system wrongly\n"
    "raised an alert on.   LOWER IS BETTER  (fewer false alarms to the parent).\n"
    "RESULT:  reading the conversation cut false alarms from 55.9% to 26.5% — nearly in half — and the\n"
    "drop is statistically significant (McNemar p=0.002).  This is the core thesis result.")
fig.savefig(OUT / "fig_fpr.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

# --------------------------------------------------------------------------- #
# 2 — overall accuracy                                                         #
# --------------------------------------------------------------------------- #
fig, ax = plt.subplots(figsize=(8.2, 6.6))
bars = ax.bar(["context-blind", "context-aware"], [acc_b, acc_a], color=[BLIND, AWARE],
              edgecolor="white", width=.6)
label_bars(ax, bars, "{:.1f}%")
ax.set_title("OVERALL ACCURACY"); ax.set_ylabel("% of all 61 messages decided correctly"); ax.set_ylim(0, 100)
ax.annotate(f"+{acc_a-acc_b:.1f} pp", (0.5, .82), xycoords="axes fraction", ha="center",
            fontsize=13, fontweight="bold", color=GOOD)
caption(fig,
    "WHAT THIS SHOWS:  of ALL 61 messages, the % the system decided correctly = alert on a truly-offensive\n"
    "message AND stay silent on a harmless one.   HIGHER IS BETTER.\n"
    "RESULT:  reading the conversation raised overall accuracy from 55.7% to 68.9% (+13 points).")
fig.savefig(OUT / "fig_accuracy.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

# --------------------------------------------------------------------------- #
# 3 — recall (the trade-off)                                                   #
# --------------------------------------------------------------------------- #
fig, ax = plt.subplots(figsize=(8.2, 6.6))
bars = ax.bar(["context-blind", "context-aware"],
              [F1["recall_blind"]*100, F1["recall_aware"]*100], color=[BLIND, AWARE],
              edgecolor="white", width=.6)
label_bars(ax, bars, "{:.1f}%")
ax.set_title("CATCHING REAL OFFENSIVE MESSAGES  (the trade-off)")
ax.set_ylabel("Recall (% of 27 offensive caught)"); ax.set_ylim(0, 100)
ax.annotate(f"{F1['delta_recall_pp']:+.1f} pp", (0.5, .82), xycoords="axes fraction", ha="center",
            fontsize=13, fontweight="bold", color=COST)
caption(fig,
    "WHAT THIS SHOWS:  Recall = of the 27 truly-OFFENSIVE messages, the % the system correctly caught.\n"
    "HIGHER IS BETTER.   RESULT:  a small drop (−7 pp). The loss is ENTIRELY on clear-cut abusive 'control'\n"
    "items the agent over-forgave (it asks 'is it a real THREAT?', so it lets non-violent abuse pass).\n"
    "On the hard 'hidden-threat' group, recall actually ROSE +14 pp.  The drop is a known, fixable prompt issue.")
fig.savefig(OUT / "fig_recall.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

# --------------------------------------------------------------------------- #
# 4 — alerts per classification group                                          #
# --------------------------------------------------------------------------- #
fig, ax = plt.subplots(figsize=(11, 7))
x = np.arange(len(GROUPS)); w = .38
b1 = ax.bar(x-w/2, [g_alert_b[g] for g in GROUPS], w, color=BLIND, edgecolor="white", label="context-blind")
b2 = ax.bar(x+w/2, [g_alert_a[g] for g in GROUPS], w, color=AWARE, edgecolor="white", label="context-aware")
label_bars(ax, b1); label_bars(ax, b2)
ax.set_title("ALERTS FIRED PER CLASSIFICATION GROUP"); ax.set_ylabel("# of messages flagged as offensive")
labs = []
for g in GROUPS:
    want = "harmless → fewer=better ↓" if not WANT_ALERT[g] else "offensive → more=better ↑"
    labs.append(f"{g}\n(n={g_n[g]})\n{want}")
ax.set_xticks(x); ax.set_xticklabels(labs, fontsize=9); ax.legend(fontsize=10, loc="upper right")
ax.set_ylim(0, max(max(g_alert_b.values()), max(g_alert_a.values()))+4)
caption(fig,
    "THE FOUR GROUPS (each tests something different):\n"
    "• A context-flip — looks offensive ALONE but is harmless IN CONTEXT (e.g. 'shut up' between friends gaming) → want NO alert.\n"
    "• B hidden threat — looks harmless ALONE but is bullying IN CONTEXT (e.g. a jab inside a pile-on) → want an alert.\n"
    "• C-benign control — clearly harmless in any reading → want NO alert.    • C-offensive control — clearly offensive in any reading → want an alert.\n"
    "HOW TO READ:  on harmless groups (A, C-benign) a lower BLUE bar = fewer false alarms = good.  On offensive groups (B, C-offensive)\n"
    "a higher BLUE bar = more true catches = good.   Context cut alerts on A (15→7) and C-benign (4→2), and caught more in B (8→10).",
    height=0.34)
fig.savefig(OUT / "fig_alerts_per_group.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

# --------------------------------------------------------------------------- #
# 5 — success rate per group                                                   #
# --------------------------------------------------------------------------- #
fig, ax = plt.subplots(figsize=(11, 7))
sb = [g_ok_b[g]/g_n[g]*100 for g in GROUPS]; sa = [g_ok_a[g]/g_n[g]*100 for g in GROUPS]
b1 = ax.bar(x-w/2, sb, w, color=BLIND, edgecolor="white", label="context-blind")
b2 = ax.bar(x+w/2, sa, w, color=AWARE, edgecolor="white", label="context-aware")
label_bars(ax, b1, "{:.0f}%"); label_bars(ax, b2, "{:.0f}%")
ax.set_title("SUCCESS RATE PER GROUP   (HIGHER IS BETTER for every group)")
ax.set_ylabel("% of messages in the group decided correctly"); ax.set_ylim(0, 115)
ax.set_xticks(x); ax.set_xticklabels([f"{g}\n(n={g_n[g]})" for g in GROUPS], fontsize=9); ax.legend(fontsize=10)
caption(fig,
    "WHAT THIS SHOWS:  within each group, the % of messages the system decided correctly\n"
    "(alert on offensive, silent on harmless).   HIGHER IS BETTER for ALL four groups.\n"
    "RESULT:  context-aware (blue) wins on 3 of 4 groups — A 35→70, C-benign 64→82, B 57→71.\n"
    "It loses only on C-offensive (85→54) — the same over-forgiving-abuse issue from the recall chart.")
fig.savefig(OUT / "fig_success_per_group.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

# --------------------------------------------------------------------------- #
# 6 — FPR by category (mechanism)                                              #
# --------------------------------------------------------------------------- #
fig, ax = plt.subplots(figsize=(8.6, 6.8))
cats = ["A: context-flip\n(n=23 harmless)", "C-benign control\n(n=11 harmless)"]
fb = [F1["cat_fpr"]["A"]["blind"]*100, F1["cat_fpr"]["C"]["blind"]*100]
fa = [F1["cat_fpr"]["A"]["aware"]*100, F1["cat_fpr"]["C"]["aware"]*100]
xx = np.arange(2)
b1 = ax.bar(xx-w/2, fb, w, color=BLIND, edgecolor="white", label="context-blind")
b2 = ax.bar(xx+w/2, fa, w, color=AWARE, edgecolor="white", label="context-aware")
label_bars(ax, b1, "{:.0f}%"); label_bars(ax, b2, "{:.0f}%")
ax.set_xticks(xx); ax.set_xticklabels(cats); ax.set_ylabel("False-Positive Rate (%)"); ax.set_ylim(0, 85)
ax.set_title("WHERE THE FALSE-ALARM DROP COMES FROM"); ax.legend()
for i, d in enumerate([F1["cat_fpr"]["A"]["delta_pp"], F1["cat_fpr"]["C"]["delta_pp"]]):
    ax.annotate(f"−{d:.0f}pp", (i, max(fb[i], fa[i])+4), ha="center", fontweight="bold", color=GOOD)
caption(fig,
    "WHAT THIS SHOWS:  the false-alarm drop split by group.  The BIG win (−35 pp) is on the\n"
    "context-flip group — exactly the messages whose meaning depends on context.  This proves\n"
    "the improvement is the MECHANISM (reading context), not the system just alerting less overall.")
fig.savefig(OUT / "fig_fpr_by_category.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

# --------------------------------------------------------------------------- #
# 7 — McNemar pairs                                                            #
# --------------------------------------------------------------------------- #
fig, ax = plt.subplots(figsize=(8.2, 6.6))
c = F1["fpr_mcnemar"]["c"]; b = F1["fpr_mcnemar"]["b"]
bars = ax.bar(["false alarms FIXED\nby context", "false alarms ADDED\nby context"], [c, b],
              color=[GOOD, BLIND], edgecolor="white", width=.55)
label_bars(ax, bars)
ax.set_title(f"WHY IT'S STATISTICALLY SIGNIFICANT  (p={F1['fpr_mcnemar']['p']:.4f})")
ax.set_ylabel("# of harmless messages"); ax.set_ylim(0, max(c, b)+3)
caption(fig,
    "WHAT THIS SHOWS:  comparing the two systems message-by-message on the harmless items.\n"
    "Context FIXED 10 false alarms and ADDED 0 new ones — an entirely one-sided improvement.\n"
    "That 10-vs-0 split is why the result is significant (very unlikely to be luck).")
fig.savefig(OUT / "fig_mcnemar.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

# --------------------------------------------------------------------------- #
# DASHBOARD (overview)                                                         #
# --------------------------------------------------------------------------- #
fig = plt.figure(figsize=(16, 10))
fig.suptitle("Does reading the conversation reduce false alarms in Hebrew bullying detection?\n"
             "context-blind classifier  vs.  classifier + Context-Agent   (MVP, n=61)",
             fontsize=15, fontweight="bold")
gs = fig.add_gridspec(2, 3, hspace=.46, wspace=.28, top=.86, bottom=.14)
def mini(ax, vals, title, ylab, ymax, delta, dcol):
    bars = ax.bar(["blind", "aware"], vals, color=[BLIND, AWARE], edgecolor="white", width=.6)
    label_bars(ax, bars, "{:.1f}%"); ax.set_title(title); ax.set_ylabel(ylab); ax.set_ylim(0, ymax)
    ax.annotate(delta, (.5, .82), xycoords="axes fraction", ha="center", fontsize=11,
                fontweight="bold", color=dcol)
mini(fig.add_subplot(gs[0,0]), [F1["fpr_blind"]*100, F1["fpr_aware"]*100],
     "False alarms (lower=better)", "FPR %", 70, f"−{F1['delta_fpr_pp']:.1f}pp  p=0.002 ✓", GOOD)
mini(fig.add_subplot(gs[0,1]), [acc_b, acc_a], "Accuracy (higher=better)", "%", 100, f"+{acc_a-acc_b:.1f}pp", GOOD)
mini(fig.add_subplot(gs[0,2]), [F1["recall_blind"]*100, F1["recall_aware"]*100],
     "Recall (higher=better)", "%", 100, f"{F1['delta_recall_pp']:+.1f}pp", COST)
ax = fig.add_subplot(gs[1,0:2])
b1 = ax.bar(x-w/2, [g_alert_b[g] for g in GROUPS], w, color=BLIND, edgecolor="white", label="context-blind")
b2 = ax.bar(x+w/2, [g_alert_a[g] for g in GROUPS], w, color=AWARE, edgecolor="white", label="context-aware")
label_bars(ax, b1); label_bars(ax, b2); ax.set_title("Alerts per group"); ax.set_ylabel("# alerts")
ax.set_xticks(x); ax.set_xticklabels(
    [f"{g}\nn={g_n[g]} · {'↓ good' if not WANT_ALERT[g] else '↑ good'}" for g in GROUPS], fontsize=8.5)
ax.legend(fontsize=9)
ax = fig.add_subplot(gs[1,2])
b1 = ax.bar(x-w/2, sb, w, color=BLIND, edgecolor="white"); b2 = ax.bar(x+w/2, sa, w, color=AWARE, edgecolor="white")
label_bars(ax, b1, "{:.0f}"); label_bars(ax, b2, "{:.0f}")
ax.set_title("Success rate per group"); ax.set_ylabel("% correct"); ax.set_ylim(0, 115)
ax.set_xticks(x); ax.set_xticklabels([g.split(chr(10))[0] for g in GROUPS], fontsize=9)
fig.text(0.5, 0.055, LEGEND.replace("🟥","[red] ").replace("🟦","   [blue] "), ha="center", fontsize=10)
fig.text(0.5, 0.02,
    "MVP / feasibility — eval set partly synthetic/authored (real screenshots + curated humor + generated conversations); "
    "magnitude optimistic, real-gold eval is future work.", ha="center", fontsize=8.5, style="italic", color="#888")
fig.savefig(OUT / "mvp_dashboard.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

print("Group sizes:", {g.split(chr(10))[0]: g_n[g] for g in GROUPS})
print(f"Accuracy {acc_b:.1f}->{acc_a:.1f} | FPR {F1['fpr_blind']*100:.1f}->{F1['fpr_aware']*100:.1f} "
      f"| Recall {F1['recall_blind']*100:.1f}->{F1['recall_aware']*100:.1f}")
print("Saved 8 figures to", OUT)
