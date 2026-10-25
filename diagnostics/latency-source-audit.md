# AIRI voice latency: source audit, 2026-10-25

This audit read local source, the installed compiled renderer, and only the whitelisted Hearing preference keys in offline-settings.json. It sent no HTTP/SDK request, opened no microphone, played no audio, read no private chat, and changed no runtime default or service. No new latency measurements are claimed here.

## Correcting the SDK evidence boundary

The existing `verify-app-llm-tts.mjs` uses a random `overrides.binding`. In this installed renderer that is an **external scene**, and scene responses deliberately do not speak on the host. An increase in the process-wide `tts_requests` counter is therefore only a concurrent observation. It cannot be attributed to this SDK message.

The former 38,970 ms observation must be described as **SDK synthetic text completion plus a simultaneous global TTS-count observation**, not a causally verified microphone/LLM/TTS/playback result. An SDK `output:gen-ai:chat:message` is also not first-token timing: this event is emitted after generation completes.

The complete installed-bundle chain is:

| Stage | Installed compiled evidence | Matching source |
|---|---|---|
| Binding selects external session | `assets/context-bridge-q5xwtBWr.js:670` | `packages/stage-ui/src/stores/mods/api/context-bridge.ts:944` |
| Session has bindings and is not activated | `assets/hearing-C884hhRK.js:76568` (`createSession` body around 76580) | `packages/stage-ui/src/stores/chat/session-store.ts:1615`, `:1633` |
| Bound sessions are not owner sessions | `assets/chat-B825WUc6.js:2207`–2208 | `packages/stage-ui/src/stores/chat.ts:409` |
| Request becomes scene | `assets/chat-B825WUc6.js:2912` | `packages/stage-ui/src/stores/chat.ts:1287` |
| Scene gives speaks=false | `assets/tools-BKt_0CNb.js:61167` | `packages/core-agent/src/runtime/chat-orchestrator-runtime.ts:686` |
| Host checks speaks before opening output/writing tokens | `assets/pages-0e_WCEAU.js:782`–800 | `packages/stage-ui/src/components/scenes/Stage.vue:569`–598 |
| SDK message comes from assistant-message hook | `assets/context-bridge-q5xwtBWr.js:766`–770 | `packages/stage-ui/src/stores/mods/api/context-bridge.ts:1029`–1034 |
| Assistant-message hook runs after generation/commit/stream-end | `assets/tools-BKt_0CNb.js:61647`; complete at 61649 | `packages/core-agent/src/runtime/chat-orchestrator-runtime.ts:1249`–1252 |

Compiled paths above are relative to `airi/apps/stage-tamagotchi/out/renderer/`; source paths are relative to `airi/`. The context bridge directly imports chat-B825WUc6 and hearing-C884hhRK, and chat-B825WUc6 imports tools-BKt_0CNb. This is not just a conclusion inferred from an unrelated source checkout. Snapshot hashes are in `latency-source-snapshot.json`.

## Why always-on hearing waits after speech

The configured file currently selects `always-on`, auto-send=true, rephrase=false, end-judge=false, speaker-recognition=false. These are configured values, not a new live browser-state measurement.

1. `stores/voice.ts:48` sets `pauseMs=1200`, `graceMs=3000`. At line 507 the false end-judge branch still uses 1200 ms of VAD-classified silence. It does not mean immediate submission. Installed `use-push-to-talk-shortcut-6QU1GwbZ.js:1487`–1489 and `:1906` match.
2. The live VAD uses ordered 32 ms windows (`libs/voice/voice-activity-plugin.ts:55`; installed `voice-activity-plugin-Dj2qnaMF.js:19`). A clean 1200 ms threshold is crossed after 38 windows, about 1216 ms of detected non-speech. This is a sample-window calculation, not measured wall-clock latency.
3. While an input is active the speech threshold is lowered from 0.6 to 0.18. Any above-threshold tail/noise resets the silence count to zero (`packages/core-agent/src/voice/policy/rules.ts`, threshold and count logic around 149 and 188). Thus wall-clock waiting can exceed 1.2 s. Ordered model work or source buffering can add further delay; their contribution has not been measured.
4. The local OpenAI-compatible SenseVoice route is file upload. `hearing.ts:609`–611 awaits WAV encoding of the captured stream before invoking the provider, so its HTTP request begins after capture has been sealed. Then it waits for the batch ASR result. HTTP-only ASR latency omits endpointing and WAV preparation.
5. `autoSendDelay` is defined with 2000 ms at hearing.ts:335 but the current source has no consuming timer: references are definition, reset and export only. `composables/voice-drafts.ts` sends the final draft directly when auto-send is enabled. Do not add a fictitious extra 2 s to the latency budget.
6. Rephrase=false bypasses the optional final rewriting call (which otherwise has a 10 s timeout). End-judge=false bypasses the pause-time LLM judgement and the 3 s grace. It does not disable the silence threshold.

Echo is a separate boundary. There is no confirmed global “echo gate=false” preference in this audit. The built-in acceptance rule is `!speaking.nowSpeaking || devices.source.echoCancellation` (`voice.ts:509`, installed `:1907`). It runs on a window that could begin an input, not as a fixed post-speech timer. The processed microphone requests browser echo cancellation, AGC and noise suppression (`composables/audio/audio-device.ts:95`–97); `packages/audio/src/browser/sources.ts:107`–108 reads whether the actual track reports echoCancellation=true. Actual track capabilities were not queried. If playback is active and actual echo cancellation is false, the rule may reject a new automatic input rather than merely queue it for 1200 ms.

## LLM, synthesis and playback boundaries

| Boundary | Existing observable | What it does not prove |
|---|---|---|
| Speech ends in the room | Requires a known synthetic PCM ending or an acoustic reference | SDK text and HTTP ASR do not cover this |
| VAD last speech / seal | Input activity and input-finalizing events; VAD traces have last-speech end | Browser wall-clock processing and human acoustic endpoint differ |
| ASR start/end | `Speech recognition` span in hearing-transcriber.ts | Span starts before WAV encoding and may cover input capture; it is not pure server compute |
| Chat request / first text token | `LLM inference` span; event `ai.moeru.airi.io.llm.first_token`, attribute `...llm.time_to_first_token` (`chat.ts:827`–889) | Reasoning deltas are separate; this is first `text-delta`, not first network byte or first hidden reasoning token |
| First visible literal | Existing chat context channel `token-literal`, filtered to the synthetic turn/session | SDK `output:...:message` is later, after complete generation |
| First TTS request | `TTS synthesis` span, exact turnId + segmentId + expected synthetic text hash | Global server counters lack this correlation |
| TTS response available | End of matched synthesis span; optional server request relay timing | Does not include later playback waiting/decode |
| Scheduled playback | `Audio playback` span / onPlaybackStart (`speech-output-trace.ts:47`) | It marks scheduled audio, not proof of sound perceived at the speaker |
| Playback done | Per-clip receipt and Speech turn drain | LLM completion can occur earlier |

The non-streaming local speech provider receives complete encoded audio in `modules/speech.ts:594`–600 before the Blob is returned. The app does stream *text into sentence requests*, but this provider does not return playable partial PCM while a sentence is still being generated.

There are two text segmentation stages. `core-agent/src/voice/output/speech-transformation/segmenter.ts` first waits for a safe sentence/line boundary and complete markdown constructs. Only then does `pipelines-audio/src/processors/tts-chunker.ts` apply early-clause boost, word limits and punctuation. A long first sentence or unclosed markdown can therefore delay the first request despite the inner chunker's boost setting. A short exact phrase with no punctuation waits until end-of-text.

The app allows up to four in-flight sentence TTS requests (`speech-pipeline.ts:69`). Responses are scheduled in sequence (`:181`), so a later fast sentence cannot overtake an earlier slow sentence. `core-agent/.../output/response.ts` also respects earlier producers and a playback group plays clips in order (`pipelines-audio/src/playback.ts`). These are expected queueing boundaries; this audit did not measure their durations or infer GPU contention from them.

## Strict silent synthetic host test design — NOT RUN

Use a fresh **unbound owner session**, not overrides.binding, for the real host speech path. The SDK can target its explicit `overrides.sessionId`; the current public input route accepts that when binding is omitted. A normal chat turn persists its messages by design, so a zero-write real-chat test is not possible in the existing runtime. A new hidden synthetic session/card isolates those writes from all existing user conversations and does not need to become the selected card. An isolated disposable profile is preferable if zero lasting metadata is required.

Suggested controlled fixture, only after the baseline is finished:

1. Create a temporary test card/session through the existing public card/session stores, `setActive:false`, `hidden:true`, **no bindings**. Use only copied whitelisted provider/model/voice settings; do not load private session messages. Fix a short reply such as `本机延迟测试通过。`, request no tool use and no screen context, and require zero actual tool calls in the result. A prompt saying “no tools” does not remove app-injected built-in tools. Keep a fresh test turn ID and nonce. A disposable profile also avoids inherited global context; a fresh session alone does not prove that every global context source is empty.
2. Give only this card a one-shot loopback TTS relay provider. Its nonce is in a unique URL path; its destination is fixed to the existing 9945 speech endpoint. It accepts only the configured model/voice and SHA256 of the exact permitted synthetic text. Reject all other requests without saving their body. There is no need to log or persist text, WAV bytes, headers containing credentials, or other traffic.
3. Relay records request arrival, upstream first response bytes and completion with a monotonic clock, nonce, text hash and byte/frame counts. Forward the real synthesis request unchanged. For a silent test, return a WAV with the same rate/channels/frame count but zero PCM samples, held only in RAM. This tests actual host scheduling while preserving a quiet room; report it as silent scheduling, not acoustic playback quality. Do not globally mute or replace the user's normal output.
4. Filter context events to that exact session/turn/nonce before inspecting content. Record first nonempty literal timestamp and only its length; compare final synthetic text hash without saving the text. Capture SDK message/complete timestamps separately with their correct names.
5. Subscribe only to new spans for that exact `ai.moeru.airi.io.turn_id`; project a whitelist of names, IDs and times, discarding all text/context attributes before persistence. Join TTS and playback by `tts.segment_id`. A matching expected synthetic text hash plus relay nonce links app synthesis to the server request; no global counter is needed. Existing spans are emitted when ended, so use their start/end times rather than receipt time.
6. Require all three causal links: known synthetic turn → expected TTS span/hash, expected TTS span → nonce relay request/hash, same segment → scheduled silent playback. Report missing links as incomplete. Restore/remove only the test-owned card/provider/session after output drains; preserve the user's selected 3D and normal configuration.

The fixture above is a design, not a claim that the app already exposes this as a one-call SDK API. It needs a small test harness using existing public stores and a test-only relay. If the parent elects not to create any test metadata or a silent relay, report SDK text, HTTP ASR/TTS and source-derived endpointing separately; do not combine them into a fabricated end-to-end number.

For VAD itself, a separate disposable pipeline fixture can feed a fixed synthetic WAV followed by exact PCM silence through the same VoiceController/Silero configuration, with no microphone subscription and no private audio. It can measure sample endpointing plus ASR/LLM/synthesis. It still excludes physical microphone/browser capture/room acoustics unless an explicitly authorized acoustic test is performed while the user is awake.

## Low-risk next decisions

First compare the parent's HTTP baseline with a correctly correlated host trace. If TTS dominates, sentence-generation improvements belong to the TTS agent. If the first safe sentence dominates, test segmentation on fixed transcripts without changing punctuation semantics. A shorter fixed silence limit could save a few hundred milliseconds, but can split deliberate pauses; do not silently label it lossless. Push-to-talk release is already an explicit endpoint and provides an honest comparison without changing always-on behavior. No setting or implementation was changed by this audit.
