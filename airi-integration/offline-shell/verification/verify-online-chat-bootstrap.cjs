'use strict'
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const hooks = new Set()
// The actual llm store returns models/stream only. There is deliberately no compatibility Map.
const llm = {
  models: async () => [],
  stream(...args) { for (const hook of hooks) hook({ name: 'stream', args }); return args[3] },
  $onAction(callback) { hooks.add(callback); return () => hooks.delete(callback) },
}
const window = { addEventListener() {} }
const document = { querySelector: () => ({ __vue_app__: { config: { globalProperties: { $pinia: { _s: new Map([['llm', llm]]) } } } } }) }
const provider = (baseURL, protocol = 'chat-completions') => ({ generation: () => ({ protocol, config: { baseURL } }) })
const source = fs.readFileSync(path.join(__dirname, '..', 'online-chat-bootstrap.js'), 'utf8')
const install = vm.runInNewContext(`(${source})`, { window, document, setTimeout, URL, Array, String, Error })
;(async () => {
  assert((await install()).actionHookInstalled)
  assert.equal(hooks.size, 1)
  const resolver = () => 'kept'
  const selected = llm.stream('chatgpt-codex-text', provider('http://127.0.0.1:9948/v1/'), {}, { maxTokens: 123, supportsTools: true, tools: ['old'], taskTools: ['old'], resolveStep: resolver })
  assert.equal(selected.supportsTools, false); assert.equal(selected.tools.length, 0); assert.equal(selected.taskTools.length, 0)
  assert.equal(selected.maxTokens, 123); assert.equal(selected.resolveStep, resolver)
  const offlineOptions = { tools: ['preserved'], supportsTools: true }
  assert.equal(llm.stream('airi-qwen3.5-9b', provider('http://127.0.0.1:9941/v1/'), {}, offlineOptions), offlineOptions)
  assert.equal(llm.stream('chatgpt-codex-text', provider('http://127.0.0.1:9999/v1/'), {}, offlineOptions), offlineOptions)
  assert.equal(llm.stream('chatgpt-codex-text', provider('http://127.0.0.1:9948/v1/', 'responses'), {}, offlineOptions), offlineOptions)
  assert.equal(llm.stream('chatgpt-codex-text', provider('http://localhost:9948/v1'), {}).supportsTools, false)
  assert((await install()).reused); assert.equal(hooks.size, 1)
  const result = { test: 'online-chat-public-llm-action-hook-no-private-map', passed: 7,
    checks: ['actual public store shape without Maps installs', 'exact online model disables tool resolution', 'unrelated options preserved', 'offline9B unchanged', 'unrelated endpoint unchanged', 'other protocol unchanged', 'missing options and reuse supported'],
    actualAiriRequestTested: false }
  fs.writeFileSync(path.join(__dirname, 'online-chat-bootstrap-result.json'), JSON.stringify(result, null, 2) + '\n')
  console.log(JSON.stringify(result))
})().catch(error => { console.error(error.stack); process.exitCode = 1 })
