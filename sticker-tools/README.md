# Local AIRI chat stickers: verified preparation and import API

This tool prepares a device-local sticker pack from images you already have. It performs deterministic crop/PNG conversion, preserves aspect ratio, records source hashes and transformations, and produces a manifest for AIRI's existing sticker store. It never downloads media or uploads application data. The separate catalog query reads one public official MiYouShe metadata endpoint.

For Phoenix, the prepared local set contains nine **static official-video-frame crops**. The source index is [official-sources.json](official-sources.json). The returned official MiYouShe catalog did not identify a Phoenix set; an official downloadable complete pack has not been verified. The selected images reuse the already verified official channel's public storyboard cache. No fan artwork, restricted video stream, AI redraw, or speculative leak pack was substituted. Source images and prepared stickers stay outside this repository and its ZIP.

## What was verified

- Nine actual source images decoded and produced PNGs inside AIRI's size limits; each local manifest entry records input/output SHA-256, nominal source time, and crop coordinates.
- The import helper's five Node tests passed: stable-ID repeat import, path/ID rejection, all hashes checked before writes, preservation of existing user edits, and metadata/frequency validation. These tests use a synthetic store; they do not by themselves prove main-app rendering.
- Five actual-PNG preparation tests also passed, including exact repeat output, preservation of existing edits, input/crop/metadata rejection, and dry-run behavior.
- A controlled MAIN-world run against the actual running AIRI store imported all nine stickers successfully, enabled stickers, and selected frequency 50. The host's settings-library visual check and an actual chat reply choosing/rendering a sticker remain pending. Successful persistence is not a complete chat-rendering test.

## Prepare images

Use Python with Pillow installed. All input files must resolve inside the explicit asset root; output files are new or identical, and conflicting existing images/manifests are preserved.

```text
python sticker-tools/prepare_stickers.py --recipe /path/to/recipe.json --asset-root /path/to/local-character --out /path/to/local-sticker-pack
```

A minimal recipe has `pack_id`, optional source metadata, and `items`:

```json
{
  "pack_id": "my-character-stickers",
  "items": [{
    "id": "gentle-smile",
    "file": "my-local-image.png",
    "name": "Character: gentle smile",
    "emotions": ["happy", "affectionate"],
    "source_url": "https://example.com/the-actual-source-page",
    "crop": [0, 0, 256, 256]
  }]
}
```

`crop` uses original pixel coordinates `[left,top,right,bottom]`; omit it to keep the full image. `max_side` defaults to 256 and only downsizes. The output manifest contains deterministic `custom-*` identities and relative PNG filenames. Repeating the same recipe reproduces the same output. Animated input is rejected rather than silently flattened. The official-frame pack's labels describe an interpretation of the visible expression; they are not official emotion names.

To check the currently returned official catalog without downloading images:

```text
python sticker-tools/query_official_catalog.py --name 菲欧妮 --name 菲歐妮 --name Phoenix --out /path/to/local-query-result.json
```

An access-control error is a failure to stop at. Neither script contains cookie extraction, login automation, CAPTCHA handling, restricted-stream fetching, or blocked-URL fallback.

## Use the real AIRI store

Verified source locations in an AIRI checkout:

- `packages/stage-ui/src/stores/modules/stickers.ts`: Pinia store ID `stickers`; `load`, `add`, `save`, `remove`, and reply-catalog selection.
- `packages/stage-ui/src/libs/stickers/import.ts`: metadata, MIME, byte and dimension validation.
- `packages/stage-ui/src/database/repos/stickers.repo.ts`: local `airi-stickers` IndexedDB, `entries` and `images` stores, serialized by a Web Lock.
- `packages/stage-ui/src/components/modules/stickers.vue`: settings form, also shown at `/settings/modules/stickers`.

The existing settings UI imports one PNG/JPEG/WebP/GIF with a name and at least one emotion label. Images must be nonempty, at most 2 MiB, and no side greater than 4096 pixels. Names are trimmed to 1–80 characters. Valid labels are `happy`, `sad`, `confused`, `surprised`, `thanks`, `celebrate`, `angry`, `tired`, `affectionate`, `awkward`, `agree`, and `disagree`.

For a controlled application integration, call [import-pack.mjs](import-pack.mjs) in the renderer's **MAIN world**, passing the real store and a trusted local loader. Do not write raw IndexedDB records or edit a live LevelDB profile.

```js
const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia
const store = pinia._s.get('stickers')
// The normal chat store initializes this store. If it is not present,
// initialize the installed useStickersStore(pinia) export first.
const result = await importStickerPack({
  store,
  manifest, // parsed local manifest.json
  loadBytes: async filename => localImages[filename], // trusted Uint8Array data
  enabled: true,
  frequency: 50,
})
```

The host may read the explicitly selected local pack and pass its bytes through its own trusted IPC; the browser helper has no filesystem or credential access. It verifies content hashes before mutations, then calls `store.save(stableCustomId,name,emotions,File)`. AIRI performs its own image decoding, Web Lock, persistence, refresh, and cross-window broadcast. Matching entries are reused on repeat import. Different existing image/metadata is reported and left intact. If a storage error interrupts a pack, repeating the operation resumes matching entries without creating duplicates.

To prepare a self-contained private payload for a host that already has a controlled MAIN-world execution mechanism:

```text
python sticker-tools/build_import_script.py --manifest /path/to/local-pack/manifest.json --out /path/to/private/import-main-world.js --frequency 50
```

The generated file contains local image bytes. The generator refuses to write it inside this public repository. Keep it local, never add it to a release or paste its contents into a public issue. It does not execute against the app by itself. If needed, `--store-module <installed-chunk-basename.js>` enables the version-dependent store initialization fallback described below.

Do not assume a compiled chunk's hash filename is stable across AIRI updates. If the store is not yet initialized, locate the installed chunk containing `settings/stickers/enabled`; import its export whose function has `$id === 'stickers'`, then call it with the existing Pinia instance. Recheck the installed source/API after updates.

## Relationship to the character card

Chat stickers are a **device-wide library and setting**. They are separate from Live2D expression JSON and from role-card consciousness/vision/speech module selection. Switching character cards does not create a separate sticker collection.

`store.enabled` persists as `settings/stickers/enabled`; `store.frequency` as `settings/stickers/frequency`. The UI offers 25, 50, 75 and 100. Frequency controls whether a reply receives the sticker catalog, not a guaranteed attachment count. At 100 the model still chooses whether a sticker is appropriate. Existing built-in stickers remain eligible unless the user removes them; this tool does not silently delete them or rewrite role-card prompts.

For Phoenix-specific selection, meaningful names prefixed with the character's name help the model choose. A role prompt can prefer that prefix when selecting an available sticker, but no per-character sticker filter was found in the installed store. Confirm a real chat message renders the saved local artwork before declaring the whole feature verified.

Run helper tests with `node --test sticker-tools/test-import-pack.mjs` and preparation tests with `python sticker-tools/test_prepare.py`. The tool code is MIT; official character/image rights remain separate and no official images are bundled here.

## Actual native settings acceptance

The running AIRI Settings → modules → stickers page was checked: enabled ON, frequency50, twelve default entries preserved plus nine new character entries, and several added official-frame thumbnails visibly rendered. This establishes real-store import/persistence/settings/thumbnail rendering. It does not establish that the model selected and attached a sticker in a real chat reply; that remains separate. Local verification screenshots include a private chat overlay and are deliberately not published.
