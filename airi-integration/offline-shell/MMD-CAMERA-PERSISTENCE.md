# MMD camera persistence wrapper patch

The implementation patches the compiled renderer MMD component only. It does not edit upstream tracked source or rebuild AIRI. The patcher defaults to a read-only check; writes require `--apply`.

```powershell
& '<node.exe>' '<offline-wrapper>/patch-mmd-camera.cjs' --assets '<AIRI>/out/renderer/assets' --check
& '<node.exe>' '<offline-wrapper>/patch-mmd-camera.cjs' --assets '<AIRI>/out/renderer/assets' --apply
& '<node.exe>' '<offline-wrapper>/verify-mmd-camera.cjs' --assets '<AIRI>/out/renderer/assets'
```

The wrapper owner should invoke the patch before launching the updated renderer, check its exit code, and abort launch on failure. Exactly one top-level JavaScript asset must contain the MMD.vue source-region marker. Each setup, fit, load, disposal, watcher, and FOV anchor must match once. Existing incomplete or incompatible patches fail closed. `--apply` syntax-checks the result with Node, creates an original-hash-named `.bak`, checks the original hash again, then replaces the asset with an atomic same-directory rename. Repeat apply leaves the file unchanged. A backup is never executed as a JavaScript asset. Do not blindly restore a backup over a newer upstream release; use the backup whose original hash belongs to that asset.

V2 can upgrade an installed V1 patch only with its matching original `.airi-mmd-camera-v1.<hash>.bak`. The frozen generator and helper in `camera-patch-v1/` must be shipped beside the new patcher. Replaying the frozen V1 generator over that backup must reproduce the **entire installed file byte for byte**. Only then does V2 patch the validated original in memory. V2 backs up the installed V1 file separately before replacement and leaves the original backup intact. A missing/ambiguous backup, edited old patch, or unrelated changed bytes fails without replacement. No blind stripping or string replacement of an old patch is permitted.

## Keys and data

Keys remain `airi-offline:mmd-camera:v1:stage:<encodeURIComponent(modelId)>` and independently `airi-offline:mmd-camera:v1:preview:<encodeURIComponent(modelId)>`, preserving existing saved views across patch versions. V2 chooses `stage` only for the native wrapper's explicit `fullscreen-host=main-window` URL role with the root hash route (`#/`). Settings routes and other roles use `preview`, even if an audio context is present. Missing/invalid URL context fails to preview. No audio readiness assumption is involved. A missing/invalid model ID still renders with the upstream fit and disables persistence.

The source audio store constructs `shallowRef(new AudioContext())` synchronously, and Stage immediately calls `createGain()`. That source does not establish an asynchronous initial-null audio-context race. V1's prop-based scope inference was nevertheless an indirect context assumption; V2 replaces it with the wrapper's explicit role/route and adds observable diagnostics. Do not report a scope mismatch as the proven cause of a native framing failure until the actual native status has been read.

An independently reproduced V1 failure was its immediate check of `componentState.value === 'mounted'` after assigning that controlled `v-model`. The actual bundled Vue `useModel` setter emits an update, but its getter retains the old prop value until the parent update reaches the child. The check could therefore reject restoration with no retry, despite the camera seed being present. The tests create an actual Vue renderer with a controlled child model to prove that timing, reproduce lost restoration with the frozen V1 compiled setup, and verify V2 restoration with the same delayed prop return. V2 readiness uses a scene-local flag set only after successful runtime initialization and fit, and cleared synchronously on disposal; it never relies on reading back a freshly emitted parent-controlled prop.

Only these fields are serialized:

```json
{"version":1,"modelId":"example-model","position":[0,1,3],"target":[0,1,0],"up":[0,1,0],"fov":30,"near":0.1,"far":1000,"savedAt":0}
```

Values must be finite and in bounded ranges; zero distance, zero up, or parallel up/view direction is rejected. Bad data and unavailable localStorage fall back to the normal fit without crashing or replacing the bad entry. Position, target, up, FOV, near, and far restore after successful model loading and default fit. Restoration never writes the global camera-FOV store. A subsequent model with no entry starts from the upstream global FOV/default up and normal fit, rather than inheriting the previous model's restored projection.

Changes are debounced for 150 ms, with Orbit `end` and unmount flushing the last captured immutable snapshot. Initialization, fitting, restoration, and pre-load controls events cannot save. Each asynchronous load owns a generation, model ID, and source ticket: stale results are discarded before scene ownership, stale initialization cannot fit, and stale failures cannot dispose the current model. Pending old-model snapshots retain their captured old key when props change.

## Private initial seed for an already selected view

The wrapper owner can seed before launching/activating the model using this helper. Pass private model IDs and view values from private configuration; do not put them in public source, reports, or example files.

```javascript
const { buildMmdCameraSeedScript } = require('./mmd-camera-state.cjs');
const script = buildMmdCameraSeedScript(actualDisplayModelId, privateCameraView, 'stage');
const result = await window.webContents.executeJavaScript(script, true);
```

This validates the seed before emitting JavaScript. The renderer writes only if the exact key is absent. Existing values, even malformed ones, are preserved. The script uses localStorage directly, never a shell or a network request. A bootstrap already executing in the renderer may instead embed `createMmdCameraPersistence.toString()` and call `seedIfMissing(modelId, view)`.

Only position/target/up define the initial orientation; a quaternion is not serialized. A target derived from camera forward preserves initial projection, but its distance may differ from the user's true Orbit pivot. The next real controls change saves the actual `controls.target`. Subsequent seeds do not replace it.

## Safe renderer diagnostics

```javascript
const status = window.__airiOfflineMmdCameraDiagnostics?.() ?? [];
// [{scope: 'stage'|'preview', restored: boolean, loadStatus: string}]
```

The getter returns only those three fields for mounted MMD instances. It returns no model IDs, storage keys, sources, camera values, or user text. The wrapper owner can collect it with `webContents.executeJavaScript` and whitelist these same fields into health output. An instance unregisters on unmount. `loadStatus` distinguishes `idle`, `loading`, `fitted`, `restored`, `fit-no-saved-view`, invalid/unavailable storage, missing model IDs, and `load-failed`. `restored: true` means a validated saved view was applied after loading/fit; it does not by itself prove that later model transforms or the visible crop match an earlier screenshot.

## Verification boundary

`verify-mmd-camera.cjs` tests the self-contained factory in a separate VM, the actual patched compiled MMD setup with a synthetic engine, the actual bundled Vue controlled-model update timing, and actual bundled Three.js/OrbitControls without a canvas/GPU. It checks numerical projection round trips, residual damping, load races, delayed parent prop updates, separate scopes/models, missing IDs, bad storage, default-fit behavior, V1 upgrade verification, idempotence, and failure without mutation. Apply tests use a disposable copied asset directory; the real asset is read only.

The report explicitly separates these checks from native application acceptance. Mouse drag and application restart persistence, the private current-view seed, WebGL visuals, and any wrapper integration require owner verification. No native service, audio, or UI is started by the tests.

## Native wrapper result

The wrapper was subsequently started with V2 through the actual launcher. Its [anonymous native report](verification/native-start-screen-camera-20261025.json) records `scope=stage`, `restored=true`, `loadStatus=restored` and zero renderer diagnostic errors. The visible native close-up was compared with the user's selected pre-restart view and matched its crop. Existing saved state was preserved rather than reseeded. No model IDs, camera coordinates or screenshots are distributed as evidence.

This verifies restoration of that previously saved view in the real app. A separate fresh mouse-drag/save/restart user flow is not claimed by this report; interaction persistence and projection equality are also covered by the 41-case production/Three/Vue test suite. Numerical and native visual evidence remain distinct.
