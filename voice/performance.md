# Measured local speech options

These tests use the fixed original sentence `先休息一下吧。我在这里，慢慢来就好。`, Serena, the existing soft instructions, and local model files. They do not use private conversation, screenshots or microphone recordings. No default voice or application capability was changed. Audio files stay in the local test output directory for the user to compare.

## What the isolated comparison established

The tested runtime was native Windows ARM64 Python, PyTorch 2.14.0+cu134, Transformers 4.57.3 and `qwen-tts` 0.1.1 on an RTX Spark N1X. The talker, residual code predictor and waveform tokenizer were all actually on CUDA in BF16 with SDPA. Both autoregressive predictor configurations had KV caching enabled. CPU inter-op/intra-op thread counts were 20. No new model weights or compiled attention package was downloaded.

The first comparison used one baseline warmup, then each candidate warmup and an A-B-B-A block: 21 generations, 16 measured runs. A separate hidden-state follow-up used warmups followed by A-B-B-A and B-A-A-B: 10 generations, eight measured runs. All runs used one candidate process at a time. The production model instance remained loaded, and screen vision stayed enabled throughout; its publication count increased from 18 to 36 across the tests. GPU/host-memory competition is therefore part of this workload. The small sample does not establish an exclusive-GPU performance ceiling or guarantee a particular percentage improvement.

| Isolated case | Measured n | Median complete-WAV time | Resulting audio | Median RTF |
| --- | ---: | ---: | ---: | ---: |
| Baseline, pooled first comparison | 8 | 6.120 s | 5.20 s | 1.177 |
| `non_streaming_mode=True` | 2 | 9.036 s | 7.04 s | 1.283 |
| Residual predictor greedy sampling | 2 | 7.448 s | 5.84 s | 1.275 |
| Unused predictor hidden states off | 2 | 6.093 s | 5.20 s | 1.172 |
| All three changes combined | 2 | 8.229 s | 6.56 s | 1.254 |

Changing the text-input mode or residual sampling changed the generated waveform and did not improve complete-WAV latency in this test. They are not enabled by the service. `non_streaming_mode=False` in this package only simulates streaming text input; neither value makes this HTTP service stream playable audio.

The follow-up's baseline median was **7.441 s** (6.001–7.685, n=4); hidden-states-off was **5.959 s** (5.922–6.022, n=4), approximately 19.9% less time. However, the first comparison's pooled baseline was already 6.120 s versus 6.093 s for that candidate. Report both results: the observed gain varies with background load. All baseline and hidden-states-off WAVs had the same SHA-256 `845dbba822164162816d65dd58a4a7cfe2edfa1e41c8e48d6a979a2cd7fde6ef`. This is exact output equivalence for this fixed sentence/configuration, not a claim about every text, model version or language.

Coarse phase measurements put almost all elapsed time in autoregressive codec generation. Waveform decoding was about 0.04–0.07 seconds; text tokenization was around one millisecond. Each codec frame invoked the residual predictor, which generated 15 additional code groups. Its returned per-layer hidden states were unused by the caller. The main talker's hidden states are required to extract generated codec data and must remain enabled.

## Optional request alias

`phoenix-soft-efficient` retains the exact `phoenix-soft` instruction string, Serena, seed, language and all other generation settings. Only that request temporarily wraps the residual predictor's `generate` call with `output_hidden_states=False`. The wrapper exists inside the single-GPU lock and is restored in `finally`, including cancellation, timeout or failure. A subsequent default request keeps its original behavior. It does not change the main talker's output settings.

The response header `X-AIRI-Voice-Profile` identifies `default` or `predictor-hidden-off`. Health metrics include `last_voice` and `last_profile`. The default alias remains `phoenix-soft`.

CPU-only tests exercise the actual engine's request path with a fake model: waveform and instructions preserved, default→candidate→default isolation, failed/cancelled/timed-out request cleanup, concurrent default/candidate requests, and rejection of an override outside the generation lock.

After a controlled host reload, the actual service passed a baseline warmup and four serial HTTP A-B-B-A requests. The default median complete-WAV response was **7.580 s** (n=2), versus **6.082 s** (n=2) for `phoenix-soft-efficient`, approximately **19.8% less time** in this comparison. All four WAVs were bit-identical to the hash above, and `X-AIRI-Voice-Profile` confirmed the expected request mode. The tested optional alias is available for selection, while the existing AIRI card and default voice remain unchanged. These small, background-dependent results do not guarantee a fixed improvement.

## Windows system voice is a separate tradeoff

The installed Microsoft Huihui Desktop SAPI5 voice generated a 24 kHz, 16-bit mono WAV for the same sentence in **0.0988 s** on its first synthesis and **0.0110 s** warm, with 5.4145 seconds of audio. COM creation and voice selection took another **0.3828 s**; the first complete file including that setup was about **0.482 s**, excluding PowerShell process startup. Both WAVs had identical hashes. The test selected the local SAPI token explicitly and wrote to `SpFileStream`; it did not play sound or change the system default voice.

This preserves offline operation and needs no additional weights. It uses a different system voice and does not support Qwen's natural-language style instructions, so it is not a drop-in preservation of Serena or the character performance. These file-synthesis measurements do not prove an AIRI system-voice adapter or its end-to-end latency. The separate [Windows adapter](windows-sapi/README.md) now has its own 36-check actual HTTP, queue, cancellation, recovery and owned-lifecycle result; three complete-WAV HTTP client times were 0.147/0.055/0.029 seconds. This is still not a causal AIRI host-to-acoustic timing result.

No online service was tested: no usable API credentials were configured for the compared providers. An advertised latency is not an account-specific measurement.

## Reproduce without changing the running service

Use a fresh private output directory. The isolated process loads a second model instance, which needs additional memory and shares the GPU with the live workload. No audio is played and no live API configuration is changed.

```text
python voice/bench_candidates.py --deps /path/to/voice-deps --model-dir /path/to/local-model --out /path/to/private-candidates --rounds 1
python voice/bench_candidates.py --deps /path/to/voice-deps --model-dir /path/to/local-model --out /path/to/private-followup --rounds 2 --candidates predictor_hidden_off
powershell -NoProfile -File voice/bench_sapi.ps1 -Out C:\private\sapi-comparison
python voice/tests/test_candidates.py
python voice/tests/test_efficient_profile.py
```

The candidate report separates warmups, stores waveform hashes and phase timings, and retains one private WAV per candidate. Coarse phase boundaries synchronize CUDA. Nested predictor timing is host elapsed time, not an isolated GPU kernel measurement. The optional profiler is diagnostic and excluded from the ABBA results. Direct-engine measurements exclude HTTP queueing, encoding and the live server's socket-cancellation checks.

After the host explicitly reloads the updated service, the following loopback-only test can confirm the optional alias and a separate short-sentence prefetch simulation. It never reloads or switches a service itself:

```text
python voice/verify_efficient_api.py --out /path/to/private-api-comparison
```

The actual split test generated `先休息一下吧。` then `我在这里，慢慢来就好。` twice using the default voice. The first playable WAV arrived in **2.938 / 2.781 s**, with 2.48 seconds of audio. The second took **4.121 / 4.088 s**, with 3.60 seconds of audio. Total generation was **7.060 / 6.868 s**, combined audio was **6.08 s**, and the calculated playback gap was **1.641 / 1.608 s** if second generation starts when the first clip becomes playable. No sound was played. This trades a faster initial utterance for changed prosody and a potential pause; it is not seamless streaming. AIRI already performs sentence chunking, so this API simulation must not be described as a newly integrated AIRI speedup. It is not enabled as a new default behavior.

Recorded summaries: [candidate verification](tests/candidate-verification.json), [live alias and split verification](tests/efficient-http-verification.json), [SAPI verification](tests/sapi-verification.json). The reports contain no private paths, credentials, conversation or source recordings.

Primary references: [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), [PyTorch SDPA selection](https://docs.pytorch.org/docs/2.14/generated/torch.nn.functional.scaled_dot_product_attention.html), [SAPI file output](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms723597(v=vs.85)), [SAPI PCM format enum](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms720595(v=vs.85)).
