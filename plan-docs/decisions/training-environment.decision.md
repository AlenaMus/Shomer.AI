# Training environment — Decisions

**Phase:** Meeting-5 Track A (DictaBERT fine-tune) — environment setup
**Decided on:** 2026-06-04
**Decided by:** Alona, with options presented by Claude

Captures the environment-setup decisions made just before kicking off Track A
(DictaBERT fine-tune). The trigger was the verified failure of the previously
installed PyTorch on the RTX 5080 — `torch 2.7.0.dev20250310+cu124` does not
ship `sm_120` kernels and any real CUDA op throws
`no kernel image is available for execution on the device`.

---

## D1 — WSL2 Python venv location

**Question:** Where should the WSL2 training Python environment live —
inside the WSL filesystem, under the Windows project tree at `/mnt/c/...`,
or replace the broken system-wide install at `/home/alona/.local`?

**Choice:** **WSL native — `~/shomer-training-venv`** (i.e. `/home/alona/shomer-training-venv` inside the Ubuntu-24.04 WSL distro).

**Why:**
- I/O on `/mnt/c/...` is a 9P translation layer; pip installs, HuggingFace dataset
  caching, and checkpoint reads are measurably slower (often 5–20×) than on the
  native ext4 filesystem inside WSL. For a multi-GB training workflow this is
  not a micro-optimisation.
- A dedicated venv keeps the broken system torch (and any other packages from
  earlier Keras / TF / notebook experiments) from contaminating the training
  Python — and vice versa.
- Accessible from Windows when needed via `\\wsl$\Ubuntu-24.04\home\alona\shomer-training-venv\`.

**Alternatives considered:**
- *Project tree (`/mnt/c/AIDevelopmentCourse/Shomer.AI/training/.venv-wsl`):* visible
  from Windows Explorer, but the disk-I/O penalty would compound across every
  pip install, every HF dataset cache read, every checkpoint save. Not worth
  the convenience.
- *Replace the system `~/.local` install:* simplest in principle, but the
  existing broken torch was installed user-wide and is entangled with whatever
  earlier experiments put it there; cleaner to leave it alone and start fresh
  in a venv that is unambiguously the training environment.

**Revisit:** if a future workflow genuinely needs Windows-side tooling to read
intermediate checkpoints (e.g. a Netron model viewer running on Windows
pointing at the venv), reconsider — but until then native WSL wins on
throughput.

---

## D2 — PyTorch build

**Question:** Which PyTorch build to install — the stable cu128 wheel or the
nightly cu128 wheel?

**Choice:** **Stable, cu128 wheel.** Installed via
`pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128`.
Resolved to `torch-2.11.0+cu128` (with `cu128` CUDA runtime, cuDNN 9.19,
cuBLAS 12.8.4, NCCL 2.28, Triton 3.6).

**Why:**
- The `cu128` wheels are the official stable build that ships with `sm_120`
  (Blackwell) kernels — verified in `torch.cuda.get_arch_list()` after install
  (`['sm_75','sm_80','sm_86','sm_90','sm_100','sm_120']`).
- BF16 forward+backward on the RTX 5080 works (real test: 10× 4096² matmul +
  backward in 0.21 s, 0.17 GB VRAM peak) — the architecture doc's
  BF16 training assumption is honoured.
- Stable over nightly because the training run is the academic deliverable;
  regressions in a nightly build would be hard to debug under time pressure
  and would not be defensible at the meeting.

**Alternatives considered:**
- *Nightly cu128:* freshest Blackwell optimisations, but occasional regressions
  and no upside for a workload this size. Reserve for a future need
  (e.g. if a specific sm_120 perf fix lands post-2.11 stable and we need it).

**Revisit:** if a downstream library (PEFT, bitsandbytes, accelerate) pins
to a different torch range and forces a downgrade — re-check `sm_120` support
on whatever the resolver picks.
