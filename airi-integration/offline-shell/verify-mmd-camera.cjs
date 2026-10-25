#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { pathToFileURL } = require('node:url');
const crypto = require('node:crypto');
const { createMmdCameraPersistence, buildMmdCameraSeedScript, resolveMmdCameraScope, registerMmdCameraDiagnostic } = require('./mmd-camera-state.cjs');
const { patchSource, inspectAssets, syntaxCheck, runCli, helperHash, REGION } = require('./patch-mmd-camera.cjs');
const legacyV1 = require('./camera-patch-v1/patch-mmd-camera.cjs');
const cases = [];
async function test(name, fn) { await fn(); cases.push({ name, passed: true }); }
class Vector {
  constructor(x = 0, y = 0, z = 0) { this.set(x, y, z); }
  set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; }
  copy(v) { return this.set(v.x, v.y, v.z); }
  clone() { return new Vector(this.x, this.y, this.z); }
}
class Camera {
  constructor(fov = 30, aspect = 1, near = 0.1, far = 1000) {
    Object.assign(this, { fov, aspect, near, far });
    this.position = new Vector(0, 1, 3); this.up = new Vector(0, 1, 0); this.projections = 0;
  }
  lookAt(target) { this.lookTarget = [target.x, target.y, target.z]; }
  updateProjectionMatrix() { this.projections++; }
}
class Controls {
  constructor(camera) { this.camera = camera; this.target = new Vector(0, 1, 0); this.listeners = new Map(); this.enableDamping = true; }
  addEventListener(name, fn) { if (!this.listeners.has(name)) this.listeners.set(name, new Set()); this.listeners.get(name).add(fn); }
  removeEventListener(name, fn) { this.listeners.get(name)?.delete(fn); }
  dispatch(name) { for (const fn of this.listeners.get(name) || []) fn(); }
  update() { this.camera.lookAt(this.target); this.dispatch('change'); }
  dispose() { this.listeners.clear(); }
}
function memoryStorage() {
  const data = new Map();
  let writes = 0;
  return { data, get writes() { return writes; }, getItem: key => data.has(key) ? data.get(key) : null,
    setItem(key, value) { writes++; data.set(key, value); } };
}
const sample = () => ({ position: [0.2, 1.8, 1.1], target: [0.1, 1.75, 0], up: [0, 1, 0], fov: 35, near: 0.02, far: 300 });
function harness({ scope = 'stage', store = memoryStorage(), id = 'fixture-a', src = 'fixture:a' } = {}) {
  const state = { id, src, loaded: false };
  const camera = new Camera(); const controls = new Controls(camera); const timers = new Map(); let sequence = 0;
  const helper = createMmdCameraPersistence({ scope, storage: store,
    getModelId: () => state.id, getSource: () => state.src, getCamera: () => camera, getControls: () => controls,
    isLoaded: () => state.loaded, now: () => 123456,
    schedule(fn) { const handle = ++sequence; timers.set(handle, fn); return handle; }, cancel(handle) { timers.delete(handle); } });
  helper.attach(controls);
  function start() { state.loaded = false; return helper.beginLoad(state.id, state.src); }
  function fit(ticket) {
    camera.position.set(0, 1, 3); controls.target.set(0, 1, 0); controls.update(); helper.didFit(ticket, true);
    state.loaded = true; return helper.finishLoad(ticket);
  }
  function tick() { for (const [key, fn] of [...timers]) { timers.delete(key); fn(); } }
  return { state, camera, controls, helper, store, timers, start, fit, tick };
}
function view(camera, controls) {
  return { position: [camera.position.x, camera.position.y, camera.position.z],
    target: [controls.target.x, controls.target.y, controls.target.z],
    up: [camera.up.x, camera.up.y, camera.up.z], fov: camera.fov, near: camera.near, far: camera.far };
}
async function helperTests() {
  await test('scope uses exact native window role and route without audio-context readiness', () => {
    assert.equal(resolveMmdCameraScope('file:///synthetic/index.html?synced-leader=true&fullscreen-host=main-window#/'), 'stage');
    assert.equal(resolveMmdCameraScope('file:///synthetic/index.html?fullscreen-host=main-window#/settings/models'), 'preview');
    assert.equal(resolveMmdCameraScope('file:///synthetic/index.html?fullscreen-host=settings-window#/'), 'preview');
    assert.equal(resolveMmdCameraScope('file:///synthetic/index.html#/'), 'preview');
    assert.equal(resolveMmdCameraScope({ href: 'invalid' }), 'preview');
  });
  await test('diagnostics expose only scope, restored and loadStatus and unregister safely', () => {
    const target = {}; const stage = harness();
    const off = registerMmdCameraDiagnostic(target, () => ({ ...stage.helper.getDiagnostic(), modelId: 'must-not-escape', position: [1, 2, 3] }));
    const ticket = stage.start(); assert.deepEqual(target.__airiOfflineMmdCameraDiagnostics(), [{ scope: 'stage', restored: false, loadStatus: 'loading' }]);
    stage.helper.seedIfMissing(stage.state.id, sample()); stage.fit(ticket);
    assert.deepEqual(target.__airiOfflineMmdCameraDiagnostics(), [{ scope: 'stage', restored: true, loadStatus: 'restored' }]);
    off(); assert.deepEqual(target.__airiOfflineMmdCameraDiagnostics(), []);
    stage.helper.dispose(); assert.equal(stage.helper.getDiagnostic().loadStatus, 'disposed');
  });
  await test('factory is self-contained in a separate VM', () => {
    const factory = vm.runInNewContext('(' + createMmdCameraPersistence.toString() + ')');
    const helper = factory({ storage: memoryStorage() });
    assert.equal(helper.keyFor('模型:one'), 'airi-offline:mmd-camera:v1:stage:%E6%A8%A1%E5%9E%8B%3Aone');
  });
  await test('wrapper seed script writes only a missing key and validates before generation', () => {
    const store = memoryStorage(); const script = buildMmdCameraSeedScript('fixture-wrapper', sample());
    assert.equal(vm.runInNewContext(script, { window: { localStorage: store } }).seeded, true);
    assert.equal(vm.runInNewContext(script, { window: { localStorage: store } }).reason, 'exists');
    assert.equal(store.writes, 1); assert.throws(() => buildMmdCameraSeedScript('', sample()), /invalid/);
    assert.throws(() => buildMmdCameraSeedScript('fixture', { ...sample(), fov: 180 }), /invalid/);
  });
  await test('missing saved key preserves upstream fit without initial writes', () => {
    const h = harness(); const t = h.start(); h.controls.update(); assert.equal(h.fit(t), true); h.controls.update(); h.tick();
    assert.equal(h.store.writes, 0); assert.deepEqual(view(h.camera, h.controls).position, [0, 1, 3]);
  });
  await test('seed is write-once and uses whitelisted fields only', () => {
    const h = harness(); const seed = sample();
    assert.equal(h.helper.seedIfMissing(h.state.id, { ...seed, secret: 'excluded' }).seeded, true);
    const key = h.helper.keyFor(h.state.id); const original = h.store.getItem(key);
    assert.equal(JSON.parse(original).secret, undefined);
    assert.equal(h.helper.seedIfMissing(h.state.id, { ...seed, fov: 50 }).reason, 'exists');
    assert.equal(h.store.getItem(key), original);
  });
  await test('restore follows fit and preserves all seven camera fields', () => {
    const h = harness(); const expected = sample(); expected.up = [0.1, 1, 0];
    h.helper.seedIfMissing(h.state.id, expected); const writes = h.store.writes;
    const ticket = h.start(); assert.equal(h.fit(ticket), true); assert.deepEqual(view(h.camera, h.controls), expected);
    h.controls.update(); h.tick(); assert.equal(h.store.writes, writes); assert.equal(h.controls.enableDamping, true);
    assert.deepEqual(h.camera.lookTarget, expected.target);
  });
  await test('change snapshots real target, debounces writes, and end flushes', () => {
    const h = harness(); h.fit(h.start());
    h.camera.position.x = 0.25; h.controls.target.x = 0.15; h.controls.dispatch('change');
    h.camera.position.x = 0.3; h.controls.dispatch('change'); assert.equal(h.store.writes, 0); assert.equal(h.timers.size, 1);
    h.controls.dispatch('end'); assert.equal(h.store.writes, 1); assert.equal(h.timers.size, 0);
    assert.equal(h.helper.read(h.state.id).position[0], 0.3); assert.equal(h.helper.read(h.state.id).target[0], 0.15);
  });
  await test('already captured changes flush to the old key after props change', () => {
    const h = harness(); h.fit(h.start()); h.camera.position.x = 0.4; h.controls.dispatch('change');
    h.state.id = 'fixture-b'; h.state.src = 'fixture:b'; h.camera.position.x = 9; h.controls.dispatch('change'); h.tick();
    assert.equal(h.helper.read('fixture-a').position[0], 0.4); assert.equal(h.helper.read('fixture-b'), null);
  });
  await test('model switching restores separate views and invalidates stale tickets', () => {
    const h = harness(); const a = h.start(); h.fit(a); h.camera.position.x = 0.6; h.controls.dispatch('change');
    h.state.id = 'fixture-b'; h.state.src = 'fixture:b'; const b = h.start(); assert.equal(h.helper.isCurrent(a), false);
    assert.equal(h.helper.finishLoad(a), false); h.fit(b); assert.equal(h.camera.position.x, 0); assert.equal(h.helper.read('fixture-b'), null);
    h.state.id = 'fixture-a'; h.state.src = 'fixture:a'; h.fit(h.start()); assert.equal(h.camera.position.x, 0.6);
  });
  await test('same source with a new ID is a different lifecycle', () => {
    const h = harness(); const a = h.start(); h.state.id = 'fixture-b';
    assert.equal(h.helper.isCurrent(a), false); h.controls.dispatch('change'); h.tick(); assert.equal(h.store.writes, 0);
  });
  await test('preview cannot overwrite stage even for the same model ID', () => {
    const store = memoryStorage(); const stage = harness({ store }); const preview = harness({ store, scope: 'preview' });
    stage.helper.seedIfMissing(stage.state.id, sample()); preview.fit(preview.start()); preview.camera.position.x = 5;
    preview.controls.dispatch('change'); preview.tick(); stage.fit(stage.start());
    assert.equal(stage.camera.position.x, 0.2); assert.equal(preview.helper.read(preview.state.id).position[0], 5);
    assert.notEqual(stage.helper.keyFor(stage.state.id), preview.helper.keyFor(preview.state.id));
  });
  await test('bad JSON or mismatched ID falls back to fit without overwriting', () => {
    for (const raw of ['{broken', JSON.stringify({ ...sample(), version: 1, modelId: 'other' }), 'null']) {
      const h = harness(); const key = h.helper.keyFor(h.state.id); h.store.setItem(key, raw); const writes = h.store.writes;
      h.fit(h.start()); h.controls.update(); h.tick(); assert.equal(h.camera.position.x, 0); assert.equal(h.store.writes, writes);
      assert.equal(h.helper.seedIfMissing(h.state.id, sample()).reason, 'exists'); assert.equal(h.store.getItem(key), raw);
    }
  });
  await test('invalid finite ranges and degenerate camera geometry are rejected', () => {
    const h = harness(); const invalid = [
      { fov: 0 }, { fov: 176 }, { far: 0.001 }, { near: 0 }, { far: Infinity },
      { position: [NaN, 1, 3] }, { up: [0, 0, 0] }, { target: sample().position },
      { position: [0, 2, 0], target: [0, 1, 0], up: [0, 1, 0] }, { savedAt: -1 },
    ];
    for (const item of invalid) assert.equal(h.helper.seedIfMissing(h.state.id, { ...sample(), ...item }).reason, 'invalid');
    assert.equal(h.helper.keyFor(''), null); assert.equal(h.helper.keyFor('\ud800'), null);
    assert.equal(h.store.writes, 0);
  });
  await test('storage denial leaves rendering and interaction usable', () => {
    const store = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
    const h = harness({ store }); assert.equal(h.fit(h.start()), true); h.camera.position.x = 1; h.controls.dispatch('change');
    assert.doesNotThrow(() => h.tick()); assert.equal(h.helper.seedIfMissing(h.state.id, sample()).reason, 'unavailable');
    const deniedGetter = createMmdCameraPersistence({ getStorage() { throw new Error('denied'); } }); assert.equal(deniedGetter.read('a'), null);
  });
  await test('ID-less upstream models can load but never persist', () => {
    const h = harness({ id: undefined }); h.state.id = undefined; const ticket = h.start();
    assert.equal(h.helper.isCurrent(ticket), true); assert.equal(h.fit(ticket), false);
    h.camera.position.x = 1; h.controls.dispatch('change'); h.tick(); assert.equal(h.store.writes, 0);
  });
  await test('not-loaded and not-fitted states cannot save or restore', () => {
    const h = harness(); h.helper.seedIfMissing(h.state.id, sample()); const writes = h.store.writes; const ticket = h.start();
    h.state.loaded = true; assert.equal(h.helper.finishLoad(ticket), false); h.controls.dispatch('change'); h.tick(); assert.equal(h.store.writes, writes);
    h.helper.didFit(ticket, true); h.state.loaded = false; assert.equal(h.helper.finishLoad(ticket), false);
  });
  await test('unmount flushes the last captured view and removes listeners', () => {
    const h = harness(); const ticket = h.start(); h.fit(ticket); h.camera.position.x = 0.7; h.controls.dispatch('change'); h.helper.dispose();
    assert.equal(h.helper.read(h.state.id).position[0], 0.7); assert.equal(h.timers.size, 0);
    assert.equal(h.controls.listeners.get('change').size, 0); assert.equal(h.helper.isCurrent(ticket), false);
    h.camera.position.x = 8; h.controls.dispatch('change'); h.tick(); assert.equal(h.store.writes, 1);
  });
}
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
async function settle() { for (let i = 0; i < 8; i++) await Promise.resolve(); }
function fixtureOriginal(inspected) {
  if (!/AIRI_MMD_CAMERA_PERSISTENCE_V\d_/.test(inspected.baseSource)) return inspected.baseSource;
  const matches = new Set(); const dir = path.dirname(inspected.file); const prefix = path.basename(inspected.file) + '.airi-mmd-camera-';
  for (const name of fs.readdirSync(dir).filter(name => name.startsWith(prefix) && name.endsWith('.bak'))) {
    const source = fs.readFileSync(path.join(dir, name), 'utf8');
    if (/AIRI_MMD_CAMERA_PERSISTENCE_V\d_/.test(source)) continue;
    try { if (patchSource(source).source === inspected.source) matches.add(source); } catch { /* Not this asset's verified original. */ }
  }
  if (matches.size !== 1) throw new Error('verification_original_backup_required_for_patched_asset');
  return [...matches][0];
}

// Execute the actual patched compiled MMD setup with synthetic engine objects.
// This checks lifecycle injection, not only the helper's public API.
function componentHarness(patched, { id = 'fixture-a', audioContext = {}, store = memoryStorage(),
  href = 'file:///synthetic/index.html?synced-leader=true&fullscreen-host=main-window#/', controlledState = false } = {}) {
  const start = patched.indexOf(REGION), end = patched.indexOf('//#endregion', start);
  const region = patched.slice(start, end);
  const mounts = [], unmounts = [], watches = [], requests = [], cameras = [], controls = [], errors = [], discarded = [];
  let state;
  const props = { modelId: id, modelSrc: 'fixture:' + (id || 'no-id'), audioContext, enableOrbitControls: true, paused: false };
  const refs = {};
  for (const [key, value] of Object.entries({ physicsEnabled: false, ikEnabled: true, grantEnabled: true,
    physicsGravity: -9.8, gazeMode: 'none', position: { x: 0, y: 0 }, scale: 1, rotationY: 0,
    morphOverrides: {}, emotionActionMap: {}, materialOpacity: {}, idleMotionName: '', availableMotions: [],
    oneShotAction: null, cameraFov: 30, ambientColor: '#ffffff', ambientIntensity: 1,
    directionalColor: '#ffffff', directionalIntensity: 1, directionalPosition: { x: 0, y: 1, z: 1 },
    albedoGlow: 0, renderScale: 1 })) refs[key] = { value };
  class Group { constructor() { this.scale = { setScalar() {} }; this.rotation = {}; this.position = new Vector(); } add(mesh) { this.mesh = mesh; } updateMatrixWorld() {} }
  const globals = {
    defineComponent: value => value, mergeModels: (a, b) => ({ ...a, ...b }),
    useModel() {
      if (!controlledState) state = { value: 'pending' };
      else {
        let value = 'pending';
        state = { get value() { return value; }, set value(next) { Promise.resolve().then(() => { value = next; }); } };
      }
      return state;
    }, useMMD: () => ({}), storeToRefs: () => refs,
    ref: () => ({ value: { clientWidth: 400, clientHeight: 600 } }), toRef: (value, key) => ({ value: value[key] }),
    Clock: class { start() {} getDelta() { return 0.016; } },
    useMMDLipSync: () => ({ update() {} }), useMMDBlink: () => ({ update() {} }),
    useMMDEmote: () => ({ update() {} }), createGazeController: () => ({ update() {} }),
    createMorphController: () => ({ availableMorphs: [], resolvedSlots: ['vowel-a'] }),
    createMMDAnimationManager: resolved => ({ init: () => resolved.init.promise, dispose() { resolved.dead = true; }, update() {},
      setIKEnabled() {}, setGrantEnabled() {}, setGravity() {} }),
    onMounted: fn => mounts.push(fn), onUnmounted: fn => unmounts.push(fn), watch: (...args) => watches.push(args),
    PerspectiveCamera: class extends Camera { constructor(...args) { super(...args); cameras.push(this); } },
    OrbitControls: class extends Controls { constructor(camera) { super(camera); controls.push(this); } },
    WebGLRenderer: class { setPixelRatio() {} setSize() {} render() {} dispose() {} forceContextLoss() {} },
    Scene: class { add() {} remove() {} }, Group, Vector3: Vector, Vector2: Vector,
    Box3: class { setFromObject() { return this; } isEmpty() { return false; } getSize(v) { return v.set(1, 2, 1); } getCenter(v) { return v.set(0, 1, 0); } },
    AmbientLight: class {}, DirectionalLight: class { constructor() { this.position = new Vector(); } }, Color: class {}, SRGBColorSpace: 'srgb',
    ResizeObserver: class { observe() {} disconnect() {} }, requestAnimationFrame: () => 1, cancelAnimationFrame() {},
    window: { localStorage: store, devicePixelRatio: 1, location: { href } }, URL, setTimeout, clearTimeout,
    loadMMDModelFromSource(src, options) { const d = deferred(); requests.push({ ...d, src, options }); return d.promise; },
    disposeMMDObject: mesh => discarded.push(mesh), collectMMDMaterials: () => [], setMMDMaterialGlow() {}, applyMMDMaterialOpacity() {},
    errorMessageFrom: err => err.message, console: { warn() {}, error: (...args) => errors.push(args) }, require_jszip_min() {},
  };
  vm.runInNewContext(region + '\nglobalThis.fixtureComponent = MMD_default;', globals);
  globals.fixtureComponent.setup(props, { expose() {}, emit: (...args) => errors.push(args) });
  function asset(name) { return { mesh: { name }, mmd: { init: deferred(), dispose() { this.dead = true; } }, disposed: false, dispose() { this.disposed = true; } }; }
  function changeModel(id, src = 'fixture:' + id) {
    props.modelId = id; props.modelSrc = src;
    const entry = watches.find(([sources]) => Array.isArray(sources) && sources.length === 2
      && typeof sources[0] === 'function' && sources[0]() === props.modelSrc && sources[1]() === props.modelId);
    assert.ok(entry, 'compiled watch must include source and ID'); entry[1]([src, id]);
  }
  return { props, store, refs, mounts, unmounts, watches, requests, cameras, controls, errors, discarded, asset, changeModel,
    diagnostics: () => JSON.parse(JSON.stringify(globals.window.__airiOfflineMmdCameraDiagnostics())), get state() { return state; } };
}
async function componentTests(patched) {
  await test('real compiled setup fits then restores seeded stage view', async () => {
    const store = memoryStorage(); const seed = createMmdCameraPersistence({ storage: store }); seed.seedIfMissing('fixture-a', sample());
    const h = componentHarness(patched, { store }); h.mounts[0](); assert.equal(h.requests.length, 1);
    const a = h.asset('a'); h.requests[0].resolve(a); await settle(); a.mmd.init.resolve(); await settle();
    assert.equal(h.state.value, 'mounted'); assert.deepEqual(view(h.cameras[0], h.controls[0]), sample());
    assert.equal(store.writes, 1); assert.equal(h.errors.length, 0); h.unmounts[0]();
  });
  await test('compiled main window without an audio context still restores stage and exposes safe diagnostics', async () => {
    const store = memoryStorage(); createMmdCameraPersistence({ storage: store }).seedIfMissing('fixture-a', sample());
    const h = componentHarness(patched, { store, audioContext: null });
    assert.deepEqual(h.diagnostics(), [{ scope: 'stage', restored: false, loadStatus: 'idle' }]); h.mounts[0]();
    assert.equal(h.diagnostics()[0].loadStatus, 'loading'); const a = h.asset('a'); h.requests[0].resolve(a); await settle();
    a.mmd.init.resolve(); await settle(); assert.deepEqual(h.diagnostics(), [{ scope: 'stage', restored: true, loadStatus: 'restored' }]);
    assert.deepEqual(view(h.cameras[0], h.controls[0]), sample()); h.unmounts[0](); assert.deepEqual(h.diagnostics(), []);
  });
  await test('compiled controlled v-model prop lag cannot skip camera restoration', async () => {
    const store = memoryStorage(); createMmdCameraPersistence({ storage: store }).seedIfMissing('fixture-a', sample());
    const h = componentHarness(patched, { store, controlledState: true }); h.mounts[0](); const a = h.asset('a');
    h.requests[0].resolve(a); await settle(); a.mmd.init.resolve(); await settle();
    assert.equal(h.state.value, 'mounted'); assert.deepEqual(view(h.cameras[0], h.controls[0]), sample());
    assert.equal(h.diagnostics()[0].restored, true); h.unmounts[0]();
  });
  await test('compiled async loader discards a stale result before scene ownership', async () => {
    const h = componentHarness(patched); h.mounts[0](); h.changeModel('fixture-b'); const a = h.asset('a'), b = h.asset('b');
    h.requests[1].resolve(b); await settle(); b.mmd.init.resolve(); await settle();
    h.requests[0].resolve(a); await settle(); assert.equal(a.disposed, true); assert.equal(a.mmd.dead, true);
    assert.equal(h.discarded.includes(a.mesh), true); assert.equal(h.state.value, 'mounted'); assert.equal(h.errors.length, 0);
    h.controls[0].camera.position.x = 2; h.controls[0].dispatch('change'); h.controls[0].dispatch('end');
    assert.equal(createMmdCameraPersistence({ storage: h.store }).read('fixture-a'), null);
    assert.equal(createMmdCameraPersistence({ storage: h.store }).read('fixture-b').position[0], 2); h.unmounts[0]();
  });
  await test('compiled animation init cannot fit or restore after model switch', async () => {
    const h = componentHarness(patched); h.mounts[0](); const a = h.asset('a'); h.requests[0].resolve(a); await settle();
    h.changeModel('fixture-b'); const b = h.asset('b'); h.requests[1].resolve(b); await settle(); b.mmd.init.resolve(); await settle();
    h.cameras[0].position.x = 7; a.mmd.init.resolve(); await settle(); assert.equal(h.cameras[0].position.x, 7);
    assert.equal(h.errors.length, 0); assert.equal(h.state.value, 'mounted'); h.unmounts[0]();
  });
  await test('compiled preview uses its own scope and FOV changes save there', async () => {
    const h = componentHarness(patched, { audioContext: {}, href: 'file:///synthetic/index.html?fullscreen-host=main-window#/settings/models' }); h.mounts[0](); const a = h.asset('a');
    h.requests[0].resolve(a); await settle(); a.mmd.init.resolve(); await settle();
    h.refs.cameraFov.value = 42; h.watches.find(([source]) => source === h.refs.cameraFov)[1](); h.controls[0].dispatch('end');
    const preview = createMmdCameraPersistence({ storage: h.store, scope: 'preview' }); const stage = createMmdCameraPersistence({ storage: h.store });
    assert.equal(preview.read('fixture-a').fov, 42); assert.equal(stage.read('fixture-a'), null); h.unmounts[0]();
  });
  await test('compiled stale rejection does not dispose the new model', async () => {
    const h = componentHarness(patched); h.mounts[0](); h.changeModel('fixture-b'); const b = h.asset('b');
    h.requests[1].resolve(b); await settle(); b.mmd.init.resolve(); await settle(); h.requests[0].reject(new Error('stale failure')); await settle();
    assert.equal(h.state.value, 'mounted'); assert.equal(b.mmd.dead, undefined); assert.equal(h.errors.length, 0); h.unmounts[0]();
  });
  await test('compiled model with no saved view uses global fit FOV instead of previous restored FOV', async () => {
    const store = memoryStorage(); createMmdCameraPersistence({ storage: store }).seedIfMissing('fixture-a', { ...sample(), fov: 45, up: [0.1, 1, 0] });
    const h = componentHarness(patched, { store }); h.mounts[0](); const a = h.asset('a');
    h.requests[0].resolve(a); await settle(); a.mmd.init.resolve(); await settle(); assert.equal(h.cameras[0].fov, 45);
    h.changeModel('fixture-b'); const b = h.asset('b'); h.requests[1].resolve(b); await settle(); b.mmd.init.resolve(); await settle();
    assert.equal(h.cameras[0].fov, h.refs.cameraFov.value); assert.deepEqual(view(h.cameras[0], h.controls[0]).up, [0, 1, 0]);
    assert.equal(createMmdCameraPersistence({ storage: store }).read('fixture-b'), null); h.unmounts[0]();
  });
  await test('compiled model without an ID still mounts using upstream fit', async () => {
    const h = componentHarness(patched, { id: null }); h.mounts[0](); const a = h.asset('no-id');
    h.requests[0].resolve(a); await settle(); a.mmd.init.resolve(); await settle();
    assert.equal(h.state.value, 'mounted'); assert.equal(h.store.writes, 0); assert.equal(a.disposed, false); h.unmounts[0]();
  });
}
async function actualVueModelTests(inspected, original) {
  const imported = inspected.original.match(/from "(\.\/runtime-core\.esm-bundler-[^"]+\.js)"/);
  if (!imported) throw new Error('actual_vue_import_not_found');
  const file = path.resolve(path.dirname(inspected.file), imported[1]); const text = fs.readFileSync(file, 'utf8');
  const module = await import(pathToFileURL(file).href); const vue = {};
  for (const name of ['createRenderer', 'h', 'useModel', 'ref', 'nextTick']) {
    const match = text.match(new RegExp('\\b' + name + ' as ([\\w$]+)'));
    if (!match || typeof module[match[1]] !== 'function') throw new Error('actual_vue_export_missing:' + name);
    vue[name] = module[match[1]];
  }
  await test('actual bundled Vue controlled useModel setter does not immediately update its getter', async () => {
    const renderer = vue.createRenderer({
      createElement: tag => ({ tag, children: [], parent: null }), createText: text => ({ text, parent: null }),
      createComment: text => ({ text, parent: null }), setText(node, text) { node.text = text; }, setElementText(node, text) { node.text = text; },
      insert(node, parent) { node.parent = parent; parent.children.push(node); },
      remove(node) { if (node.parent) node.parent.children = node.parent.children.filter(item => item !== node); },
      parentNode: node => node.parent, nextSibling: () => null, patchProp() {},
    });
    let childModel, parentValue;
    const Child = { props: ['state'], emits: ['update:state'], setup(props) { childModel = vue.useModel(props, 'state'); return () => vue.h('fixture'); } };
    const Parent = { setup() { parentValue = vue.ref('loading'); return () => vue.h(Child, { state: parentValue.value, 'onUpdate:state': value => { parentValue.value = value; } }); } };
    const app = renderer.createApp(Parent); app.mount({ children: [] });
    assert.equal(childModel.value, 'loading'); childModel.value = 'mounted';
    assert.equal(parentValue.value, 'mounted'); assert.equal(childModel.value, 'loading');
    await vue.nextTick(); assert.equal(childModel.value, 'mounted'); app.unmount();
  });
  await test('frozen V1 loses restoration under the reproduced controlled-model timing', async () => {
    const store = memoryStorage(); createMmdCameraPersistence({ storage: store }).seedIfMissing('fixture-a', sample());
    const h = componentHarness(legacyV1.patchSource(original).source, { store, controlledState: true }); h.mounts[0]();
    const a = h.asset('a'); h.requests[0].resolve(a); await settle(); a.mmd.init.resolve(); await settle();
    assert.equal(h.state.value, 'mounted'); assert.notDeepEqual(view(h.cameras[0], h.controls[0]), sample());
    assert.equal(h.cameras[0].position.x, 0); h.unmounts[0]();
  });
}
async function actualOrbitTests(inspected) {
  const importMatch = inspected.original.match(/import \{([^\n]+)\} from "(\.\/three\.core-[^"]+\.js)";/);
  if (!importMatch) throw new Error('actual_three_import_not_found');
  const three = await import(pathToFileURL(path.resolve(path.dirname(inspected.file), importMatch[2])).href);
  const globals = {};
  for (const part of importMatch[1].split(',')) {
    const names = part.trim().split(/\s+as\s+/); globals[names[1] || names[0]] = three[names[0]];
  }
  const eventStart = inspected.original.indexOf('//#region ../../node_modules/.pnpm/three-stdlib@');
  const orbitStart = inspected.original.indexOf('/controls/OrbitControls.js', eventStart);
  const orbitEnd = inspected.original.indexOf('//#endregion', orbitStart);
  if (eventStart < 0 || orbitStart < 0 || orbitEnd < 0) throw new Error('actual_orbit_region_not_found');
  vm.runInNewContext(inspected.original.slice(eventStart, orbitEnd) + '\nglobalThis.fixtureOrbit = OrbitControls;', globals);
  const RealCamera = globals.PerspectiveCamera, RealOrbit = globals.fixtureOrbit, RealVector = globals.Vector3;
  function realHarness(store, id) {
    const camera = new RealCamera(30, 0.8, 0.1, 1000); const controls = new RealOrbit(camera);
    controls.enableDamping = true;
    const state = { id, src: 'fixture:' + id, loaded: false };
    const helper = createMmdCameraPersistence({ storage: store, getModelId: () => state.id,
      getSource: () => state.src, getCamera: () => camera, getControls: () => controls, isLoaded: () => state.loaded });
    helper.attach(controls);
    function load() {
      state.loaded = false; const ticket = helper.beginLoad(state.id, state.src);
      camera.position.set(0, 1, 4); controls.target.set(0, 1, 0); controls.update(); helper.didFit(ticket, true);
      state.loaded = true; helper.finishLoad(ticket); camera.updateMatrixWorld(true);
    }
    return { camera, controls, state, helper, load };
  }
  function near(a, b, epsilon = 1e-11) { assert.ok(Math.abs(a - b) < epsilon, `${a} != ${b}`); }
  await test('actual bundled OrbitControls restores pose and emits no initial write', () => {
    const store = memoryStorage(); const h = realHarness(store, 'actual-orbit-a'); const expected = sample();
    h.helper.seedIfMissing(h.state.id, expected); const writes = store.writes; h.load();
    view(h.camera, h.controls).position.forEach((n, i) => near(n, expected.position[i]));
    for (let i = 0; i < 60; i++) h.controls.update(); h.helper.flush(); assert.equal(store.writes, writes);
    assert.equal(h.controls.enableDamping, true); h.helper.dispose(); h.controls.dispose();
  });
  await test('actual Orbit interaction saves real target and restores identical projection', () => {
    const store = memoryStorage(); const a = realHarness(store, 'actual-orbit-b'); a.load();
    a.controls.setAzimuthalAngle(0.23); a.controls.setPolarAngle(1.45);
    for (let i = 0; i < 300; i++) a.controls.update();
    a.controls.target.add(new RealVector(0.1, 0.04, 0)); a.controls.update(); a.helper.flush(); a.camera.updateMatrixWorld(true);
    const pointA = new RealVector(0.1, 1.6, 0.1).project(a.camera);
    const stored = a.helper.read(a.state.id); assert.ok(stored); near(stored.target[0], a.controls.target.x);
    const b = realHarness(store, 'actual-orbit-b'); b.load(); const pointB = new RealVector(0.1, 1.6, 0.1).project(b.camera);
    near(pointA.x, pointB.x, 1e-8); near(pointA.y, pointB.y, 1e-8); near(pointA.z, pointB.z, 1e-8);
    a.helper.dispose(); b.helper.dispose(); a.controls.dispose(); b.controls.dispose();
  });
  await test('actual Orbit residual damping cannot overwrite a newly restored model', () => {
    const store = memoryStorage(); const h = realHarness(store, 'actual-orbit-c'); h.load();
    h.controls.setAzimuthalAngle(1.0); h.state.id = 'actual-orbit-d'; h.state.src = 'fixture:actual-orbit-d';
    const expected = sample(); h.helper.seedIfMissing(h.state.id, expected); h.load(); const writes = store.writes;
    for (let i = 0; i < 60; i++) h.controls.update(); h.helper.flush();
    view(h.camera, h.controls).position.forEach((n, i) => near(n, expected.position[i])); assert.equal(store.writes, writes);
    h.helper.dispose(); h.controls.dispose();
  });
}
async function main() {
  const index = process.argv.indexOf('--assets'); if (index < 0 || !process.argv[index + 1]) throw new Error('assets_required');
  const inspected = inspectAssets(process.argv[index + 1]);
  const original = fixtureOriginal(inspected);
  await helperTests();
  await test('current real compiled asset patches in memory and passes Node ESM syntax', () => syntaxCheck(inspected.source));
  await test('patch is idempotent without touching unrelated regions', () => {
    assert.equal(patchSource(inspected.source).changed, false);
    const a = original.indexOf(REGION), b = original.indexOf('//#endregion', a);
    assert.equal(inspected.source.slice(0, a), original.slice(0, a));
    assert.equal(inspected.source.slice(inspected.source.indexOf('//#endregion', a)), original.slice(b));
  });
  if (!original.includes('AIRI_MMD_CAMERA_PERSISTENCE_V1_BEGIN')) {
    await test('changed upstream anchor fails closed', () => assert.throws(() => patchSource(original.replace('function frameCamera()', 'function changedFrameCamera()')), /anchor_mismatch|camera_patch_not_idempotent/));
  }
  await test('duplicate MMD region and partial markers fail closed', () => {
    assert.throws(() => patchSource(original + '\n' + REGION), /not_unique/);
    assert.throws(() => patchSource(inspected.source.replace('AIRI_MMD_CAMERA_PERSISTENCE_V2_END', 'BROKEN_END')), /incompatible/);
  });
  await componentTests(inspected.source);
  await actualVueModelTests(inspected, original);
  await actualOrbitTests(inspected);
  const fixture = fs.mkdtempSync(path.join(__dirname, 'camera-fixture-'));
  try {
    const file = path.join(fixture, 'synthetic-chunk.js'); fs.writeFileSync(file, original);
    const fixtureNeedsPatch = patchSource(original).changed;
    await test('apply and repeat apply work only on a copied fixture', () => {
      const result = runCli(['--assets', fixture, '--apply']); assert.equal(result.status, fixtureNeedsPatch ? 'patched' : 'already-patched');
      assert.equal(runCli(['--assets', fixture, '--apply']).status, 'already-patched'); assert.equal(fs.readFileSync(file, 'utf8'), inspected.source);
      assert.equal(fs.readdirSync(fixture).filter(name => name.endsWith('.bak')).length, fixtureNeedsPatch ? 1 : 0);
      assert.equal(fixtureOriginal(inspectAssets(fixture)), original);
    });
    await test('ambiguous asset directory fails without modifying either candidate', () => {
      const copy = path.join(fixture, 'second.js'); fs.writeFileSync(copy, original); const before = fs.readFileSync(file, 'utf8');
      assert.throws(() => runCli(['--assets', fixture, '--apply']), /mmd_chunk_count:2/); assert.equal(fs.readFileSync(file, 'utf8'), before);
      assert.equal(fs.readFileSync(copy, 'utf8'), original);
    });
    const legacyDirectory = path.join(fixture, 'legacy-upgrade'); fs.mkdirSync(legacyDirectory);
    const legacyFile = path.join(legacyDirectory, 'legacy.js'); const legacySource = legacyV1.patchSource(original).source;
    const originalHash = crypto.createHash('sha256').update(original).digest('hex');
    const legacyBackup = legacyFile + '.airi-mmd-camera-v1.' + originalHash.slice(0, 12) + '.bak';
    fs.writeFileSync(legacyFile, legacySource);
    await test('V1 without a matching original backup fails without changing the installed asset', () => {
      assert.throws(() => runCli(['--assets', legacyDirectory, '--apply']), /legacy_v1_backup/);
      assert.equal(fs.readFileSync(legacyFile, 'utf8'), legacySource);
    });
    fs.writeFileSync(legacyBackup, original);
    await test('V1 upgrade checks the entire old patch by exact replay and preserves originals', () => {
      const check = runCli(['--assets', legacyDirectory, '--check']); assert.equal(check.upgradeFrom, 'v1');
      assert.equal(fs.readFileSync(legacyFile, 'utf8'), legacySource);
      const apply = runCli(['--assets', legacyDirectory, '--apply']); assert.equal(apply.upgradeFrom, 'v1');
      assert.equal(fs.readFileSync(legacyFile, 'utf8'), inspected.source); assert.equal(fs.readFileSync(legacyBackup, 'utf8'), original);
      assert.equal(fs.readFileSync(path.join(legacyDirectory, apply.backup), 'utf8'), legacySource);
      assert.equal(runCli(['--assets', legacyDirectory, '--apply']).status, 'already-patched');
    });
    await test('modified V1 code cannot be silently replaced even with an original backup', () => {
      const modified = legacySource.replace('controls.enableDamping = true;', 'controls.enableDamping = false;');
      assert.notEqual(modified, legacySource); fs.writeFileSync(legacyFile, modified);
      assert.throws(() => runCli(['--assets', legacyDirectory, '--apply']), /legacy_v1_backup/);
      assert.equal(fs.readFileSync(legacyFile, 'utf8'), modified);
    });
  } finally {
    const resolved = path.resolve(fixture); const parent = path.resolve(__dirname) + path.sep;
    if (!resolved.startsWith(parent) || !path.basename(resolved).startsWith('camera-fixture-')) throw new Error('unsafe_fixture_cleanup');
    fs.rmSync(resolved, { recursive: true, force: true });
  }
  const report = { schemaVersion: 1, passed: true, cases: cases.length, helperSha256: helperHash,
    coverage: cases, liveAssetModified: false, liveRendererRestarted: false, browserOrbitVisualVerified: false,
    actualBundledOrbitControlsVerified: true, numericalProjectionRoundTripVerified: true,
    actualVueControlledModelTimingVerified: true, frozenV1RestorationFailureReproduced: true,
    limits: ['Compiled lifecycle uses a synthetic engine VM; actual bundled Vue controlled-model timing and Three/OrbitControls are separately tested without a native window or GPU.',
      'Native restart, exact current closeup seed, and mouse drag/restart persistence require owner integration.'] };
  fs.writeFileSync(path.join(__dirname, 'mmd-camera-verification.json'), JSON.stringify(report, null, 2) + '\n');
  process.stdout.write(JSON.stringify(report) + '\n');
}
main().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
