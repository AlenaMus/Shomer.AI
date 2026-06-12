#!/usr/bin/env python3
"""Visualize the HARM-CONTEXT reframe results (docs/research_question/harm_context_results.json)
into self-explanatory annotated figures in docs/research_question/plots_harm/.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
RQ = ROOT / "docs" / "research_question"
OUT = RQ / "plots_harm"; OUT.mkdir(parents=True, exist_ok=True)
J = json.loads((RQ / "harm_context_results.json").read_text(encoding="utf-8"))
H, O, PG, META = J["harm_target"], J["offensive_target"], J["per_group"], J["meta"]

BLIND, AWARE, GOOD, COST = "#E45756", "#4C78A8", "#54A24B", "#B25400"
plt.rcParams.update({"font.size": 11, "axes.titleweight": "bold", "figure.dpi": 130,
                     "axes.grid": True, "grid.alpha": .25, "axes.axisbelow": True})

def label(ax, bars, fmt="{:.0f}"):
    for b in bars:
        h = b.get_height()
        ax.annotate(fmt.format(h), (b.get_x()+b.get_width()/2, h), ha="center", va="bottom",
                    fontsize=10, fontweight="bold", xytext=(0, 2), textcoords="offset points")

def caption(fig, text, h=0.30):
    fig.subplots_adjust(bottom=h)
    fig.text(0.5, 0.015, text, ha="center", va="bottom", fontsize=9.6, linespacing=1.45,
             bbox=dict(boxstyle="round,pad=0.6", fc="#F4F6FA", ec="#C7CEDB"))

# 5 groups after the self_or_report relabel (victim_disclosure -> alert-worthy;
# self_deprecation folded into benign -> not alert-worthy).
SC = J["scores"]
GROUPS = ["harmful", "veiled_harmful", "victim_disclosure", "offensive_not_harmful", "benign"]
GLAB = {"harmful": "Harmful\n(should alert)", "veiled_harmful": "Veiled harmful\n(should alert)",
        "victim_disclosure": "Child disclosing\nabuse (should alert)",
        "offensive_not_harmful": "Offensive but\nNOT harmful\n(should NOT alert)",
        "benign": "Benign chat\n(should NOT alert)"}
WANT = {"harmful": True, "veiled_harmful": True, "victim_disclosure": True,
        "offensive_not_harmful": False, "benign": False}
PG = {g: {"n": 0, "alert_b": 0, "alert_a": 0, "ok_b": 0, "ok_a": 0} for g in GROUPS}
for s in SC:
    g = s["group"]; d = PG[g]; d["n"] += 1
    d["alert_b"] += s["blind"]; d["alert_a"] += s["aware"]
    d["ok_b"] += (s["blind"] == s["alert_worthy"]); d["ok_a"] += (s["aware"] == s["alert_worthy"])

# --- 1. headline: FPR + recall under the HARM target -------------------------- #
fig, axes = plt.subplots(1, 2, figsize=(13, 6.4))
ax = axes[0]
bars = ax.bar(["context-blind", "context-aware"], [H["fpr_blind"]*100, H["fpr_aware"]*100],
              color=[BLIND, AWARE], edgecolor="white", width=.6)
label(ax, bars, "{:.1f}%"); ax.set_title("False alarms on NON-harmful messages"); ax.set_ylabel("FPR %")
ax.set_ylim(0, max(H["fpr_blind"]*100, 10)*1.3+5)
ax.annotate(f"−{H['fpr_delta_pp']:.1f}pp\nfixed={H['fpr_c']} added={H['fpr_b']}  p={H['fpr_p']:.3f}",
            (.5, .8), xycoords="axes fraction", ha="center", fontweight="bold", color=GOOD,
            bbox=dict(boxstyle="round", fc="#EAF5E8", ec=GOOD))
ax = axes[1]
bars = ax.bar(["context-blind", "context-aware"], [H["rec_blind"]*100, H["rec_aware"]*100],
              color=[BLIND, AWARE], edgecolor="white", width=.6)
label(ax, bars, "{:.1f}%"); ax.set_title("Recall on genuinely HARMFUL situations"); ax.set_ylabel("Recall %")
ax.set_ylim(0, 100)
ax.annotate(f"{H['rec_delta_pp']:+.1f}pp", (.5, .85), xycoords="axes fraction", ha="center",
            fontweight="bold", color=GOOD if H["rec_delta_pp"] >= 0 else COST)
fig.suptitle("HARM-CONTEXT reframe — alert on harmful SITUATIONS, not on every offensive word", fontweight="bold")
caption(fig,
    "Target = 'alert_worthy' (is this part of a harmful situation?).   LEFT: of the messages that should NOT alert\n"
    "(friendly banter, one-off jabs, benign chat), the % wrongly alerted — LOWER IS BETTER.   RIGHT: of the genuinely\n"
    "harmful situations, the % caught — HIGHER IS BETTER.   Reading the conversation should cut false alarms AND keep recall.",
    h=0.26)
fig.savefig(OUT / "harm_headline.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

# --- 2. THE reframe chart: same 0 alerts, two verdicts ------------------------ #
onh = PG["offensive_not_harmful"]; n_onh = onh["n"]; alerts_onh = onh["alert_a"]
old_recall = alerts_onh / n_onh * 100          # OLD: these "should" alarm -> recall
new_correct = (n_onh - alerts_onh) / n_onh * 100  # NEW: these should NOT alarm -> specificity
fig, ax = plt.subplots(figsize=(9.5, 6.6))
bars = ax.bar(["OLD target:\n'alarm on EVERY\noffensive message'\n→ scored as RECALL",
               "NEW target:\n'alarm on HARMFUL\ncontext only'\n→ scored as CORRECT"],
              [old_recall, new_correct], color=["#9D7660", AWARE], edgecolor="white", width=.55)
label(ax, bars, "{:.0f}%")
ax.set_ylabel(f"% on the {n_onh} 'offensive-but-not-harmful' messages"); ax.set_ylim(0, 115)
ax.set_title("SAME system, SAME 0 alerts on banter — two definitions of 'correct'")
caption(fig,
    f"On the {n_onh} offensive-but-NOT-harmful messages (friendly banter, one-off jabs, affectionate slang), the\n"
    f"context-aware system fired {alerts_onh} alerts.   If you DEMAND an alarm on every offensive message (OLD), that looks\n"
    f"like {old_recall:.0f}% recall — a failure.   If you only want alarms on HARMFUL situations (NEW), it is {new_correct:.0f}% correct.\n"
    "Identical behavior, opposite verdict — and the NEW definition is what a parent actually wants.")
fig.savefig(OUT / "harm_reframe_oldvsnew.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

# --- 3. alerts per group ------------------------------------------------------ #
fig, ax = plt.subplots(figsize=(13.5, 7))
x = np.arange(len(GROUPS)); w = .38
ab = [PG[g]["alert_b"] for g in GROUPS]; aa = [PG[g]["alert_a"] for g in GROUPS]
b1 = ax.bar(x-w/2, ab, w, color=BLIND, edgecolor="white", label="context-blind")
b2 = ax.bar(x+w/2, aa, w, color=AWARE, edgecolor="white", label="context-aware")
label(ax, b1); label(ax, b2)
ax.set_title("Alerts fired per group"); ax.set_ylabel("# alerts")
ax.set_xticks(x)
ax.set_xticklabels([f"{GLAB[g]}\n(n={PG[g]['n']}) {'↑ good' if WANT[g] else '↓ good'}" for g in GROUPS], fontsize=8.5)
ax.legend(fontsize=10)
caption(fig,
    "FIVE GROUPS:  Harmful = pile-on / threat / coercion / exclusion / doxxing.  Veiled harmful = looks innocent alone but "
    "continues a threat.  Child disclosing abuse = a kid reporting being bullied (all 3 → should alert).\n"
    "Offensive-but-NOT-harmful = friendly banter / one-off jab / affectionate slang.  Benign = ordinary chat (both → should NOT alert).\n"
    "On 'should-alert' groups a higher BLUE bar is better; on 'should-NOT-alert' groups a lower BLUE bar is better.", h=0.30)
fig.savefig(OUT / "harm_alerts_per_group.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

# --- 4. success rate per group ------------------------------------------------ #
fig, ax = plt.subplots(figsize=(13.5, 7))
sb = [PG[g]["ok_b"]/PG[g]["n"]*100 if PG[g]["n"] else 0 for g in GROUPS]
sa = [PG[g]["ok_a"]/PG[g]["n"]*100 if PG[g]["n"] else 0 for g in GROUPS]
b1 = ax.bar(x-w/2, sb, w, color=BLIND, edgecolor="white", label="context-blind")
b2 = ax.bar(x+w/2, sa, w, color=AWARE, edgecolor="white", label="context-aware")
label(ax, b1, "{:.0f}%"); label(ax, b2, "{:.0f}%")
ax.set_title("Success rate per group (higher = better, every group)"); ax.set_ylabel("% correct"); ax.set_ylim(0, 115)
ax.set_xticks(x); ax.set_xticklabels([f"{GLAB[g]}\n(n={PG[g]['n']})" for g in GROUPS], fontsize=8.5); ax.legend(fontsize=10)
caption(fig, "Within each group, the % of messages decided correctly (alert on harmful, stay silent on the rest).")
fig.savefig(OUT / "harm_success_per_group.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

print("HARM target:  FPR %.1f->%.1f (-%.1fpp)  Recall %.1f->%.1f (%+.1fpp)" % (
    H["fpr_blind"]*100, H["fpr_aware"]*100, H["fpr_delta_pp"],
    H["rec_blind"]*100, H["rec_aware"]*100, H["rec_delta_pp"]))
print("Saved 4 figures to", OUT)
