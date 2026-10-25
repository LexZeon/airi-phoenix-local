'use strict'

// Execute the production lifecycle functions with synthetic capture/HTTP/renderer adapters.
// This never captures the desktop, runs a model, reads private chat, or restarts AIRI.
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const { randomUUID } = require('node:crypto')
const { fileURLToPath, pathToFileURL } = require('node:url')
const main = path.resolve(__dirname, '..', 'main.cjs')
const source = fs.readFileSync(main, 'utf8')
const start = source.indexOf('async function connectContext(')
const end = source.indexOf('function showAiri(', start)
assert(start > 0 && end > start)
const lifecycle = source.slice(start, end)
const writer = 'local-offline-vision:screen-observer'
const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}
const tick = () => new Promise(resolve => setImmediate(resolve))

function harness(options = {}) {
  const entries = new Map([[writer, ['synthetic old observation']], ['synthetic-unrelated:writer', ['unrelated observation']]])
  const calls = { thumbnails: 0, fetches: 0, publishes: 0, closes: 0, signals: [], clientStates: [] }
  const store = {
    removeContextWriter: key => entries.delete(key),
    getContextsSnapshot: () => Object.fromEntries(entries),
  }
  const rendererEntry = path.resolve('synthetic-airi', 'index.html')
  const document = { querySelector: () => ({ __vue_app__: { config: { globalProperties: { $pinia: { _s: new Map([['chat-context', store]]) } } } } }) }
  const screenState = { enabled: options.enabled !== false, capturing: false, publishedCount: 0, failureCount: 0, skippedCount: 0, contextClearStatus: 'not-needed', clearedWriterCount: 0 }
  class Client {
    constructor(config) { this.config = config }
    async connect() { if (options.connectGate) await options.connectGate.promise }
    sendOrThrow(event) { assert.equal(event.type, 'context:update'); calls.publishes += 1 }
    close() { calls.closes += 1 }
  }
  const context = vm.createContext({
    state: { screen: screenState }, captureEpoch: 0, activeRequest: undefined, contextClient: undefined, CHANNEL: 'synthetic-airi-offline',
    contextStopPromise: Promise.resolve(), quitting: false, sdk: { Client, ContextUpdateStrategy: { ReplaceSelf: 'replace-self' } },
    preset: { screen: { baseUrl: 'http://127.0.0.1:9941/v1/', model: 'synthetic', maxTokens: 400, timeoutMs: 1000 } },
    base: path.resolve('synthetic-airi'), userData: path.resolve('synthetic-profile'), rendererEntry,
    fs: { readFileSync: () => JSON.stringify({ authToken: 'synthetic-non-secret-test-token' }) },
    process: { env: {} }, path, pathToFileURL, fileURLToPath, URL, Buffer, AbortController, AbortSignal, randomUUID,
    screen: { getPrimaryDisplay: () => ({ id: 1 }) },
    BrowserWindow: { getAllWindows: () => [{ isDestroyed: () => false, webContents: {
      isDestroyed: () => false, getURL: () => pathToFileURL(rendererEntry).href, send: () => {},
      executeJavaScript: async script => { if (options.clearGate) await options.clearGate.promise; return vm.runInNewContext(script, { document, Object }) },
    } }] },
    desktopCapturer: { getSources: async () => {
      calls.thumbnails += 1
      if (options.thumbnailGate) await options.thumbnailGate.promise
      return [{ display_id: '1', thumbnail: { isEmpty: () => false, toJPEG: () => Buffer.from('synthetic-image') } }]
    } },
    fetch: async (_url, request) => {
      calls.fetches += 1; calls.signals.push(request.signal)
      // Deliberately permit a late response after abort to exercise the epoch guard.
      if (options.fetchGate) await options.fetchGate.promise
      return { ok: true, json: async () => ({ choices: [{ message: { content: 'Synthetic observation.' } }] }) }
    },
    requireLocalURL: () => {}, refreshTray: () => {}, wait: tick,
    errorCode: error => error.code || error.name || 'ERROR', event: () => {}, console,
  })
  vm.runInContext(lifecycle, context)
  return { context, entries, calls, screenState }
}

async function run() {
  const checks = []
  {
    const h = harness({ enabled: false })
    await h.context.captureAndPublish()
    assert.equal(h.calls.thumbnails, 0); assert.equal(h.calls.fetches, 0)
    checks.push('disabled: no thumbnail or inference')
  }
  {
    const gate = deferred(); const h = harness({ thumbnailGate: gate })
    const cycle = h.context.captureAndPublish(); await tick()
    assert.equal(h.calls.thumbnails, 1)
    await h.context.setCaptureEnabled(false); gate.resolve(); await cycle
    assert.equal(h.calls.fetches, 0); assert.equal(h.calls.publishes, 0)
    assert(!h.entries.has(writer)); assert(h.entries.has('synthetic-unrelated:writer'))
    checks.push('off during thumbnail: no subsequent inference; only own writer removed')
  }
  {
    const gate = deferred(); const h = harness({ fetchGate: gate })
    const cycle = h.context.captureAndPublish(); await tick()
    assert.equal(h.calls.fetches, 1)
    await h.context.setCaptureEnabled(false)
    assert(h.calls.signals[0].aborted)
    gate.resolve(); await cycle
    assert.equal(h.calls.publishes, 0); assert.equal(h.screenState.failureCount, 0)
    assert(!h.entries.has(writer))
    checks.push('off during HTTP: request aborted; ignored-abort late response cannot publish')
  }
  {
    const gate = deferred(); const h = harness({ connectGate: gate })
    const cycle = h.context.captureAndPublish(); await tick()
    await h.context.setCaptureEnabled(false); gate.resolve(); await cycle
    assert.equal(h.calls.thumbnails, 0); assert.equal(h.calls.fetches, 0); assert.equal(h.calls.publishes, 0)
    checks.push('off during SDK connect: no thumbnail/inference/publish afterwards')
  }
  {
    const gate = deferred(); const h = harness({ clearGate: gate })
    const off = h.context.setCaptureEnabled(false)
    const on = h.context.setCaptureEnabled(true)
    await tick(); assert.equal(h.calls.thumbnails, 0)
    gate.resolve(); await off; await on; await tick()
    assert.equal(h.calls.publishes, 1); assert.equal(h.screenState.contextClearStatus, 'cleared')
    checks.push('rapid off/on: old-context clear completes before a new publication')
  }
  const result = { test: 'screen-stop-production-functions-with-synthetic-adapters', passed: checks.length, checks,
    realDesktopCaptured: false, inferenceRun: false, appRestarted: false,
    limits: ['Synthetic adapters validate lifecycle/races; real native-window context state requires the installed shell after restart.'] }
  fs.writeFileSync(path.join(__dirname, 'screen-stop-synthetic-result.json'), JSON.stringify(result, null, 2) + '\n')
  console.log(JSON.stringify(result))
}
run().catch(error => { console.error(error.stack); process.exitCode = 1 })
