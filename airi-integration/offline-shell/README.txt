AIRI offline desktop wrapper — verified integration notes

This template is copied by launchers/airi-env.ps1 to
  airi/apps/stage-tamagotchi/out/offline-shell
and started with the existing Electron x64 installation. Do not launch the template folder itself.
The original AIRI main/renderer remain unchanged. Update AIRI using the separate update shortcut;
normal launch reuses installed runtimes/models and does not download them.

Verified target
  AIRI 0.12.0, Electron 43.4.1 x64 on Windows ARM64.
  x64 is needed by the installed electron-click-drag-plugin binary.
  Model inference, SenseVoice and local TTS use the existing native ARM environment.

Profile application
  APP_USER_DATA_PATH selects the profile only when launching the wrapper directly.
  The supplied one-click launcher fixes it to <base>/runtime/airi-data; its updater backs up that directory.
  On a new preset revision, preload backs up only the localStorage keys it changes.
  The backup may contain prior provider credentials. Keep backups private.
  Providers, global module defaults, VAD settings and speech settings are applied before mount.
  Existing unrelated character cards retain their own module overrides.
  Managed cards are imported through the real Pinia display-model/card APIs.
  A selectionRevision updates only their provider/model/voice selections, preserving persona edits.

Private character models
  character.modelZip identifies the primary Live2D ZIP.
  additionalCharacters accepts explicit live2d-zip or pmx-zip entries, each with a distinct id/cardFile/modelZip.
  Model paths must resolve to ordinary files inside the configured companions/characters tree.
  The helper serves only the specifically configured model ZIPs, with GET/HEAD; it does not browse directories.
  The 3D importer verifies SHA256 and pmx-zip persistence before binding an MMD avatar.
  The user MMD package uses one primary character PMX with unchanged bytes/textures and UTF-8 ZIP names.
  Weapon/alternative PMX files are excluded from that working ZIP so the loader chooses the intended body.
  Physics is off for the current model because its hair stretches with the current physics integration.
  This does not establish that arbitrary MMD models have working physics.

Chat stickers
  Separate from Live2D expressions. Use the public sticker-tools generator with a selected private manifest.
  The generated script contains image bytes: keep it outside the public repository and ZIP.
  stickers.importScriptFile can point to that explicitly generated local script.
  It calls the real Pinia stickers.save API, checks image hashes, uses stable IDs, and preserves conflicting user edits.
  The actual app import remains a separate acceptance check; helper unit tests alone do not prove chat rendering.

Offline runtime assets and network
  Chromium permits loopback HTTP/HTTPS/WS/WSS and local/data/blob resources; external requests are cancelled.
  The Node TCP guard also blocks non-loopback connections by default. No OS firewall/privacy setting is modified.
  VAD model is served from the existing local speech service.
  Install-AiriOfflineShell copies the exact installed Transformers ORT JS/WASM pair to renderer assets.
  Recognized CDN library requests resolve to those local bundled assets; models/private endpoints are not inferred.
  Offline update-check failures are expected and do not make chat/audio unavailable.

Screen context
  The primary display is sampled in memory, bounded to 1280x720, on the configured interval.
  Local vision creates a brief summary and publishes ReplaceSelf context to AIRI's own channel.
  The wrapper does not store screenshots, summaries or chat text in diagnostics.
  No new capture starts while one is running. Tray controls can pause this source.

Verification
  GET http://127.0.0.1:9943/health returns sanitized readiness, managed-card, asset and screen counters.
  It does not expose provider keys, channel token, screen contents or arbitrary code execution.
  The synthetic SDK verifier uses its own binding and records counts, not user conversations.
  AIRI_TEST_TTS_HEALTH explicitly selects loopback 9942 or 9945 for that verification.
  API/SDK connectivity, physical microphone endpointing, audible playback, Core validation and visual acceptance
  are different checks. Report only the checks that actually ran.

Overrides
  AIRI_COMPANIONS_ROOT, AIRI_DESKTOP_ROOT, AIRI_ORIGINAL_MAIN, AIRI_ORIGINAL_RENDERER,
  AIRI_OFFLINE_PRESET, AIRI_OFFLINE_VAD_MAP, AIRI_SERVER_SDK_PATH, AIRI_CHANNEL_CONFIG_PATH,
  APP_USER_DATA_PATH, SERVER_CHANNEL_PORT, AIRI_OFFLINE_HEALTH_PORT, AIRI_OFFLINE_ICON.

Public distribution
  Publish reviewed source/templates and verified procedures. Exclude actual profiles/settings, backups,
  private sticker payloads, chat/screenshots, model weights, Core/SDK binaries, and official/user artwork/models.

Snapshot limitation: additional characters, stickers and MMD idle initialization currently require an enabled, valid primary Live2D entry. The public example disables all managed imports; it does not promise a standalone additional-MMD-only wrapper setup. See SETUP.md.
