Layered Rig Toolkit (MIT)

Requirements: Python 3.10 or newer, Pillow (see requirements.txt).
The MIT py-moc3 serializer snapshot is included with its full license and
upstream commit/hashes in vendor/py-moc3/provenance.json. Cubism Core is NOT
included. Supply your own legally obtained Core JavaScript file and Node.js
for binary/geometry validation. The tool does not use Codex-specific APIs.

Quick start, from the repository root:
  python rig-tools/rig.py init --out my-character --name MyCharacter --json
  python rig-tools/rig.py inspect --project my-character/project.json --json
  python rig-tools/rig.py build --project my-character/project.json --out build/MyCharacter --json
  python rig-tools/rig.py validate --model build/MyCharacter/MyCharacter.model3.json --core-file /path/to/live2dcubismcore.min.js --node-executable node --json

init copies a working, original robot example with real PNG artwork. Replace
its sources, placements and effects with your own legally usable artwork.
The compiler accepts explicit transparent layers, atlas cells and polygon
crops. It does not promise automatic semantic rigging from any single image.

Project coordinates are source-image pixels; rect is destination [x,y,w,h].
polygon is an explicit alpha-mask in source-image coordinates. A polygon
without rect keeps its original source placement including 3-pixel padding.
With rect, the cropped polygon is resized and placed at that destination.
An optional source_overlays array can composite an externally supplied
patch into explicit polygons only; target/source are existing source aliases,
rect is destination [x,y,w,h], and optional crop is source [l,t,r,b].
Every source overlay reports zero changes outside its explicit hard mask.
It performs no inpainting or semantic image synthesis. Neutral reconstruction
and all texture provenance are saved in the build output's authoring folder.

See project.schema.json for supported fields. inspect enforces its vocabulary
and then semantic constraints such as real RGBA PNG sources, unique names,
valid effect bindings, expression ranges, actual mask drawables, and finite
mesh dimensions. One layer has a rectangular grid mesh; groups apply effects
to their members. value_mode defaults to normalized distance from the
parameter default; raw uses the raw value. weight_rect localizes a geometric
effect in [left,top,right,bottom,feather] coordinates. weight_y supplies a
full/zero influence interval. aperture uses interpolation points; clipping
masks are actual MOC3 mask drawables referenced by their layer IDs.

UVs use PNG top-down coordinates. Core and the runtime shader handle their
own V conversion; do not introduce a second manual flip. The validator
checks actual Core UV origins to catch this regression. It also checks
binary consistency/corrupt magic rejection, every vertex/index, parameter
influence, exact keyform endpoint probes, distinct expressions, mixed poses,
model3 texture/expression references, parameter IDs in expressions/motions/
physics, and Head/Body hit drawable references. All model3 runtime files
must exist at safe relative paths, with nonempty data and decodable PNG/JSON.
validate is read-only unless --report-dir is explicitly provided. It expects
the build-manifest.json produced by this compiler next to model3.

All CLI stdout responses are a single JSON object:
  {ok, stage, code, outputs: [file paths], summary: {...}}
Failures contain message and optional details. code is a stable string;
exit status 0=success, 2=input/schema, 3=internal/build, 4=runtime validation.
No paid service, remote agent, or global Python installation is needed.

Optional actual visual proof uses an existing AIRI compiled Pixi renderer,
an existing Electron executable, and an existing licensed Core:
  python rig-tools/rig.py render --model build/MyCharacter/MyCharacter.model3.json --core-file /path/to/core.js --renderer-dir /path/to/airi/out/renderer --electron-executable /path/to/electron --out visual-proof --json
This opens only a hidden, isolated test page with its own temporary profile,
not the user's AIRI window. It produces WebGL PNGs for UV/XY diagnostics,
expressions, blink/mouth/gaze/head/breath. It is an optional integration test;
AIRI's private hashed bundle export names may change between versions.
A Core PASS alone never establishes visual quality or artistic likeness.

Run python -m unittest discover -s rig-tools/tests to test the machine
contract and missing-runtime regressions. Optional environment variables
LIVE2D_CORE_FILE and NODE enable the real Core fixture test as well.

Licensing: compiler code and original robot example are MIT. Your artwork,
character IP, model output and Core/runtime usage retain their own rights.
Official-derived character textures used in local evaluation are not part of
the toolkit distribution. Do not publish third-party art merely because the
compiler is open source.
