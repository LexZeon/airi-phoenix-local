---
name: airi-character-forge
description: Create or revise AIRI character companions with sourced personas, configured Live2D meshes and expressions, optional local Chinese speech, and portable character packages. Use for agent-assisted character production or AIRI integration, not a standalone illustration or a ChatGPT Work pet.
---

# AIRI Character Forge

Use this folder as the tool root. It contains executable code, project examples and prompts; no particular AI account or image provider is required. Resolve bundled paths relative to this file, not the current working directory.

## Work from the current project

Read the user's requested character, target app and supplied assets. Reuse an existing project when revising it. Inspect the project JSON and current build reports before regenerating artwork or replacing files. Preserve the user's manual edits.

- For a new character, read [prompts/character-and-art.md](prompts/character-and-art.md). First check existing Live2D and 3D/MMD references and their terms, unless already supplied or offline authoring was requested. For HoYoverse and similar games prioritize official distribution and the verified publisher account on 模之屋/Aplaybox. Download/reference/desktop use/redistribution permissions differ. Preserve the chosen pose and identity; obtain independent facial components without forcing a symmetric redesign.
- For binding or an existing asset pack, read [prompts/rig-and-expressions.md](prompts/rig-and-expressions.md) and the schema bundled with `rig-tools`. Exact geometry and placement belong in project JSON, not character-specific code branches.
- For running and handing off the result, read [prompts/verify-and-deliver.md](prompts/verify-and-deliver.md). The CLI interface and optional MCP entry are described in [START_HERE.md](START_HERE.md) and [docs/agent-api.md](docs/agent-api.md).
- For persona/card, speech or AIRI provider work, read [prompts/voice-and-airi.md](prompts/voice-and-airi.md). Reuse installed model files and working environments when compatible. The optional voice service uses built-in Serena plus original style instructions, not actor cloning. A speech-only request does not require new artwork or a Live2D rebuild. The shared [SenseVoice/Melo service](shared-speech/README.md) and [offline wrapper templates](airi-integration/offline-shell/SETUP.md) preserve existing model reuse; fixed synthetic [latency probes](diagnostics/README.md) separate measured stages from physical playback. Do not switch a working default to an unmeasured online option.
- For chat stickers/emote packs, verify AIRI's separate chat setting and official resource sources. These are not model3 facial expressions. Retain source URLs/acquisition code and a separate actual chat-UI check; restricted sticker assets stay outside public packages.
- For an existing permitted MMD model, use the native AIRI model/card and motion stores described in [airi-integration](airi-integration/README.md) and [mmd-tools](mmd-tools/README.md). A 3D request does not require rebuilding it as Live2D. Retarget original idle data per skeleton and preserve gaze/blink/lip-sync tracks; model physics and actual audio playback remain separate checks.
- For startup and observation controls, use [Windows sign-in](docs/windows-sign-in.md) and [unified screen permission](docs/screen-access-off.md). Launching the application does not authorize screen collection; preserve the user's current view and explicit off state. For slow text, first verify the actual thinking flag and prompt/cache/queue timing as in [the local audit](diagnostics/llm-latency-audit.md), rather than treating hidden reasoning or a tiny synthetic prompt as proof.
- For an explicitly requested online task button, the optional [official Codex CLI bridge](control-center/codex-task-assistant-verified.md) reuses the user's own login with a separate task form. Keep it separate from AIRI conversation providers. Do not read/export auth state, automatically send task content, or choose an existing task ID without the user's requested destination; metadata checks do not prove a continuation was sent.

The principal commands, run from this folder, are:

```text
python rig-tools/rig.py inspect --project <project.json> --json
python rig-tools/rig.py build --project <project.json> --out <output-directory> --json
python rig-tools/rig.py validate --model <output/Model.model3.json> --core-file <existing-Live2D-Core.js> --json
```

Use the returned `ok`, `code`, `outputs` and `summary` fields to decide the next step. Keep diagnostic logs separate from JSON stdout. If a stage fails, address the reported cause and rerun that stage before claiming success. CLI help is the source of truth if a command changes.

For a clean smoke test, `init` copies a real original robot project. The independently adapted [DeskBot example](examples/deskbot/README.md) also supplies repeatable post-build Idle/Demo motion3 authoring. The generic project schema does not author motions; it emits meshes, parameter bindings and expressions. Its validator requires its generated `build-manifest.json`, so it is not a universal validator for arbitrary downloaded models.

## Constraints that affect the result

- A static image, model JSON alone or a valid MOC header is not a working Live2D. Validate the produced MOC3 with the supplied target Core, exercise parameter combinations and visually inspect the avatar in the target renderer.
- Do not paint the original eyes underneath movable eye sprites. Blink, lip movement and named expressions must produce observable changes. Show material limitations such as shallow head rotation or a missing hand animation.
- Compare a face with the user's actual selected reference. Pupil/eye-white centroid equality is a diagnostic, not artistic acceptance; retain intentional convergence and upper-lid overlap. See [reference-face QA](docs/live2d-face-qa-lessons.md) for geometry, semantic pixel, renderer and native-app evidence boundaries.
- `inspect` enforces the bundled schema. `validate` checks every referenced runtime file before Core geometry tests; missing textures, expressions, motions or sound are failures. Actual target-renderer images remain a separate check. The optional `render` command uses an existing AIRI build/Electron/Core in an isolated hidden test page; it never proves desktop import or speech integration by itself.
- Use the image tools available to the user's agent for semantic generation or inpainting. This tool performs deterministic cropping, atlas construction and mesh binding; it does not provide a trained universal single-image layer separator.
- Do not bundle Live2D Core, third-party model weights or official character media merely because they can be downloaded. Keep code licensing, original asset licensing and character IP separate; see [RIGHTS.md](RIGHTS.md).
- Installing into an application or publishing a repository follows the user's requested scope. A build request does not itself request publishing or changing unrelated app profiles.

## Handoff

Leave the project JSON, relative asset paths, generation prompts, source index, build/validation report and final output paths together. Mark unperformed runtime checks explicitly. Another agent should be able to continue from files without the original conversation.

This project's author requests ongoing public records of AIRI configuration, changes and debugging. Follow `AGENTS.md` and [docs/airi-change-recording.md](docs/airi-change-recording.md): publish reviewed reusable code/templates, sanitized process and actual test evidence, excluding personal data and restricted assets.

The Phoenix example is a source-only production record: no official or official-derived images/model ZIP is included. Use robot/DeskBot to test the complete program, then supply your own permitted assets. Current Phoenix desktop acceptance remains unfinished; alternative costumes are deferred by the user; see [docs/process-log.md](docs/process-log.md).
