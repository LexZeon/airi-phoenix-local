# AIRI local text-latency audit

Validated on 2026-10-25 against the running loopback service, without restarting AIRI/model services, changing inference configuration, reading private chat, or sending synthetic prompts to the user's AIRI conversation.

## Verified runtime

- Model alias: `airi-qwen3.5-9b`; GGUF: `Qwen3.5-9B-Q4_K_M.gguf`.
- `/props` build: `b11829-184f65360`; context capacity 32768; one server slot; vision/video supported, audio input unsupported by this model server.
- Running command and launcher both use `--reasoning off --parallel 1 --ctx-size 32768 -ngl 999 -fa on`, matching local projection weights.
- In this exact llama.cpp revision, `--reasoning off` sets both `enable_reasoning=0` and the template default `enable_thinking=false`. This is different from `--reasoning-format none`, which controls parsing/output fields.
- A no-inference `/apply-template` synthetic check returned identical 109-character prompts for the current default and an explicit per-request `chat_template_kwargs: {enable_thinking: false}`. Both end with a closed empty thinking block, not an open thinking block. Adding the same flag again is not an unexploited latency fix.
- Qwen's official model card documents non-thinking API parameters and says the `/think` and `/nothink` soft switches are not officially supported for Qwen3.5.

## Bounded synthetic timing observation

Each size was tested exactly once, with the same synthetic system instruction and a two-token `OK` result. Both began immediately after a `/slots` idle observation. Periodic screen understanding stayed enabled. The long input is repeated synthetic filler, not real AIRI persona, tools, history, or a quality benchmark. No private prompt or answer was read or retained.

| Input | First visible text | Whole response | Server prompt processing | Processed / cached tokens | Decode |
| --- | ---: | ---: | ---: | ---: | ---: |
| 39 tokens | 0.1683 s | 0.2135 s | 132.501 ms | 39 / 0 | 2 tokens, 44.717 ms |
| 11992 tokens | 5.6765 s | 5.7110 s | 5630.406 ms | 11972 / 20 | 2 tokens, 34.075 ms |

Both returned zero reasoning-content characters and stopped normally. This demonstrates that an uncached input near 12K tokens can spend about 5.6 seconds in prefill on this setup even with thinking disabled. It does not establish the latency of the current AIRI conversation, its prompt length, a cold/warm average, or a proposed optimization's speedup. Very short two-token decode rates are not sustained-generation benchmarks. The 32768 setting is capacity, not proof that every request processes 32768 tokens.

## Verified screen contention opportunity

- The screen worker targets the same 9941 model service every 20000 ms, uses a 1280x720 primary-display thumbnail, `stream=false`, and up to 400 output tokens. It skips overlapping work of its own but has no foreground-chat priority in the inspected worker.
- The helper reported recent completed screen-request durations of 5155 ms and 5120 ms; successful publications continued, with zero failures/skips in the snapshots. These are two observations, not a distribution or a pure-GPU timing.
- `/props` reports one total slot. Concurrent `/slots` snapshots showed a processing, nonstreaming, 400-token-limit request while the helper reported `capturing=true`, consistent with the configured screen worker. Snapshot token counts are not treated as a real chat's prompt size.
- Exact-revision server source defers new completion tasks when no slot is free. Therefore a foreground chat can wait behind screen inference. These observations do not causally attribute a particular user-perceived pause or quantify its queue time. The observed metadata does not expose a trustworthy per-chat queue length/wait duration.

## Recommended test order for everyday companionship

1. Preserve the confirmed non-thinking mode. Measure actual foreground-request token counts, cached-token counts, first visible text and timing fields without persisting content. Do not infer current history length from the last vision slot.
2. Compare the existing persona/tool/history payload against a shorter, capability-preserving version using fixed synthetic dialogues and explicit quality checks. Retain necessary character behavior, tools and useful recent context. Do not merely lower the 32K context ceiling to 8K; that previously failed to fit AIRI requests.
3. Test foreground priority for screen work: defer new background screen requests while hearing/chat generation is active, retain the latest screen summary, then refresh after the turn. This preserves screen understanding with temporarily older context. Quantify chat TTFT and screen freshness before adopting it.
4. Separately test an additional slot or a dedicated vision endpoint only after recording memory, throughput and mixed LLM/TTS load. More slots do not guarantee lower latency and can consume more context memory. GPU contention with speech is a candidate, not proven by this audit.
5. For faster perceived speech, test short natural first sentences and incremental TTS scheduling, measuring sentence gaps as well as first audio. Do not treat SDK scene-binding completion events as native-host speech or microphone-to-speaker latency.

Steps 2-5 are proposed tests, not measured improvements. No production setting was changed by this audit.

## Primary sources and local evidence

- Exact llama.cpp CLI handling: https://github.com/ggml-org/llama.cpp/blob/184f65360/common/arg.cpp#L3611-L3638
- Exact server thinking defaults: https://github.com/ggml-org/llama.cpp/blob/184f65360/tools/server/server-context.cpp#L1539-L1578
- Exact one-slot scheduling/defer path: https://github.com/ggml-org/llama.cpp/blob/184f65360/tools/server/server-context.cpp#L2729-L2744
- Exact API timing/token semantics: https://github.com/ggml-org/llama.cpp/blob/184f65360/tools/server/README.md#timings-and-context-usage
- Qwen official model card: https://huggingface.co/Qwen/Qwen3.5-9B#instruct-or-non-thinking-mode
- Local launcher: `launchers/airi-model-start.ps1`, lines 35-38.
- Deployed screen helper snapshot: [`main.cjs`](../airi-integration/offline-shell/main.cjs), `captureAndPublish` and the periodic capture timer. Line numbers differ after the screen-off repair; this timing observation describes the earlier enabled state.
- Running `/props`, whitelisted `/slots` and helper `/health` metadata; no raw template, private prompts, chats or screenshots retained.
