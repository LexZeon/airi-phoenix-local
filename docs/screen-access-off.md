# Unified screen access: verified stop behavior

The local helper and AIRI's monitor/computer-use button previously represented separate switches. The helper could continue its 20-second screen-summary work while the chat button only changed which tools were offered to a turn. Its default preset was also enabled. The implementation now uses the helper's boolean as the single source of truth, with startup default disabled.

## Changes

- `offline-settings.json`: changed only `screen.enabled` from true to false. Model, voice, character, camera, and other personal values are preserved.
- `main.cjs`: disabling immediately advances the capture epoch and aborts an in-flight inference request. It re-checks permission after awaiting Electron's thumbnail call, so disabling during capture cannot start a later inference request. Late responses cannot publish. Stop/enable transitions serialize context cleanup.
- The helper removes only its activity writer, `local-offline-vision:screen-observer`, through AIRI's actual `chat-context.removeContextWriter` API. It then closes the SDK connection. Empty `replace-self` text is deliberately not used as a deletion mechanism.
- `preload.cjs`: narrow IPC connects only AIRI's own local main frames to get/set screen permission. The main process validates the frame again. There is no new HTTP write endpoint.
- `screen-control-bootstrap.js`: the existing `[data-testid="computer-use-toggle"]` button and tray both control the helper. The helper broadcasts its state to native windows. Late replicated Pinia defaults are corrected and cannot authorize capture. Explicit button clicks are the path that grants UI permission; ordinary state replication is not.
- Both already registered and subsequently registered `computer_use` / `computer_use_read_image` executors check main-process permission before execution and after completion. Disabled calls are blocked; results arriving after an epoch change are discarded. A native command already started before permission changes is not forcibly killed by this wrapper.
- Disabling also stops any instantiated vision-debug ticker and screen-capture ambient sampling. Manual image attachments remain separate from desktop observation.
- An independent capability writer, `local-offline-capabilities:screen-permission`, says that screen observation and computer control are off, that old records are not the current interface, and that the character must not claim to see it. This contains no screen data. Turning access on removes this status. User chat history is not deleted.
- Read-only helper health reports only four renderer booleans per window: `computerUseEnabled`, `capabilityStatusPresent`, `screenWriterPresent`, `visionTickerRunning`. Context text/history is not exposed.

## Verified checks

1. `node --check` passes for main, preload, and the new bootstrap.
2. `verification/verify-screen-stop.cjs` executes the actual production lifecycle functions with synthetic adapters. Five cases pass: disabled start; disabling during thumbnail; disabling during HTTP with an intentionally ignored abort and late response; disabling during SDK connect; and rapid off/on ordering. No real desktop capture, model inference, or app restart occurs in this test.
3. `verification/verify-screen-controls.cjs` executes the production bootstrap with Pinia/IPC adapters and the production `structuredClone` definition projection. Fifteen checks pass, including actual bundled Vue reactive definitions, cross-window state, tool guards, future registrations, late result rejection, capability status add/remove, retaining unrelated contexts, rapid on/off while IPC replies are delayed, and rejecting a late replicated enabled default.
4. `verification/verify-screen-context-protocol.mjs` tests the running local SDK channel and installed compiled core registry. Its synthetic context is routed only to its test observer, not the AIRI conversation. SDK close produces module de-announcement; removing that writer leaves no active bucket. Empty `replace-self` leaves one entry and therefore is not deletion. No private event payload is read or retained.
5. Local source and the installed compiled context bridge both remove a departed module's writer on `extension:module:de-announced`. The installed compiled UI contains the expected `computer-use-toggle` selector. The existing launcher already copies all top-level offline-wrapper files, so the new bootstrap needs no installer change.

## Native app validation

After preserving the user's 3D framing, the updated native shell was restarted and its existing UI button exercised. The [anonymous native report](../airi-integration/offline-shell/verification/native-start-screen-camera-20261025.json) records:

- The native button was explicitly enabled and the helper published a screen observation, demonstrating that the UI controlled the actual worker.
- Turning it off removed one activity writer. Both observed windows reported `computerUseEnabled=false`, `capabilityStatusPresent=true`, `screenWriterPresent=false` and `visionTickerRunning=false`; the helper was disabled and no longer capturing.
- `publishedCount` stayed unchanged over **79.07 seconds**, longer than three 20-second cycles. The helper remained off, with zero renderer diagnostic errors.
- Tool execution rejection while disabled was validated by the production bootstrap test; a live native tool was not deliberately executed merely to repeat that check.

This does not make the model forget historical messages. The capability status instructs it not to treat earlier descriptions as current observation; an explicit live-conversation test of its wording remains separate. The synthetic report still accurately says it did not restart the real app; native evidence is the separate report above.

## Reactive tool definitions must become plain data

The first native run exposed a `DataCloneError` not represented by a plain-object stub. AIRI's production `addTools` serializes the tool definition with `structuredClone`. Shallow-spreading a Vue reactive definition leaves nested `function`/schema values as Proxy objects. The wrapper now deep-clones only the whitelisted JSON definition fields and wraps `execute` separately. The test reproduces the old nested-Proxy rejection with actual bundled Vue and verifies both existing and newly registered tools. Passing a syntax check or a non-reactive stub alone would not establish this path.

## Upstream meanings checked

- `tamagotchi-tool-selection` uses a synchronized, non-persisted `computerUseEnabled=ref(true)` upstream; the local bootstrap safely overrides and binds that default without changing the upstream repository.
- The separate vision developer page starts with `sendContextUpdates=false`; its `vision-processing.isRunning` starts false. `vision.useForChat` and `vision.useForToolImages` are image interpretation options, not a background screen-observation switch.
- `devtools:io-tracer.isRecording` starts false. The Hearing playground's monitoring flag starts false. These are distinct from ongoing voice conversation recording; no microphone setting was changed by this screen repair.
