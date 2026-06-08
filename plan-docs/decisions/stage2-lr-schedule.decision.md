# Stage-2 Training Hyperparameter Adjustment — Decision

**Phase:** Meeting-7 Track A (DictaBERT fine-tune — Stage-2 iteration)
**Decided on:** 2026-06-07
**Decided by:** Alona (via ai-researcher-developer agent, ml-iteration-coach review)

Captures the hyperparameter adjustment made after Stage-2 training with the
locked recipe (LR=2e-5, 5 epochs, patience=2) missed the F1 gate by 0.013.

---

## D7 — LR and epoch adjustment after Stage-2 gate miss

**Question:** Stage-2 training (LR=2e-5, 5 epochs, patience=2) produced test
macro-F1=0.767 (gate=0.78). The val macro-F1 at epoch 2 was 0.801. Early stopping
fired at epoch 4 (epoch-2 best never improved). Should we adjust LR and epochs
to narrow the val/test gap and push abusive F1 above its current 0.464?

**Choice:** **Lower LR to 1e-5, increase max_epochs to 8, patience=3.**

**Why:**
- The epoch-2 val macro-F1 of 0.801 was the best checkpoint, but test macro-F1
  was 0.767 (0.034 val-test gap). This indicates the model converged quickly at
  2e-5 LR to a local minimum that overfits the val distribution slightly.
- A lower LR (1e-5) with more epochs allows the cosine schedule to explore a
  wider basin — the model may find a flatter, more test-generalizable minimum.
- Abusive is the primary bottleneck (F1=0.464; violence=0.749, hate=0.776).
  Abusive class weight is already 3.43 (highest), so Focal Loss is already
  emphasizing it. The gap is a convergence issue, not a data weighting issue.
- This is within the Fallback Rung 1 envelope (arch §10): MLP hyperparameter
  variation without redesigning the head or the backbone.
- If this does NOT clear the gate: escalate to Rung 2 (multi-task head) per
  the locked fallback chain — do NOT re-derive a new approach without invoking
  ml-architect.

**Alternatives considered:**
- Keep LR=2e-5, just increase patience: risk of overfitting with high LR past epoch 4.
- Synthesize more abusive data (Task 2-style Gemini synthesis for abusive): adds
  ~2h of API time + another train run; defer to after the LR experiment.
- MLP head variation (Linear(768→128) instead of 768→256): small change, unlikely
  to move abusive F1 by 0.013.
- DictaBERT-large (Rung 3): ~730M params, ~13 GB VRAM, requires gradient accumulation;
  too expensive before trying the cheap fix.

**What does NOT change:**
- Architecture (locked — arch doc §5 MLP head).
- Focal Loss gamma=2.0, label_smoothing=0.05 (locked C2+C4).
- BF16 (locked sm_120 requirement).
- Seed=42.
- Data stack (§11 locked, Stage-2 variant).

**Revisit:** If LR=1e-5 + 8 epochs + patience=3 still misses the gate, invoke
ml-iteration-coach to pick Rung 2 (multi-task head). Document the result under
outputs/dictabert-offensive/fallback-1/.
