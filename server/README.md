# Server

FastAPI wrapper around Ollama, exposing `/classify`.

## Prerequisites

1. **Ollama** installed and running on Windows (https://ollama.com/download). After install, verify:
   ```powershell
   ollama list
   ```
2. **Your GGUF model** (`offensive-hebrew.gguf`) in this directory. Produced by `training/export_gguf.py`.

## Register the model with Ollama (one-time)

Two paths depending on where you are in the project:

**A. Stand-in for end-to-end testing** (before the fine-tuned GGUF exists). Uses base `qwen2.5:7b-instruct` + a strong system prompt:
```powershell
cd C:\Users\Dima\Projects\offensive-hebrew\server
ollama pull qwen2.5:7b-instruct
ollama create offensive-hebrew:v1 -f Modelfile.standin
```

**B. Real fine-tuned model** (after `training/export_gguf.py` produced `offensive-hebrew.gguf`):
```powershell
ollama rm offensive-hebrew:v1   # drop the stand-in
ollama create offensive-hebrew:v1 -f Modelfile
```

Smoke test either build:
```powershell
ollama run offensive-hebrew:v1 "סווג: שלום עולם"
```

If your base model is NOT Qwen-family (e.g. DictaLM/Mistral), edit the `TEMPLATE` block in `Modelfile` to match — Mistral uses `[INST]...[/INST]` instead of ChatML.

## Run the server

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` is required so the Android phone can reach it. `127.0.0.1` only listens to the PC itself.

### Open the Windows Firewall once

```powershell
# Run elevated
New-NetFirewallRule -DisplayName "OffensiveHebrew" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

## Smoke test

```powershell
curl http://localhost:8000/health
curl -Method POST -Uri http://localhost:8000/classify `
  -ContentType "application/json" `
  -Body '{"text":"שלום עולם"}'
```

## API

| Method | Path           | Body                          | Returns                         |
|--------|----------------|-------------------------------|---------------------------------|
| GET    | `/health`      | —                             | `{status, ollama_reachable}`    |
| GET    | `/model/info`  | —                             | model id, labels                |
| POST   | `/classify`    | `{"text": "..."}`             | `{is_offensive, category, confidence, model, latency_ms}` |

Interactive docs at http://localhost:8000/docs.
