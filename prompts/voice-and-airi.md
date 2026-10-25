# Persona, speech and AIRI integration

Choose the requested mode rather than rebuilding unrelated assets. The persona config,
Live2D project, installed model files and speech service are separate inputs.

## Persona and expressions

Use `examples/phoenix/character.json` as a documented configuration example, with its
facts and source pointers in `sources.json`. Write another character's original persona,
greetings and example dialogue from that character's evidence. Keep unknown facts unknown.
Expression labels are original runtime interpretations, not official emotion names.

Export from the package root:

```text
python character-tools/export_cards.py examples/phoenix/character.json --out work/card-only
python character-tools/export_cards.py my-character.json --out work/card-with-model --model work/verified-model
```

Card-only export has no animated body. Include a model only after independent Core and
visual validation and only when its distribution terms allow that output. Normal AIRI
Character Cards import registers the display model; invented IDs or direct edits of
running IndexedDB are not a substitute. Details and the exact ACT syntax are in
[character-tools/README.md](../character-tools/README.md).

## Optional expressive Chinese voice

Inspect existing ASR/TTS services, weights and compatible environments before downloading
another copy. The bundled [voice module](../voice/README.md) is text-only Qwen3-TTS 1.7B
CustomVoice, built-in Serena, with three original general delivery instructions. It has
no voice-cloning input and no actor reference audio. Preserve a faster working TTS as a
fallback if latency matters. Batch synthesis waits for a whole utterance before audio.

Model setup requires approximately 4.52 GB of files, downloaded separately from pinned
official sources. The code and lock file are bundled; weights are not. Choose a suitable
local GPU/PyTorch environment, then install extra dependencies into an isolated overlay.
Do not replace an unrelated application's Torch/Transformers environment to satisfy it.
Regular server startup is local-file-only with a process-local loopback network policy.

Default TTS settings are base URL `http://127.0.0.1:9945/v1/`, model
`phoenix-qwen3-tts-local`, and voice `phoenix-soft`. The other voices are
`phoenix-drowsy` and `phoenix-focused`. Change names/styles for another character in
`voice/styles.json`; performance descriptions should remain original. ASR is separate:
reuse a working local transcription service rather than assuming this TTS provides it.

## AIRI integration and acceptance

Provider addresses are configured separately from character cards. The Phoenix sample
uses `openai-compatible` and `vision-openai-compatible` for the existing local 9B service,
and `openai-compatible-audio-speech` for Qwen TTS. A portable package cannot assume these
provider IDs are already configured on another machine. Hearing/ASR is a global setting
in the tested AIRI revision; do not invent an unused per-card ASR field.

Use normal app import/selection within the user's requested scope. Preserve existing
cards, sessions, edited settings and the original model while testing a new candidate.
Test one short original synthetic sentence and confirm the actual provider/model/voice,
audible response, lip sync, independently controlled eyes and one exact manifest
expression name. Check the active card's speech override as well as global providers.
Screen and microphone capabilities require actual app permission and user-requested
configuration; a role card cannot grant those permissions.

Record service HTTP tests separately from AIRI end-to-end acceptance. Retain original
sample text and timing definitions, and record any unperformed import/render/audio tests.
Never call a waveform-only check a voice match or claim the generated voice is the actor.
