'use strict'
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const { pathToFileURL } = require('node:url')
const source = fs.readFileSync(path.join(__dirname, '..', 'screen-control-bootstrap.js'), 'utf8')
const tick = () => new Promise(resolve => setImmediate(resolve))
let helper = { enabled: false, epoch: 0 }
const stateListeners = new Set()
let setterCalls = 0
let setterGate
const reports = []
let definitionProxyFactory
let actualVueProxyVerified = false
// This is deliberately the production addTools projection, not a spread of a
// fake plain object. structuredClone must actually reject nested Proxy objects.
function productionDefinition(tool) {
  return structuredClone({
    id: tool.id,
    type: tool.type,
    function: tool.function,
    ...(tool.defaultActive === undefined ? {} : { defaultActive: tool.defaultActive }),
    ...(tool.requiresExplicitSelection === undefined ? {} : { requiresExplicitSelection: tool.requiresExplicitSelection }),
    ...(tool.icon === undefined ? {} : { icon: tool.icon }),
  })
}
function nativeDeepProxy(value, cache = new WeakMap()) {
  if (!value || typeof value !== 'object') return value
  if (cache.has(value)) return cache.get(value)
  const proxy = new Proxy(value, { get(target, key, receiver) { return nativeDeepProxy(Reflect.get(target, key, receiver), cache) } })
  cache.set(value, proxy)
  return proxy
}
async function loadDefinitionProxyFactory() {
  const index = process.argv.indexOf('--assets')
  if (index < 0) { definitionProxyFactory = nativeDeepProxy; return }
  const assets = process.argv[index + 1]
  if (!assets) throw new Error('ASSETS_REQUIRED')
  const candidates = fs.readdirSync(assets).filter(name => /^runtime-core\.esm-bundler-.*\.js$/.test(name))
  if (candidates.length !== 1) throw new Error('VUE_RUNTIME_NOT_UNIQUE')
  const file = path.join(assets, candidates[0])
  const text = fs.readFileSync(file, 'utf8')
  const exported = text.match(/\breactive as (\w+)/)
  const isReactiveExported = text.match(/\bisReactive as (\w+)/)
  if (!exported || !isReactiveExported) throw new Error('VUE_REACTIVE_EXPORT_NOT_FOUND')
  const vue = await import(pathToFileURL(path.resolve(file)).href)
  definitionProxyFactory = vue[exported[1]]
  assert.equal(vue[isReactiveExported[1]](definitionProxyFactory({ nested: {} }).nested), true)
  actualVueProxyVerified = true
}
const bridge = {
  getState: async () => ({ ...helper }),
  setEnabled: async enabled => {
    if (setterGate) await setterGate
    helper = { enabled, epoch: helper.epoch + 1 }; setterCalls += 1
    for (const callback of stateListeners) callback({ ...helper })
    return { ...helper }
  },
  onState: callback => { stateListeners.add(callback); return () => stateListeners.delete(callback) },
  reportState: status => reports.push(status),
}
function makeWindow() {
  const listeners = new Set(), actionHooks = new Set(), executors = new Map()
  let nativeCalls = 0, tickerStops = 0
  const selection = new Proxy({ computerUseEnabled: true, $subscribe: callback => { listeners.add(callback); return () => listeners.delete(callback) } }, {
    set(target, key, value) { const changed = target[key] !== value; target[key] = value; if (changed) for (const callback of listeners) callback(); return true },
  })
  let storedDefinitions = []
  const tools = {
    get tools() { return definitionProxyFactory(storedDefinitions) },
    getToolsByNames: name => tools.tools.filter(definition => definition.function.name === name).map(definition => ({ type: definition.type, function: definition.function, execute: executors.get(definition.id) })),
    addTools: (...args) => {
      for (const hook of actionHooks) hook({ name: 'addTools', args })
      const definitions = [...tools.tools]
      for (const tool of args) {
        const definition = productionDefinition(tool)
        const index = definitions.findIndex(item => item.id === tool.id)
        executors.set(tool.id, tool.execute)
        if (index < 0) definitions.push(definition); else definitions[index] = definition
      }
      storedDefinitions = definitions
    },
    $onAction: callback => { actionHooks.add(callback); return () => actionHooks.delete(callback) },
  }
  tools.addTools({ id: 'synthetic:computer', type: 'function',
    function: { name: 'computer_use', description: 'synthetic tool', parameters: { type: 'object', properties: { action: { type: 'string', enum: ['synthetic'] } }, required: ['action'], additionalProperties: false } },
    defaultActive: false, requiresExplicitSelection: true, icon: 'synthetic-icon',
    execute: async () => { nativeCalls += 1; return 'synthetic result' } })
  const ambient = { screenAmbientLightEnabled: true, screenAmbientLightSource: 'screen-capture' }
  const contexts = new Map([['synthetic-unrelated:writer', [{ contextId: 'unrelated', text: 'synthetic unrelated' }]]])
  const chatContext = { removeContextWriter: key => contexts.delete(key), getContextsSnapshot: () => Object.fromEntries(contexts),
    ingestContextMessage: message => contexts.set(message.source, [message]) }
  const stores = new Map([['tamagotchi-tool-selection', selection], ['llm-tools', tools], ['vision-processing', { stopTicker: () => { tickerStops += 1 } }], ['settings-screen-ambient-light', ambient], ['chat-context', chatContext]])
  const window = { airiOfflineScreen: bridge, addEventListener: () => {} }
  let click
  const document = { querySelector: () => ({ __vue_app__: { config: { globalProperties: { $pinia: { _s: stores } } } } }),
    addEventListener: (name, callback) => { if (name === 'click') click = callback }, removeEventListener: () => {} }
  const install = vm.runInNewContext(`(${source})`, { window, document, Set, WeakSet, Number, Error, setTimeout, console })
  return { install, selection, tools, ambient, contexts, click: () => click({ target: { closest: () => ({ disabled: false }) }, preventDefault: () => {}, stopImmediatePropagation: () => {} }), counts: () => ({ nativeCalls, tickerStops }) }
}

async function run() {
  await loadDefinitionProxyFactory()
  const schema = definitionProxyFactory({ id: 'synthetic:regression', type: 'function', function: { name: 'computer_use', parameters: { type: 'object', properties: { nested: { type: 'string' } } } } })
  assert.throws(() => productionDefinition({ ...schema }), error => error.name === 'DataCloneError')
  assert.doesNotThrow(() => productionDefinition(JSON.parse(JSON.stringify(schema))))
  const first = makeWindow(), second = makeWindow()
  await first.install(); await second.install()
  const registered = JSON.parse(JSON.stringify(first.tools.tools[0]))
  assert.equal(registered.id, 'synthetic:computer'); assert.equal(registered.type, 'function')
  assert.equal(registered.defaultActive, false); assert.equal(registered.requiresExplicitSelection, true)
  assert.equal(registered.icon, 'synthetic-icon'); assert.deepEqual(registered.function.parameters.required, ['action'])
  assert.equal(registered.function.parameters.properties.action.enum[0], 'synthetic'); assert.equal(Object.hasOwn(registered, 'execute'), false)
  assert.equal(first.selection.computerUseEnabled, false); assert.equal(second.selection.computerUseEnabled, false)
  assert.equal(first.ambient.screenAmbientLightEnabled, false)
  assert(first.contexts.has('local-offline-capabilities:screen-permission'))
  await assert.rejects(() => first.tools.getToolsByNames('computer_use')[0].execute({}), /屏幕感知已关闭/)
  assert.equal(first.counts().nativeCalls, 0)
  first.selection.computerUseEnabled = true; await tick()
  assert.equal(helper.enabled, false); assert.equal(setterCalls, 0); assert.equal(first.selection.computerUseEnabled, false)
  first.click(); await tick()
  assert.equal(helper.enabled, true); assert.equal(second.selection.computerUseEnabled, true); assert.equal(setterCalls, 1)
  assert(!first.contexts.has('local-offline-capabilities:screen-permission'))
  assert.equal(await first.tools.getToolsByNames('computer_use')[0].execute({}), 'synthetic result')
  second.click(); await tick()
  assert.equal(helper.enabled, false); assert.equal(first.selection.computerUseEnabled, false); assert.equal(setterCalls, 2)
  assert(first.contexts.has('local-offline-capabilities:screen-permission'))
  assert(first.contexts.has('synthetic-unrelated:writer'))
  await assert.rejects(() => first.tools.getToolsByNames('computer_use')[0].execute({}), /屏幕感知已关闭/)
  let futureCalls = 0
  first.tools.addTools(definitionProxyFactory({ id: 'synthetic:read-image', type: 'function', function: { name: 'computer_use_read_image', parameters: { type: 'object', properties: { image: { type: 'string' } } } }, execute: async () => { futureCalls += 1; return 'synthetic image' } }))
  await assert.rejects(() => first.tools.getToolsByNames('computer_use_read_image')[0].execute({}), /屏幕感知已关闭/)
  assert.equal(futureCalls, 0)
  await bridge.setEnabled(true)
  let resolveLate
  const late = new Promise(resolve => { resolveLate = resolve })
  first.tools.addTools({ id: 'synthetic:read-image', function: { name: 'computer_use_read_image' }, execute: async () => { await late; return 'must not escape' } })
  const pending = first.tools.getToolsByNames('computer_use_read_image')[0].execute({})
  await tick(); await bridge.setEnabled(false); resolveLate()
  await assert.rejects(() => pending, /工具结果已丢弃/)
  let releaseSetter
  setterGate = new Promise(resolve => { releaseSetter = resolve })
  first.click()
  first.click()
  releaseSetter(); await tick(); setterGate = undefined
  assert.equal(helper.enabled, false); assert.equal(first.selection.computerUseEnabled, false); assert.equal(second.selection.computerUseEnabled, false)
  assert(reports.some(status => status.capabilityStatusPresent && !status.computerUseEnabled))
  assert(reports.every(status => Object.values(status).every(value => typeof value === 'boolean')))
  const result = { test: 'unified-screen-bootstrap-with-production-structured-clone-and-proxy-definitions', passed: 15,
    checks: ['production structuredClone rejects legacy shallow-spread nested Proxy with DataCloneError', 'JSON definition clone allows production structuredClone without serializing execute', 'existing Proxy-backed tool retains nested schema, id, activation flags and icon', 'future Proxy-backed tool registration is serializable and guarded', 'helper-off initializes both UI windows off', 'off blocks existing computer tool executor', 'explicit UI-on enables helper and other window without feedback', 'explicit UI-off disables helper and other window', 'future tool executors are guarded', 'off discards late native tool result', 'off stops vision ticker and screen-capture ambient sampling', 'independent capability status appears off and is removed on without deleting unrelated context', 'rapid UI on/off before IPC replies preserves final off intent', 'renderer reports contain whitelisted booleans only', 'late replicated Pinia default cannot enable helper'],
    actualStructuredCloneVerified: true, nestedProxyRejectionVerified: true, actualVueProxyVerified,
    realAppRestarted: false, actualNativeToolRun: false, privateDataRead: false,
    limits: ['Store/IPC adapters use the production addTools structuredClone projection and real Proxy definitions; optional --assets also loads the installed Vue reactive implementation. Installed native-window behavior still needs app validation after restart.'] }
  fs.writeFileSync(path.join(__dirname, 'screen-controls-synthetic-result.json'), JSON.stringify(result, null, 2) + '\n')
  console.log(JSON.stringify(result))
}
run().catch(error => { console.error(error.stack); process.exitCode = 1 })
