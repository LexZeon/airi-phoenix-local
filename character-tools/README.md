# Character export and AIRI integration

`export_cards.py` is a generic, standard-library-only Python program. It accepts a JSON character configuration, not a fixed character or a remote service. Copy `../examples/phoenix/character.json`, change the identity, original persona, providers and expression names, then export another character. `character.schema.json` describes the configuration.

```powershell
python character-tools/export_cards.py examples/phoenix/character.json --out work/card
python character-tools/export_cards.py examples/phoenix/character.json --out work/card --model work/verified-model
```

Run these commands from the package root. The second command requires an already built, independently Core-validated Live2D directory or ZIP. It checks MOC3 magic, texture and optional file dependencies, safe relative paths and the exact requested expression names. It does not certify an arbitrary MOC3 file as Core-compatible. The separate rig validator supplies that evidence.

Outputs include an AIRI native card JSON for programmatic use, Character Card V3 JSON, portable SillyTavern V2 JSON and an AIRI share ZIP. The V2 system prompt omits AIRI-specific ACT instructions because other frontends may not consume those tokens. Its required fields follow the [Character Card V2 specification](https://github.com/malfoyslastname/character-card-spec-v2/blob/main/spec_v2.md).

## Normal import

Use AIRI Settings → Character Cards → import the generated `*.airi-card.zip`, then select/activate the new card. This invokes AIRI's own `importAiriCardPackage` → `displayModelsStore.addDisplayModel` → `addCard(..., 'import')`. A new card and device-local model/ avatar IDs are created; existing cards and chat sessions remain separate. Card-only export is allowed, but it has no model until a model is explicitly assigned. Do not present a card-only package as a completed animated character.

The outer ZIP contains:

```text
manifest.json
card.json                    # CCv3: chara_card_v3 / 3.0
models/body-model.zip        # only when --model is supplied
```

`manifest.json` uses `format: "airi-character-card"`, `version: 1`, `card: {"path":"card.json","spec":"chara_card_v3"}`. A model resource uses `resources.displayModel: {"path":"models/body-model.zip","format":"live2d-zip","name":"character-live2d.zip","controls":{"disabledExpressions":[],"disabledMotions":[]}}`. See `airi-package.schema.json`.

The inner model ZIP contains a genuine `.moc3`, `.model3.json`, referenced textures and `Expressions` files. The importer creates the avatar reference. A filesystem path in `modules.live2d.url` or a made-up `displayModelId` does not register a model in AIRI's display-model store.

The observed AIRI share whitelist retains reviewed persona fields and consciousness/vision/speech provider and model strings, but omits examples, tags, creator, arbitrary extensions and agent prompts. The exporter keeps examples in JSON formats for portability; all rules required by AIRI are in `system_prompt`. The active system-prompt composer uses systemPrompt, description, personality, scenario and available Live2D controls. Post-history instructions and example messages are not dependable prompt inputs in this AIRI revision.

## Actual expression control

Each `FileReferences.Expressions` entry in the model3 JSON must have its exact `Name` and an existing `File`, for example `{"Name":"E11_ClosedEyeSmile","File":"expressions/E11_ClosedEyeSmile.exp3.json"}`. AIRI reads these references, parses the exp3 definitions, removes disabled/broken controls and adds the exact available names to the active character's model prompt.

An assistant reply can begin with:

```text
<|ACT {"expression":{"name":"E11_ClosedEyeSmile","duration":3}}|>嗯，这样就好。
```

`duration` is seconds. Omit it for a persistent expression; reset with `<|ACT {"expression":null}|>`. This uses the actual streaming ACT path, not a free-form tag. `normalizeActPayload` accepts the name, `Stage.vue` calls `live2d.expressions.execute`, and the expression context calls the selected executor and schedules the reset. `Model.vue` uses either the Live2D expression overlay or the SDK expression manager, depending on the application's expression-system setting. The separate `emotion` field is a small generic enum and does not expose arbitrary 12 presets.

`act-contract.json` lists the exact character-specific names and original usage hints. A label describes the intended runtime interpretation, not an official expression title. Gesture references are translated into implemented facial axes; a facial preset does not imply an animated arm or a scene accessory. Visually validate each actual output before claiming it works.

Observed source entry points (relative to the AIRI checkout):

- `packages/stage-ui/src/services/airi-card-import-export.ts`
- `packages/stage-pages/src/pages/settings/airi-card/index.vue`
- `packages/stage-ui/src/stores/modules/airi-card.ts`
- `packages/stage-ui/src/constants/prompts/live2d-act.ts`
- `packages/pipelines-audio/src/llm-streaming-control/payloads.ts`
- `packages/stage-ui/src/components/scenes/Stage.vue`
- `packages/stage-ui-live2d/src/controls/manifest.ts`
- `packages/stage-ui-live2d/src/contexts/expressions.ts`
- `packages/stage-ui-live2d/src/components/scenes/live2d/Model.vue`

## Local defaults and optional wrapper initialization

The sample card selects existing providers:

| Module | Provider ID | Model / voice |
| --- | --- | --- |
| Consciousness | `openai-compatible` | `airi-qwen3.5-9b` |
| Vision | `vision-openai-compatible` | `airi-qwen3.5-9b` |
| Speech | `openai-compatible-audio-speech` | `phoenix-qwen3-tts-local` / `phoenix-soft` |

Configure provider endpoints separately: LLM and vision at loopback port 9941 `/v1/`, Qwen speech at port 9945 `/v1/` and the separately reused transcription service at port 9942 `/v1/`. Importing a character does not create providers. Hearing/ASR is a global AIRI setting in this revision, not a consumed per-card `AiriExtension.modules` field. The existing local ASR model is `sensevoice-local`; do not invent a card-only ASR field and claim it configures recording.

`merge-card.cjs` exports a pure `mergeNewCard(serializedMapOrEntries, nativeCard, {cardId, displayModelId?})`. It returns new entries/storage JSON and never reads or writes storage. It preserves every existing card and returns an existing ID unchanged, including user edits. It does not change providers, defaults, active cards or sessions. Supply a model ID only after AIRI has really registered the model. Do not edit running IndexedDB directly.

If an authorized wrapper uses this helper during a closed-app initialization transaction, merge only the requested new card. Do not loop over all cards to replace their module settings. After AIRI's card store is ready, use its `activateCard(id)` action if automatic activation is requested; the observed `activeCardId` is an in-memory ref initialized to `default`, not a reliable localStorage setting.

## Compatibility checks

With Node supporting source TypeScript stripping and an existing AIRI checkout:

```powershell
node character-tools/validate_cards.mjs /path/to/airi examples/phoenix/character.json work/card
```

This reads the installed AIRI CCC schema and ACT normalizer, validates the CCv3 card, checks the V2 field shape, exercises every exact expression name and verifies pure merge preservation/idempotence. It does not start AIRI, modify its sources, write its databases or prove rendered animation. `work/card/card-validation.json` states those limits.

`../examples/phoenix/sources.json` is the publishable provenance record: official URLs, approximate storyboard times and original observations. Local official images, frames and contact sheets are research references and must not be included in a public source-only repository. Character art rights and the proprietary Live2D Core remain separate from the program's code license.
