# Step 0 — POC: Feasibility (app ↔ my server)

**Phase:** Pre-A (feasibility) · **Status:** ✅ **DONE (2026-05-23)** · **Maps to:** Meeting 1 "Doable" check
> This was a throwaway feasibility step: *can an Android app reach a server on my own
> computer and get a Hebrew offensive/not answer back?* It is **not** the final
> architecture. Everything here **will change** once the full project plan is approved.

---

## 🎯 Goal

Prove the wire works end-to-end, on real hardware:

> Android app → FastAPI server on my PC → local LLM (Ollama) → classification back to the phone.

Success = type a Hebrew sentence (or pick/take a photo) in the app and see a label appear,
with the model running **locally on my computer**.

---

## ✅ Result — feasibility PROVEN

Verified on **two targets** and recorded in `integration/results/integration-1/`:

| Target | Outcome |
|---|---|
| Android **emulator** (`10.0.2.2:8000`) | ✅ PASS — `run-2026-05-23.md` |
| **Physical Huawei P20 Pro** (`CLT-L29`, EMUI 12) over Wi-Fi | ✅ PASS — `run-2026-05-23-physical-huawei-p20pro.md` |

Real calls from the phone are in the server audit log (`server/logs/audit-2026-05-23.jsonl`),
with the phone's LAN IP (`192.168.68.117` / `.107`) recorded as the client.

**Actual classifications observed:**

| Input (Hebrew) | Result | Confidence | Latency |
|---|---|---|---|
| `שלום` / `יום נפלא היום` / `ילד יפה תואר` | not offensive (`non_offensive`) | 0.95 | ~0.9–2.8 s |
| `ילד מניאק` | **offensive** (`abusive`) | 0.95 | ~1.2 s |
| `אשבור לך תראש מחר יאמנייק` | **offensive** (`violence`) | 0.95 | ~1.1 s |
| image upload (gallery + camera) | `backend=stub` (wire only) | — | ~30–76 ms |

`/health` returned `{status: ok, ollama_reachable: true, model: offensive-hebrew:v1}` in ~0.3 s.

---

## 🛠️ What was used

**Server (`server/`)** — Python 3.12, **FastAPI** + **uvicorn**, `httpx`, `pydantic` v2,
`python-multipart`. Endpoints: `GET /health`, `GET /model/info`, `POST /classify` (text),
`POST /classify-image` (multipart). Open CORS + audit-logging middleware that writes one JSONL
line per request to `server/logs/`.

**Model serving** — **Ollama** on `:11434`, model `offensive-hebrew:v1`.
⚠️ **Stand-in, not trained:** built from `Modelfile.standin` = base `qwen2.5:7b-instruct`
+ a strict-JSON system prompt (`is_offensive` / `category` / `confidence`, temperature 0.1).
Accuracy is **not meaningful yet** — this only proves the plumbing.

**Android (`android_client/`)** — Kotlin + **Jetpack Compose** (Material 3), minSdk 24 /
targetSdk 35. **Retrofit 2.11** + Moshi + OkHttp, Coil (image preview), DataStore (saved
server URL), Navigation Compose. Two screens: **Classify** (Text | Image toggle, picker +
camera capture) and **Settings** (server URL). `network_security_config.xml` allows cleartext
HTTP to the LAN/emulator.

**Connectivity** — emulator uses `http://10.0.2.2:8000/`; physical phone uses
`http://<PC-LAN-IP>:8000/` on the same Wi-Fi, with a one-time firewall rule
(`New-NetFirewallRule -DisplayName "ShomerAI" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`).

---

## 🔧 How it was built (order of work)

1. FastAPI app with `/health` + `/classify`; `httpx` call to Ollama; JSON parsed into a typed response.
2. `Modelfile.standin` → `ollama create offensive-hebrew:v1` so the stack runs before any training.
3. Android Compose app: Settings screen (server URL) → Classify screen (text) → Retrofit client.
4. Added `/classify-image` (multipart) + a **stub** image backend, and the matching Android
   image picker / camera capture — proves the image wire without real image processing.
5. Bound server to `0.0.0.0`, opened the firewall, pointed the phone at the PC's LAN IP, ran
   `integration-1` on emulator **and** physical phone → both PASS.

---

## ⚠️ Caveats — why this is only Step 0

- **Model is a stand-in** (prompted Qwen 2.5), not the fine-tuned Hebrew classifier.
- **Images returned `stub`** at POC time (a single real `vision_only` trial on 2026-05-24 took ~14.6 s — early Phase-2 work, not part of the POC pass).
- **Architecture is undecided.** The approved-proposal design (DictaBERT + 3 agents + RAG)
  differs from what this prototype uses (Qwen via Ollama). That choice is **pending plan approval** — see [`../Plan.md`](../Plan.md).

**Bottom line:** *Yes — it is possible to build the app and call my server on my computer.*
The how/what below this step is subject to the new project plan scheme.
