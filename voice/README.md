# Local expressive Chinese voice

This optional service uses the official **Qwen3-TTS-12Hz-1.7B-CustomVoice** model and its built-in **Serena** speaker. Three original Chinese style instructions provide gentle companionship, mild drowsiness, and focused work speech. They describe a general performance style; no actor audio, official character dialogue, voice clone, or character-specific speaker embedding is used or included.

The default remains `phoenix-soft`. Change the alias per request or edit [styles.json](styles.json). This package provides only text-to-speech; AIRI's microphone/SenseVoice service can remain separate.

| Alias | Style |
| --- | --- |
| `phoenix-soft` | Warm, gentle, slightly tired; a little slower and clear |
| `phoenix-soft-efficient` | Optional: the same soft instructions and Serena speaker; omits unused residual-predictor hidden states |
| `phoenix-drowsy` | Quiet and relaxed with mild breathiness |
| `phoenix-focused` | Warm but attentive, concise and clear |

`phoenix-soft-efficient` is an explicit opt-in candidate. The default remains `phoenix-soft`; no AIRI card is switched by installing it. [Performance comparisons](performance.md) distinguish measured synthetic results from pending integration checks and describe the separate system-voice option.

## Install once, run offline

Use a Python environment with functioning GPU PyTorch and Torchaudio for your hardware. The tested machine used native Windows ARM64 Python 3.13, Torch 2.14.0+cu134, and an RTX Spark GPU. The scripts do not alter your existing Torch installation. Dependency downloads and model downloads are explicit setup steps; normal server startup uses local files only.

```text
python voice/install_dependencies.py --target /path/to/isolated-voice-deps
python voice/download_models.py --models-root /path/to/shared-models/TTS
python voice/server.py --deps /path/to/isolated-voice-deps --model-dir /path/to/shared-models/TTS/Qwen3-TTS-12Hz-1.7B-CustomVoice
```

The pinned download is about **4.52 GB / 4.21 GiB**. It includes both the 3.83 GB model and matching 682 MB speech tokenizer, so a second tokenizer copy is unnecessary. Files are verified against pinned official SHA-256 or Git blob hashes. Existing matching files are reused; interrupted downloads retain partial files for retry. `download_models.py --verify-only --models-root ...` checks local files without downloading.

Sources and exact revisions are in [models.lock.json](models.lock.json). Model weights are not in this repository or its ZIP. Download only from the pinned official Hugging Face source in the script. Qwen's package and weights carry their own Apache-2.0 license; the adapter code here is MIT under the repository license.

The isolated overlay uses the upstream `qwen-tts==0.1.1` and its required Transformers 4.57.3 rather than changing another app's Transformers version. It uses PyTorch SDPA; FlashAttention compilation is unnecessary. The text-only CustomVoice path disables Transformers' optional generic audio loader when SoXR is absent, avoiding an unavailable Windows ARM wheel. This does not add voice cloning or reference-audio support. Upstream's unused 25 Hz path can emit a missing-SoX warning on import; the included 12 Hz CustomVoice synthesis was actually tested successfully.

## API and AIRI settings

The server binds only to `127.0.0.1`, default port **9945**. It installs a process-local loopback-only socket policy and Hugging Face offline/telemetry flags. It has no download endpoint, cloning endpoint, file-upload endpoint, or system firewall changes. Request text and audio are not logged or retained by the service.

- Base URL: `http://127.0.0.1:9945/v1/`
- Model: `phoenix-qwen3-tts-local`
- Voice: `phoenix-soft` (or another alias above)
- AIRI provider type: OpenAI-compatible audio speech; a placeholder key such as `local-offline` can satisfy a client's required key field. The local service itself does not require an account.
- `GET /health`, `GET /v1/models`, `GET /v1/audio/voices`
- `POST /v1/audio/speech`: `model`, `input`, `voice`, optional `response_format` and `speed`

```json
{
  "model": "phoenix-qwen3-tts-local",
  "input": "先休息一下吧。我在这里，慢慢来就好。",
  "voice": "phoenix-soft",
  "response_format": "wav",
  "speed": 1.0
}
```

WAV, MP3, FLAC, and raw 24 kHz mono PCM are supported. One GPU synthesis runs at a time; up to eight requests can be accepted and queued so AIRI's prefetched sentence chunks are preserved. An overfull queue returns 429 and can be retried. Queue waits and generation each have a 120-second limit. Disconnected clients release queued work; active cancellation is checked at the next PyTorch talker step. Request bodies have a 15-second read timeout. Text is limited to 500 characters. `speed` from 0.75–1.25 adjusts the natural-language pace instruction; it is not an exact DSP time-stretch ratio. Keep `speed: 1` for the recorded presets.

In AIRI, choose this provider/model/voice for speech. Leave the hearing/ASR provider on its existing local service. Speech settings may also be overridden by a role card; update its speech module if it still selects a previous voice provider. Keep a faster existing voice as a fallback if immediate response matters.

## Actual samples and latency

[Gentle sample](samples/phoenix-soft.wav), [drowsy sample](samples/phoenix-drowsy.wav), and [focused sample](samples/phoenix-focused.wav) use only original short test sentences, with the text and measurements in [sample-report.json](samples/sample-report.json). Listen to them to decide which style you prefer; waveform/HTTP checks do not establish a subjective voice match to a fictional character.

On the tested machine, the three clips were 4.48–5.20 seconds long and took 6.67–15.88 seconds to synthesize, including a cold first request. A later warm API request generated a 3.04-second clip and MP3 response in 4.76 seconds. These are measurements alongside the running local AIRI/model workload, not performance guarantees. The current Python wrapper returns the whole waveform, so **first audio waits for batch synthesis**; it does not provide the upstream advertised 97 ms streaming latency. Real-time factor is generation seconds divided by audio seconds; lower is faster.

Repeat synthetic verification:

```text
python voice/sample_voices.py --deps /path/to/isolated-voice-deps --model-dir /path/to/model --out /path/to/new-samples
python voice/verify_api.py --report /path/to/api-test-report.json
python voice/verify_queue.py --report /path/to/queue-test-report.json
```

[Recorded API verification](tests/api-verification.json) covers real WAV/MP3 synthesis, health/model/voice listing, CORS, and rejected inputs. [Queue verification](tests/queue-verification.json) accepted eight requests, rejected the ninth, released disconnected work in 0.458 seconds, and successfully generated both subsequent concurrent sentence chunks. The queue test deliberately cancels one active generation; the current failure counter includes that expected interruption. [Runtime verification](tests/verification.json) combines the completed sample, API, queue, and machine-local startup identity checks. All reports exclude personal text, private paths, credentials, and third-party audio.

Official references: [Qwen3-TTS code and usage](https://github.com/QwenLM/Qwen3-TTS), [CustomVoice model](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice), [12 Hz tokenizer](https://huggingface.co/Qwen/Qwen3-TTS-Tokenizer-12Hz). This package uses the built-in speaker and original instructions; it does not ship a copied performance by the character's actor.
