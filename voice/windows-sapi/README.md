# Optional Windows Huihui speech adapter

This is a separate fast system voice choice for AIRI. It uses the already installed Microsoft Huihui Desktop SAPI5 voice and does not download weights. It **does not preserve Serena's voice or Qwen's natural-language style instructions**. The current AIRI default is unchanged.

`start.ps1` starts only this adapter on `127.0.0.1:9947`. `stop.ps1` stops only the recorded server/worker after verifying executable, exact script/launch arguments, creation time, command hash, parent identity and port owner. A held native process handle prevents PID reuse between the final verification and termination. An unrelated listener or changed identity is refused.

The supplied local launcher expects the existing Python at `%LOCALAPPDATA%/Programs/SparkAI/envs/creative/Scripts/python.exe` and discovers its base executable through pyvenv.cfg. It uses native `%SystemRoot%/System32/WindowsPowerShell/v1.0/powershell.exe`. Set `AIRI_SAPI_PYTHON` to your compatible Windows venv `Scripts/python.exe` when installing elsewhere; the environment must contain its matching `pyvenv.cfg` so owned child identity can be checked. The original default path was runtime-tested; the publication-only environment override is syntax-checked. No Python package is required.

## API

| Route | Authentication | Result |
|---|---|---|
| GET /health | None | Readiness, owned instance/PID, queue/worker metrics, limitations |
| GET /v1/models | None | `windows-sapi-local` |
| GET /v1/audio/voices | None | `huihui` / Microsoft Huihui Desktop / zh-CN |
| POST /v1/audio/speech | Bearer local token | Complete PCM WAV, 24 kHz, 16 bit, mono |

The speech JSON accepts `model`, `voice`, `input`, `response_format:"wav"` and an optional `speed` from 0.25 to 4. Speed maps to SAPI's discrete integer rate and is approximate. Default model/voice/format are the sole values listed above. Empty/overlong input, other models/voices/formats, streaming and nonempty style instructions return fixed error codes. Input is literal text (`SVSFIsNotXML`), never SSML, a filename or executable code.

The adapter requires `response_format:"wav"`; configure AIRI's OpenAI-compatible speech provider accordingly. Its base URL is `http://127.0.0.1:9947/v1`. The API key is the local token; never return that key in a public catalog, UI preferences, URL or logs.

`token_store.ensure_token(path=None)` can be imported before starting the service. It atomically creates `api-token.txt` only if absent and returns its 43-character URL-safe token (`secrets.token_urlsafe(32)`). A fully written temporary file is linked into place with create-if-absent semantics, so concurrent callers cannot overwrite each other's key or read a partly written key. An invalid existing file raises a fixed error and is preserved. Importing this helper does not initialize COM or open a port.

Host must be `127.0.0.1:9947` or `localhost:9947`. Browser Origins are limited to `null` (AIRI's file renderer), this adapter's loopback URLs and control center loopback port 9944. Other/duplicate Hosts or Origins are rejected. Speech still requires the token even for an allowed Origin. CORS echoes an allowed Origin and never uses `*`; no credentials are enabled. CLI requests may omit Origin.

## Runtime and cancellation

A persistent fixed PowerShell script reads one JSON object per stdin line. User text never appears in shell arguments or a constructed command. It selects exactly `TTS_MS_ZH-CN_HUIHUI_11.0`, routes audio to `SAPI.SpMemoryStream`, and returns a base64 WAV JSON response. The Python server validates the complete WAV before returning it. There is no sound-card output and no user text/audio file. Request bodies, audio, auth headers and URLs are not logged.

At most eight accepted requests, including the active one, can exist. One worker synthesizes in FIFO order; the ninth request receives `429 VOICE_BUSY`. A disconnected queued request is skipped. Cancellation during synthesis terminates that exact child handle, discards its output and initializes a fresh worker. Queue and generation deadlines are bounded. Worker start/crash/invalid output returns fixed codes and releases its queue slot; no COM failure leaves the API thread waiting forever.

Response headers separate `X-AIRI-Queue-Seconds`, `X-AIRI-Generation-Seconds` (worker synthesis plus in-memory WAV/base64), `X-AIRI-Total-Seconds` (queue plus worker protocol/validation), and `X-AIRI-Audio-Seconds`. HTTP client wall time additionally includes transport. This batch endpoint returns no playable audio before the complete WAV exists.

## Verification

`verify_api.py --run --lifecycle` explicitly makes fixed synthetic requests only to 9947, checks WAV/counters/queue cancellation/worker recovery/Origin/Host/auth, tests repeat start, tampered creation-time refusal, proper stop and an unrelated listener's preservation, then leaves the verified adapter running. It never plays audio. It saves only the fixed declared sample phrase “先休息一下吧。我在这里，慢慢来就好。” to `samples/huihui-soft.wav`, and a private `verification.json`. Do not run this while another client is using the optional adapter.

Do not publish `api-token.txt`, state/worker-state, logs, __pycache__, generated samples or private verification output. Only the source files and sanitized verification summary belong in the public package.

Primary Microsoft references: [SpVoice AudioOutputStream](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms723597(v=vs.85)), [speech format enum](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms720595(v=vs.85)), [literal text flags](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms720892(v=vs.85)).
