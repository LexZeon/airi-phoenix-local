'use strict';

// Self-contained so the wrapper patcher can embed this factory in the renderer.
// No character IDs, camera seeds, or other user state belong in this file.
function createMmdCameraPersistence(options = {}) {
  const PREFIX = 'airi-offline:mmd-camera:v1:';
  const scope = options.scope === 'preview' ? 'preview' : 'stage';
  const later = options.schedule || ((fn, ms) => setTimeout(fn, ms));
  const cancel = options.cancel || (handle => clearTimeout(handle));
  const now = options.now || (() => Date.now());
  const delay = Number.isFinite(options.debounceMs) ? Math.max(0, options.debounceMs) : 150;
  let generation = 0;
  let active = null;
  let ready = false;
  let fitted = false;
  let applying = false;
  let disposed = false;
  let pending = null;
  let timer = null;
  let attached = null;
  let lastSignature = null;

  function modelId(value) {
    if (typeof value !== 'string' || !value.trim() || value.length > 256) return null;
    const id = value.trim();
    try { encodeURIComponent(id); } catch { return null; }
    return id;
  }
  function keyFor(value) {
    const id = modelId(value);
    return id ? PREFIX + scope + ':' + encodeURIComponent(id) : null;
  }
  function storage() {
    try { return options.getStorage ? options.getStorage() : options.storage; } catch { return null; }
  }
  function vector(value) {
    return Array.isArray(value) && value.length === 3
      && value.every(n => typeof n === 'number' && Number.isFinite(n) && Math.abs(n) <= 1e6);
  }
  function validate(value, expectedId) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const id = modelId(expectedId);
    if (!id || value.version !== 1 || value.modelId !== id
      || !vector(value.position) || !vector(value.target) || !vector(value.up)) return null;
    const upLength2 = value.up.reduce((sum, n) => sum + n * n, 0);
    const distance2 = value.position.reduce((sum, n, i) => sum + (n - value.target[i]) ** 2, 0);
    const direction = value.position.map((n, i) => n - value.target[i]);
    const cross = [direction[1] * value.up[2] - direction[2] * value.up[1],
      direction[2] * value.up[0] - direction[0] * value.up[2],
      direction[0] * value.up[1] - direction[1] * value.up[0]];
    const crossLength2 = cross.reduce((sum, n) => sum + n * n, 0);
    if (upLength2 < 1e-12 || distance2 < 1e-12 || crossLength2 / (upLength2 * distance2) < 1e-12) return null;
    if (typeof value.fov !== 'number' || !Number.isFinite(value.fov) || value.fov < 1 || value.fov > 175
      || typeof value.near !== 'number' || !Number.isFinite(value.near) || value.near < 1e-6
      || typeof value.far !== 'number' || !Number.isFinite(value.far) || value.far <= value.near || value.far > 1e9) return null;
    if (value.savedAt !== undefined && (!Number.isFinite(value.savedAt) || value.savedAt < 0)) return null;
    return { version: 1, modelId: id, position: value.position.slice(), target: value.target.slice(),
      up: value.up.slice(), fov: value.fov, near: value.near, far: value.far,
      savedAt: value.savedAt === undefined ? now() : value.savedAt };
  }
  function read(id) {
    const key = keyFor(id);
    if (!key) return null;
    try {
      const raw = storage()?.getItem(key);
      return raw === null || raw === undefined ? null : validate(JSON.parse(raw), modelId(id));
    } catch { return null; }
  }
  function seedIfMissing(id, view) {
    const key = keyFor(id);
    const validated = validate({ ...view, version: 1, modelId: modelId(id) }, modelId(id));
    if (!key || !validated) return { seeded: false, reason: 'invalid' };
    try {
      const store = storage();
      if (!store) return { seeded: false, reason: 'unavailable' };
      // Even a malformed existing entry is user state: do not replace it with a seed.
      if (store.getItem(key) !== null) return { seeded: false, reason: 'exists' };
      store.setItem(key, JSON.stringify(validated));
      return { seeded: true, key };
    } catch { return { seeded: false, reason: 'unavailable' }; }
  }
  function identityMatches(ticket) {
    return !disposed && ticket && active && ticket.generation === generation
      && ticket.id === active.id && ticket.src === active.src
      && ticket.id === modelId(options.getModelId?.()) && ticket.src === options.getSource?.();
  }
  function snapshot(id) {
    try {
      const camera = options.getCamera?.();
      const controls = options.getControls?.();
      if (!camera || !controls) return null;
      return validate({ version: 1, modelId: id,
        position: [camera.position.x, camera.position.y, camera.position.z],
        target: [controls.target.x, controls.target.y, controls.target.z],
        up: [camera.up.x, camera.up.y, camera.up.z],
        fov: camera.fov, near: camera.near, far: camera.far, savedAt: now() }, id);
    } catch { return null; }
  }
  function signature(value) {
    if (!value) return null;
    return JSON.stringify([value.position, value.target, value.up, value.fov, value.near, value.far]);
  }
  function flush() {
    if (timer !== null) { cancel(timer); timer = null; }
    const saved = pending;
    pending = null;
    if (!saved) return false;
    // The immutable snapshot owns its old model ID. Never recapture with new props here.
    try {
      const store = storage();
      if (!store) return false;
      store.setItem(keyFor(saved.modelId), JSON.stringify(saved));
      return true;
    } catch { return false; }
  }
  function suspend() {
    flush();
    generation += 1;
    active = null;
    ready = false;
    fitted = false;
    lastSignature = null;
  }
  function beginLoad(id, src) {
    suspend();
    const validId = modelId(id);
    // modelId is optional upstream. Missing/invalid IDs still render with the
    // normal fit, but cannot read or write any persistent camera entry.
    if (disposed || typeof src !== 'string' || !src) return null;
    active = Object.freeze({ id: validId, src, generation });
    return active;
  }
  function didFit(ticket, succeeded) {
    if (identityMatches(ticket)) fitted = succeeded === true;
  }
  function finishLoad(ticket) {
    if (!identityMatches(ticket) || !fitted || !options.isLoaded?.()) return false;
    const camera = options.getCamera?.();
    const controls = options.getControls?.();
    if (!camera || !controls) return false;
    const saved = read(ticket.id);
    applying = true;
    ready = false;
    try {
      if (saved) {
        const damping = controls.enableDamping;
        controls.enableDamping = false;
        try {
          // Clear residual damping from the previous fit/interaction before restore.
          controls.update();
          camera.position.set(...saved.position);
          camera.up.set(...saved.up);
          camera.fov = saved.fov;
          camera.near = saved.near;
          camera.far = saved.far;
          controls.target.set(...saved.target);
          camera.lookAt(controls.target);
          camera.updateProjectionMatrix();
          controls.update();
        } finally { controls.enableDamping = damping; }
      }
      lastSignature = signature(snapshot(ticket.id));
      ready = lastSignature !== null && identityMatches(ticket);
      return ready;
    } finally { applying = false; }
  }
  function changed() {
    if (!ready || applying || !identityMatches(active) || !options.isLoaded?.()) return false;
    const value = snapshot(active.id);
    const next = signature(value);
    if (!value || next === lastSignature) return false;
    lastSignature = next;
    pending = value;
    if (timer !== null) cancel(timer);
    timer = later(() => { timer = null; flush(); }, delay);
    return true;
  }
  function detach() {
    attached?.removeEventListener?.('change', changed);
    attached?.removeEventListener?.('end', flush);
    attached = null;
  }
  function attach(controls) {
    detach();
    if (disposed) return;
    attached = controls;
    attached?.addEventListener?.('change', changed);
    attached?.addEventListener?.('end', flush);
  }
  function dispose() {
    suspend();
    disposed = true;
    detach();
  }
  return { keyFor, validate, read, seedIfMissing, beginLoad, isCurrent: identityMatches,
    didFit, finishLoad, changed, attach, flush, suspend, dispose };
}

function buildMmdCameraSeedScript(modelId, view, scope = 'stage') {
  if (scope !== 'stage' && scope !== 'preview') throw new Error('invalid_camera_scope');
  const helper = createMmdCameraPersistence({ scope });
  if (!helper.keyFor(modelId)) throw new Error('invalid_camera_model_id');
  const normalizedId = modelId.trim();
  const validated = helper.validate({ ...view, version: 1, modelId: normalizedId }, normalizedId);
  if (!validated) throw new Error('invalid_camera_seed');
  // Return JavaScript as data for webContents.executeJavaScript; never a shell command.
  return '(' + createMmdCameraPersistence.toString() + ')({getStorage:()=>window.localStorage,scope:'
    + JSON.stringify(scope) + '}).seedIfMissing(' + JSON.stringify(normalizedId) + ',' + JSON.stringify(validated) + ')';
}

module.exports = { createMmdCameraPersistence, buildMmdCameraSeedScript };
