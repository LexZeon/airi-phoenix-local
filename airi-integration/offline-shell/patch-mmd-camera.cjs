#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const childProcess = require('node:child_process');
const { createMmdCameraPersistence, resolveMmdCameraScope, registerMmdCameraDiagnostic } = require('./mmd-camera-state.cjs');
const legacyV1 = require('./camera-patch-v1/patch-mmd-camera.cjs');

const REGION = '//#region ../../packages/stage-ui-mmd/src/components/scenes/MMD.vue';
const BEGIN = '/* AIRI_MMD_CAMERA_PERSISTENCE_V2_BEGIN';
const END = '/* AIRI_MMD_CAMERA_PERSISTENCE_V2_END */';
const factorySource = createMmdCameraPersistence.toString();
const scopeSource = resolveMmdCameraScope.toString();
const diagnosticSource = registerMmdCameraDiagnostic.toString();
const helperHash = sha256(factorySource);
const integrationHash = sha256(scopeSource + '\n' + diagnosticSource);
function sha256(value) { return crypto.createHash('sha256').update(value).digest('hex'); }
function count(text, needle) { return text.split(needle).length - 1; }
function once(text, before, after, label) {
  if (count(text, before) !== 1) throw new Error('anchor_mismatch:' + label);
  return text.replace(before, after);
}
function section(source) {
  if (count(source, REGION) !== 1) throw new Error('mmd_region_not_unique');
  const start = source.indexOf(REGION);
  const end = source.indexOf('//#endregion', start);
  if (end < 0) throw new Error('mmd_region_unterminated');
  return { start, end, text: source.slice(start, end) };
}
function patchSource(source) {
  const region = section(source);
  let text = region.text;
  for (const anchor of ['\t\tfunction setupScene() {\n', '\t\tfunction frameCamera() {\n']) {
    if (count(text, anchor) !== 1) throw new Error('anchor_mismatch:scene_functions');
  }
  if (source.includes(BEGIN) || source.includes(END)) {
    if (count(source, BEGIN) !== 1 || count(source, END) !== 1
      || !text.includes(`${BEGIN} helperSha256=${helperHash} integrationSha256=${integrationHash} */`)
      || !text.includes(factorySource)
      || !text.includes(scopeSource) || !text.includes(diagnosticSource)
      || count(text, 'airiMmdCamera.attach(controls);') !== 1
      || count(text, 'airiMmdCamera.beginLoad(props.modelId, src);') !== 1
      || count(text, 'airiMmdCamera.finishLoad(airiCameraLoad);') !== 1
      || count(text, 'airiMmdCamera.suspend();') !== 1
      || count(text, 'airiMmdCamera.didFit(airiCameraLoad, frameCamera() === true);') !== 1
      || count(text, 'if (!airiMmdCamera.isCurrent(airiCameraLoad)) return;') !== 2
      || count(text, 'if (!airiMmdCamera.isCurrent(airiCameraLoad)) {') !== 1
      || count(text, 'const airiFitDamping = controls.enableDamping;') !== 1
      || count(text, 'airiMmdCamera.dispose();') !== 1
      || count(text, 'airiMmdCamera.changed();') !== 1
      || count(text, 'airiMmdCamera.loadFailed();') !== 1
      || count(text, 'airiCameraDiagnosticOff();') !== 1
      || count(text, 'let airiCameraModelLoaded = false;') !== 1
      || count(text, 'airiCameraModelLoaded = true;') !== 1
      || count(text, 'isLoaded: () => airiCameraModelLoaded && !!modelGroup && !!mesh') !== 1
      || !text.includes('watch([() => props.modelSrc, () => props.modelId]')) {
      throw new Error('partial_or_incompatible_camera_patch');
    }
    return { source, changed: false, helperHash, hooks: 11 };
  }
  if (/AIRI_MMD_CAMERA_PERSISTENCE_V\d_/.test(source)) throw new Error('legacy_patch_requires_verified_backup');
  if (text.includes('airiMmdCamera') || text.includes('airiCameraLoad')) throw new Error('camera_identifier_collision');
  text = once(text, '\t\tlet gaze;\n', '\t\tlet gaze;\n'
    + `\t\t${BEGIN} helperSha256=${helperHash} integrationSha256=${integrationHash} */\n`
    + '\t\tlet airiCameraModelLoaded = false;\n'
    + `\t\tconst airiMmdCamera = (${factorySource})({\n`
    + `\t\t\tscope: (${scopeSource})(window.location),\n`
    + '\t\t\tgetStorage: () => window.localStorage,\n'
    + '\t\t\tgetModelId: () => props.modelId, getSource: () => props.modelSrc,\n'
    + '\t\t\tgetCamera: () => camera, getControls: () => controls,\n'
    + '\t\t\tisLoaded: () => airiCameraModelLoaded && !!modelGroup && !!mesh\n'
    + '\t\t});\n'
    + `\t\tconst airiCameraDiagnosticOff = (${diagnosticSource})(window, () => airiMmdCamera.getDiagnostic());\n`
    + `\t\t${END}\n`, 'setup_state');
  text = once(text, '\t\t\tcontrols.enabled = props.enableOrbitControls;\n',
    '\t\t\tcontrols.enabled = props.enableOrbitControls;\n\t\t\tairiMmdCamera.attach(controls);\n', 'attach_controls');
  text = once(text, '\t\t\tcontrols.target.copy(center);\n\t\t\tcontrols.update();\n',
    '\t\t\tcontrols.target.copy(center);\n\t\t\tcontrols.update();\n\t\t\treturn true;\n', 'fit_success');
  text = once(text, '\t\tfunction frameCamera() {\n\t\t\tif (!camera || !controls || !modelGroup) return;\n',
    '\t\tfunction frameCamera() {\n\t\t\tif (!camera || !controls || !modelGroup) return;\n'
    + '\t\t\t// A prior model\'s restored FOV/up and damping must not become this model\'s default fit.\n'
    + '\t\t\tconst airiFitDamping = controls.enableDamping;\n'
    + '\t\t\tcontrols.enableDamping = false;\n\t\t\ttry { controls.update(); } finally { controls.enableDamping = airiFitDamping; }\n'
    + '\t\t\tcamera.up.set(0, 1, 0);\n\t\t\tcamera.fov = cameraFov.value;\n', 'per_model_fit_defaults');
  text = once(text, '\t\tfunction disposeModel() {\n',
    '\t\tfunction disposeModel() {\n\t\t\tairiMmdCamera.suspend();\n\t\t\tairiCameraModelLoaded = false;\n', 'dispose_disarm');
  text = once(text, '\t\t\tcomponentState.value = "loading";\n\t\t\tdisposeModel();\n\t\t\ttry {\n',
    '\t\t\tcomponentState.value = "loading";\n\t\t\tdisposeModel();\n'
    + '\t\t\tconst airiCameraLoad = airiMmdCamera.beginLoad(props.modelId, src);\n\t\t\ttry {\n', 'load_ticket');
  text = once(text, '\t\t\t\tresolved = await loadMMDModelFromSource(src, { cacheKey: props.modelId });\n',
    '\t\t\t\tconst airiLoadedMmd = await loadMMDModelFromSource(src, { cacheKey: props.modelId });\n'
    + '\t\t\t\tif (!airiMmdCamera.isCurrent(airiCameraLoad)) {\n'
    + '\t\t\t\t\ttry { airiLoadedMmd.mmd.dispose(); } finally {\n'
    + '\t\t\t\t\t\ttry { disposeMMDObject(airiLoadedMmd.mesh); } finally { airiLoadedMmd.dispose(); }\n'
    + '\t\t\t\t\t}\n\t\t\t\t\treturn;\n\t\t\t\t}\n'
    + '\t\t\t\tresolved = airiLoadedMmd;\n', 'loaded_generation');
  text = once(text, '\t\t\t\tawait animation.init();\n',
    '\t\t\t\tawait animation.init();\n\t\t\t\tif (!airiMmdCamera.isCurrent(airiCameraLoad)) return;\n', 'init_generation');
  text = once(text, '\t\t\t\tframeCamera();\n',
    '\t\t\t\tairiMmdCamera.didFit(airiCameraLoad, frameCamera() === true);\n', 'fit_guard');
  text = once(text, '\t\t\t\tcomponentState.value = "mounted";\n\t\t\t\tawait syncMotions();\n\t\t\t} catch (err) {\n\t\t\t\tdisposeModel();\n',
    '\t\t\t\tcomponentState.value = "mounted";\n\t\t\t\tairiCameraModelLoaded = true;\n\t\t\t\tairiMmdCamera.finishLoad(airiCameraLoad);\n'
    + '\t\t\t\tawait syncMotions();\n\t\t\t} catch (err) {\n'
    + '\t\t\t\tif (!airiMmdCamera.isCurrent(airiCameraLoad)) return;\n\t\t\t\tdisposeModel();\n'
    + '\t\t\t\tairiMmdCamera.loadFailed();\n', 'restore_and_error_generation');
  text = once(text, '\t\tonUnmounted(() => {\n\t\t\tcancelAnimationFrame(rafHandle);\n',
    '\t\tonUnmounted(() => {\n\t\t\tairiMmdCamera.dispose();\n\t\t\tairiCameraDiagnosticOff();\n\t\t\tcancelAnimationFrame(rafHandle);\n', 'unmount_flush');
  text = once(text, '\t\twatch(() => props.modelSrc, (src) => {\n',
    '\t\twatch([() => props.modelSrc, () => props.modelId], ([src]) => {\n', 'watch_model_identity');
  text = once(text, '\t\twatch(cameraFov, () => {\n\t\t\tif (!camera) return;\n\t\t\tcamera.fov = cameraFov.value;\n\t\t\tcamera.updateProjectionMatrix();\n\t\t});',
    '\t\twatch(cameraFov, () => {\n\t\t\tif (!camera) return;\n\t\t\tcamera.fov = cameraFov.value;\n\t\t\tcamera.updateProjectionMatrix();\n\t\t\tairiMmdCamera.changed();\n\t\t});', 'fov_save');
  const patched = source.slice(0, region.start) + text + source.slice(region.end);
  // Re-run all idempotence guards before permitting a write.
  if (patchSource(patched).changed) throw new Error('camera_patch_not_idempotent');
  return { source: patched, changed: true, helperHash, hooks: 12 };
}
function inspectAssets(assets) {
  const dir = path.resolve(assets);
  if (!fs.statSync(dir).isDirectory()) throw new Error('assets_not_directory');
  const candidates = fs.readdirSync(dir).filter(name => name.endsWith('.js')).map(name => path.join(dir, name))
    .filter(file => fs.readFileSync(file, 'utf8').includes(REGION));
  if (candidates.length !== 1) throw new Error('mmd_chunk_count:' + candidates.length);
  const file = candidates[0];
  const original = fs.readFileSync(file, 'utf8');
  let baseSource = original;
  let upgradeFrom = null;
  let verifiedBackup = null;
  if (original.includes('AIRI_MMD_CAMERA_PERSISTENCE_V1_')) {
    const prefix = path.basename(file) + '.airi-mmd-camera-v1.';
    const backups = fs.readdirSync(dir).filter(name => name.startsWith(prefix) && /^[a-f0-9]{12}\.bak$/.test(name.slice(prefix.length)));
    const matching = [];
    for (const name of backups) {
      const backup = fs.readFileSync(path.join(dir, name), 'utf8');
      if (name !== prefix + sha256(backup).slice(0, 12) + '.bak') continue;
      try {
        const replay = legacyV1.patchSource(backup);
        // Byte-for-byte replay validates the entire old patch AND all unrelated
        // code. A damaged/unknown patch cannot be silently discarded.
        if (replay.changed && replay.source === original) matching.push({ name, backup });
      } catch { /* Not a matching original for the installed V1 patch. */ }
    }
    if (matching.length !== 1) throw new Error('legacy_v1_backup_not_unique_or_patch_modified:' + matching.length);
    baseSource = matching[0].backup;
    verifiedBackup = matching[0].name;
    upgradeFrom = 'v1';
  }
  const result = patchSource(baseSource);
  return { file, original, baseSource, upgradeFrom, verifiedBackup, originalSha256: sha256(original), ...result };
}
function syntaxCheck(source) {
  const result = childProcess.spawnSync(process.execPath, ['--check', '--input-type=module'], {
    input: source, encoding: 'utf8', windowsHide: true, timeout: 30000, maxBuffer: 1024 * 1024,
  });
  if (result.error || result.status !== 0) throw new Error('patched_syntax_invalid');
}
function runCli(args) {
  let assets;
  let apply = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--assets' && args[i + 1]) assets = args[++i];
    else if (args[i] === '--apply') apply = true;
    else if (args[i] === '--check') { /* Read-only is also the default. */ }
    else throw new Error('usage: patch-mmd-camera.cjs --assets <renderer/assets> [--check|--apply]');
  }
  if (!assets) throw new Error('assets_required');
  const result = inspectAssets(assets);
  syntaxCheck(result.source);
  let backup = null;
  if (apply && result.changed) {
    if (sha256(fs.readFileSync(result.file)) !== result.originalSha256) throw new Error('asset_changed_during_check');
    backup = result.file + '.airi-mmd-camera-v2.' + result.originalSha256.slice(0, 12) + '.bak';
    if (fs.existsSync(backup)) {
      if (sha256(fs.readFileSync(backup)) !== result.originalSha256) throw new Error('backup_hash_mismatch');
    } else fs.writeFileSync(backup, result.original, { flag: 'wx' });
    const temp = result.file + '.airi-mmd-camera.' + process.pid + '.' + crypto.randomBytes(6).toString('hex') + '.tmp';
    try {
      fs.writeFileSync(temp, result.source, { flag: 'wx' });
      if (sha256(fs.readFileSync(result.file)) !== result.originalSha256) throw new Error('asset_changed_before_replace');
      fs.renameSync(temp, result.file);
    } finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
  }
  return { ok: true, mode: apply ? 'apply' : 'check', chunk: path.basename(result.file),
    status: result.changed ? (apply ? 'patched' : 'ready') : 'already-patched',
    originalSha256: result.originalSha256, patchedSha256: sha256(result.source),
    helperSha256: helperHash, integrationSha256: integrationHash,
    upgradeFrom: result.upgradeFrom, verifiedBackup: result.verifiedBackup,
    backup: backup ? path.basename(backup) : null };
}
module.exports = { patchSource, inspectAssets, syntaxCheck, runCli, helperHash, integrationHash, REGION };
if (require.main === module) {
  try { process.stdout.write(JSON.stringify(runCli(process.argv.slice(2))) + '\n'); }
  catch (error) { process.stderr.write(JSON.stringify({ ok: false, error: error.message }) + '\n'); process.exitCode = 1; }
}
