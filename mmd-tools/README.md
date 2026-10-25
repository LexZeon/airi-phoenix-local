# Native AIRI MMD idle motion

This MIT tool generates an original 12-second VMD idle and imports it through AIRI's existing motion store. It does not replace the renderer or patch AIRI source. The bundled example contains only original bone rotations and offsets; no official mesh, texture, or downloaded motion is included.

The verified route is `useMMD().addMotion(File)` followed by `idleMotionName`. `MMDScene` loads that VMD through the installed `@moeru/three-mmd` loader and loops its native Three.js animation action. Physics is disabled because the tested model's hair stretched with this AIRI/runtime combination. Physics behavior is not claimed to be fixed.

## Generate and validate

Use your local AIRI checkout and a PMX that you are allowed to use. Keep model files and inspection output private.

```powershell
node .\inspect-bones.mjs --airi-root=C:\path\to\airi --pmx=C:\private\model.pmx --out=C:\private\bones.json
python .\generate_idle.py --bones C:\private\bones.json --out C:\private\natural-idle.vmd --arm-gap 13 --elbow-bend 12
node .\validate_idle.mjs --airi-root=C:\path\to\airi --vmd=C:\private\natural-idle.vmd
node .\test-idle-driver.mjs
```

The generator estimates the rest upper-arm direction from the actual upper-arm and elbow positions. It lowers the arms to about 13 degrees from the torso, adds a small elbow bend, wrist adjustment, breathing and weight shift. Verify the result on each skeleton: names, axes, proportions, skirts and accessories vary. This example was visually checked on one locally supplied standard Japanese-named PMX skeleton. It is not a universal humanoid retargeter, walk cycle, hand gesture system or physics solution.

## Install in AIRI's renderer MAIN world

Run `mmd-idle-driver.js` in the same MAIN world as the original AIRI renderer after its MMD store exists. Supply the VMD bytes, for example from a local host-approved file read. Do not give renderer code arbitrary filesystem access.

```javascript
const result = await globalThis.installAiriMmdIdle({
  bytes: Uint8Array.from(vmdBytes),
  // Optional: the current built MMD store chunk URL, when the store is not mounted yet.
  // moduleUrl: new URL('./assets/<current-mmd-store-chunk>.js', location.href).href,
})
```

The helper finds Pinia through `#app.__vue_app__`, uses the native `mmd` store, waits up to 30 seconds, imports a browser `File`, sets `physicsEnabled=false` and selects the motion. Its return value includes the previous selection for restoration. Content-derived motion names prevent duplicate imports on repeated launches and avoid the native loader's stale-clip behavior when a different file reuses the same name. Native scene loading is asynchronous; confirm the scene's `listMotions()` includes the returned name before claiming playback.

No head, neck, eye or mouth tracks are generated. AIRI retains its gaze, blink, expression and audio lip-sync drivers. The generator verifies identical first and last poses and normalized quaternions using the actual installed VMD parser. Exact loop endpoints remove the loop seam; normal VMD linear interpolation still applies between keys.

## Verified evidence and limits

`verification.json` records reproducible parser, helper and independent renderer checks. The independent preview compiled AIRI's actual `packages/stage-ui-mmd/src/components/scenes/MMD.vue`, loaded the locally supplied model, registered this motion, rendered complete textured arms lowered beside the torso, and recorded 12 seconds. Source model assets, screenshots and private paths are omitted from this repository.

Official API/source references:

- [AIRI MMD scene](https://github.com/moeru-ai/airi/blob/main/packages/stage-ui-mmd/src/components/scenes/MMD.vue)
- [AIRI MMD store](https://github.com/moeru-ai/airi/blob/main/packages/stage-ui-mmd/src/stores/mmd.ts)
- [MMD runtime](https://github.com/moeru-ai/three-mmd)

The `main` branch may evolve. Verify these interfaces after updating AIRI. No official character license is granted by this tool's MIT license.
