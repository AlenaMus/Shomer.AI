# Offensive-Hebrew Classifier

End-to-end Hebrew offensive-language classifier:

- **Android app** (Kotlin + Compose) — text in, label out.
- **FastAPI server** (Python) — exposes `/classify`, calls Ollama.
- **Ollama model** — a Hebrew-capable base LLM fine-tuned with LoRA on the [SinaLab/Offensive-Hebrew](https://huggingface.co/SinaLab/Offensive-Hebrew) dataset, exported to GGUF.

```
[Android app] --HTTP--> [FastAPI :8000] --HTTP--> [Ollama :11434] -> offensive-hebrew:v1
```

## Run order (first time)

1. **Train** the LoRA adapter (in WSL2 with a CUDA-capable GPU):
   ```bash
   cd training
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python prepare_data.py
   python train_lora.py --config configs/train.yaml
   python evaluate.py --adapter outputs/offensive-hebrew-lora
   ```

2. **Export to GGUF** and import into Ollama:
   ```bash
   python export_gguf.py --adapter outputs/offensive-hebrew-lora --out ../server/offensive-hebrew.gguf
   cd ../server
   ollama create offensive-hebrew:v1 -f Modelfile
   ollama run offensive-hebrew:v1 "סווג: שלום עולם"   # smoke test
   ```

3. **Start the server** (Windows native, in a regular PowerShell):
   ```powershell
   cd server
   python -m venv .venv ; .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   copy .env.example .env
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
   Open Windows Firewall: `New-NetFirewallRule -DisplayName "OffensiveHebrew" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow` (elevated PowerShell, one-time).

4. **Build and install the Android app**:
   - Open `android_client/` in Android Studio.
   - In the in-app **Settings** screen, set the server URL:
     - Emulator: `http://10.0.2.2:8000/`
     - Physical phone (same Wi-Fi): `http://<your-PC-LAN-IP>:8000/` (run `ipconfig` on the PC to find it).
   - Run on emulator or real device.

## Smoke testing before the app is built

```powershell
curl http://localhost:8000/health
curl -Method POST -Uri http://localhost:8000/classify -ContentType "application/json" -Body '{"text":"שלום"}'
```

See the per-subproject READMEs in `training/`, `server/`, `android_client/` for details.

## License
For personal/educational use. Dataset and base models retain their original licenses.
