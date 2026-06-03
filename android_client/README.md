# Android client

Single-screen Compose app: enter Hebrew text → tap **Classify** → see label + category + confidence.

## Open in Android Studio

1. Install **Android Studio Ladybug** or newer (https://developer.android.com/studio).
2. File → Open → select this `android_client/` directory.
3. Wait for the Gradle sync. (First run downloads the Gradle wrapper jar automatically.)
4. Pick a run target:
   - **Emulator**: AVD Manager → create Pixel 7, API 34 → Run.
   - **Physical phone**: enable USB debugging, plug in, accept RSA prompt.

## Configure the server URL

Open the app → tap the **gear icon** in the top-right → enter:

- **Emulator**: `http://10.0.2.2:8000/`  (this is the magic IP for the host machine from inside the emulator — `localhost` would point to the emulator itself).
- **Physical phone on the same Wi-Fi**: `http://<your-PC-LAN-IP>:8000/`. Find it with `ipconfig` in PowerShell.

Tap **Test connection** — you should see `OK — status=ok, ollama=true, model=offensive-hebrew:v1`. Save.

## How to test

- Try a clearly non-offensive sentence: `שלום, מה שלומך היום?`
- Try a known-offensive sample from the test set.
- Inspect requests in Android Studio's **Logcat** — `HttpLoggingInterceptor` prints the full request/response body.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Cannot reach server" | Phone on guest Wi-Fi, or firewall | Same Wi-Fi as PC; open TCP 8000 inbound |
| "CLEARTEXT communication ... not permitted" | Network security config not picked up | Confirm `android:networkSecurityConfig="@xml/network_security_config"` in Manifest |
| Hangs then times out | Ollama is cold-loading the model | Try again — subsequent calls are fast |
| 422 from server | Model returned malformed JSON | Lower `temperature` in `Modelfile`, retrain a bit longer |
