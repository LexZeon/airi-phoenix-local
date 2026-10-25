import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { randomUUID } from 'node:crypto'
import assert from 'node:assert/strict'

const here = path.dirname(fileURLToPath(import.meta.url))
const base = process.env.AIRI_COMPANIONS_ROOT || path.resolve(here, '..', '..', '..')
const userData = process.env.APP_USER_DATA_PATH || path.join(base, 'runtime', 'airi-data')
const { Client, ContextUpdateStrategy } = await import(pathToFileURL(path.join(base, 'airi', 'packages', 'server-sdk', 'dist', 'index.mjs')))
const { createContextRegistry } = await import(pathToFileURL(path.join(base, 'airi', 'packages', 'core-agent', 'dist', 'index.mjs')))
const channel = JSON.parse((await fs.readFile(path.join(userData, 'server-channel-config.json'), 'utf8')).replace(/^\uFEFF/, ''))
if (!channel.authToken) throw new Error('LOCAL_CHANNEL_TOKEN_NOT_READY')

const nonce = randomUUID()
const observerName = `screen-stop-observer-${nonce}`
const sourceName = `screen-stop-source-${nonce}`
const identity = { id: 'synthetic-source', extension: { id: sourceName } }
const writer = `${sourceName}:${identity.id}`
const registry = createContextRegistry()
let updateObserved = false
let leaveObserved = false
let resolveUpdate, resolveLeave
const update = new Promise(resolve => { resolveUpdate = resolve })
const leave = new Promise(resolve => { resolveLeave = resolve })
const waitFor = (event, label) => Promise.race([event, new Promise((_, reject) => setTimeout(() => reject(new Error(`${label}_TIMEOUT`)), 5000))])
const observer = new Client({ name: observerName, token: channel.authToken, url: 'ws://127.0.0.1:6121/ws', autoConnect: false, autoReconnect: false })
const publisher = new Client({ name: sourceName, token: channel.authToken, url: 'ws://127.0.0.1:6121/ws', identity, extension: identity.extension,
  possibleEvents: ['context:update'], autoConnect: false, autoReconnect: false })
observer.onEvent('context:update', event => {
  if (event.metadata?.source?.id !== identity.id || event.metadata?.source?.extension?.id !== sourceName) return
  registry.ingest({ ...event.data, metadata: event.metadata, createdAt: Date.now() })
  updateObserved = true
  resolveUpdate()
})
observer.onEvent('extension:module:de-announced', event => {
  if (event.data.identity?.id !== identity.id || event.data.identity?.extension?.id !== sourceName) return
  // AIRI's compiled native context bridge applies this same lifecycle action.
  registry.removeWriter(writer)
  leaveObserved = true
  resolveLeave()
})

try {
  await observer.connect({ timeout: 5000 })
  await publisher.connect({ timeout: 5000 })
  publisher.sendOrThrow({ type: 'context:update', data: { id: randomUUID(), contextId: 'synthetic-screen-stop-test', strategy: ContextUpdateStrategy.ReplaceSelf, text: 'Synthetic lifecycle-only observation.' },
    // Do not send this synthetic context to AIRI or alter its real context buckets.
    route: { destinations: [{ type: 'module', modules: [observerName] }], delivery: { mode: 'broadcast' } } })
  await waitFor(update, 'SYNTHETIC_CONTEXT')
  assert(Object.hasOwn(registry.snapshot(), writer))
  publisher.close()
  await waitFor(leave, 'SYNTHETIC_DEANNOUNCEMENT')
  assert(!Object.hasOwn(registry.snapshot(), writer))

  registry.ingest({ id: 'empty-replace', contextId: 'empty-replace', strategy: ContextUpdateStrategy.ReplaceSelf, text: '', createdAt: Date.now(), source: 'synthetic-empty-writer' })
  const emptyReplaceLeavesEntry = registry.snapshot()['synthetic-empty-writer']?.length === 1
  assert(emptyReplaceLeavesEntry)
  const result = { test: 'real-local-sdk-deannouncement-and-compiled-registry-semantics', updateObserved, leaveObserved,
    writerRemovedAfterLeave: !Object.hasOwn(registry.snapshot(), writer), emptyReplaceLeavesEntry,
    syntheticContextRoutedOnlyToTestObserver: true, privateEventsRead: false, nativeAppContextInspected: false,
    limits: ['Tests the live channel and installed core registry; native AIRI screen-stop UI state is a separate app test after installing the new shell.'] }
  await fs.writeFile(path.join(here, 'screen-stop-protocol-result.json'), JSON.stringify(result, null, 2) + '\n')
  console.log(JSON.stringify(result))
} finally {
  publisher.close()
  observer.close()
}
