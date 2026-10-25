// Synthetic SDK text observation through AIRI. Run only after explicitly selecting the online provider.
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { randomUUID } from 'node:crypto'

const here = path.dirname(fileURLToPath(import.meta.url))
const base = process.env.AIRI_COMPANIONS_ROOT || path.resolve(here, '..', '..', '..')
const userData = process.env.APP_USER_DATA_PATH || path.join(base, 'runtime', 'airi-data')
const sdkPath = process.env.AIRI_SERVER_SDK_PATH || path.join(base, 'airi', 'packages', 'server-sdk', 'dist', 'index.mjs')
const channelPort = Number(process.env.SERVER_CHANNEL_PORT || 6121)
const gatewayUrl = 'http://127.0.0.1:9948/health'
const expected = 'AIRI 在线文字连接正常'
const syntheticText = `这是独立的合成文字连通测试，不要调用工具，不要描述屏幕。只回复${expected}`
const binding = `airi-online-text-verification-${randomUUID()}`
const started = Date.now()
const deadline = started + 90000
const abort = new AbortController()
let client
let timeout
let resolveDone
let settled = false
const done = new Promise(resolve => { resolveDone = resolve })
const finish = reason => { if (!settled) { settled = true; resolveDone(reason) } }
const counters = ['requests', 'completed', 'failed', 'cancelled', 'busy_rejections']
const result = {
  test: 'airi-online-provider-sdk-synthetic-text-observation',
  scope: 'Independent SDK scene binding through AIRI provider compatibility; no microphone, speech, screen or host playback test.',
  syntheticOnly: true,
  startedAt: new Date(started).toISOString(),
  timeoutLimitMs: 90000,
  inputSent: false,
  matchedAssistantEvents: 0,
  matchedCompleteEvents: 0,
  replyCharacters: 0,
  expectedPhraseObserved: false,
  connectionErrorCount: 0,
  tokenFirstByteMeasured: false,
  physicalAudioMeasured: false,
  gatewayCounterAttribution: 'Global counter deltas are concurrent observations, not request-correlated causal proof.',
  rawReplyIdsTokensOrPrivateEventsRetained: false,
  status: 'running',
}

function own(payload) {
  return payload?.overrides?.binding === binding
    || payload?.['gen-ai:chat']?.input?.data?.overrides?.binding === binding
}
function observe(payload) {
  if (!own(payload)) return false
  const content = payload.message?.content
  const text = typeof content === 'string' ? content
    : Array.isArray(content) ? content.filter(part => part.type === 'text').map(part => part.text || '').join('') : ''
  result.replyCharacters = Math.max(result.replyCharacters, text.length)
  result.expectedPhraseObserved ||= text.includes(expected)
  return true
}
async function health() {
  const remaining = deadline - Date.now()
  if (remaining <= 0) throw Object.assign(new Error('TIMEOUT'), { code: 'TEST_TIMEOUT' })
  const response = await fetch(gatewayUrl, {
    redirect: 'error',
    signal: AbortSignal.any([abort.signal, AbortSignal.timeout(Math.min(5000, remaining))]),
  })
  if (!response.ok) throw Object.assign(new Error('GATEWAY_HEALTH_HTTP'), { code: `HEALTH_HTTP_${response.status}` })
  const value = await response.json()
  if (value.service !== 'airi-codex-chat' || value.ready !== true) throw Object.assign(new Error('GATEWAY_NOT_READY'), { code: 'GATEWAY_NOT_READY' })
  return { ready: true, metrics: Object.fromEntries(counters.map(key => [key, Number.isFinite(value.metrics?.[key]) ? value.metrics[key] : null])) }
}

try {
  if (!Number.isInteger(channelPort) || channelPort < 1 || channelPort > 65535) throw Object.assign(new Error('INVALID_CHANNEL_PORT'), { code: 'INVALID_CHANNEL_PORT' })
  timeout = setTimeout(() => { abort.abort(); finish('timeout') }, Math.max(1, deadline - Date.now()))
  result.before = await health()
  const channel = JSON.parse((await fs.readFile(path.join(userData, 'server-channel-config.json'), 'utf8')).replace(/^\uFEFF/, ''))
  if (typeof channel.authToken !== 'string' || !channel.authToken) throw Object.assign(new Error('LOCAL_CHANNEL_NOT_READY'), { code: 'LOCAL_CHANNEL_NOT_READY' })
  const { Client } = await import(pathToFileURL(sdkPath).href)
  const extension = { id: 'local-online-text-verification' }
  client = new Client({
    name: 'local-online-text-verification',
    url: `ws://127.0.0.1:${channelPort}/ws`,
    token: channel.authToken,
    extension,
    identity: { id: `synthetic-${randomUUID()}`, extension },
    possibleEvents: ['output:gen-ai:chat:message', 'output:gen-ai:chat:complete'],
    autoConnect: false,
    autoReconnect: false,
    onError: () => { result.connectionErrorCount += 1 },
  })
  client.onEvent('output:gen-ai:chat:message', event => {
    if (!observe(event.data)) return
    result.matchedAssistantEvents += 1
    if (result.matchedCompleteEvents > 0 && result.replyCharacters > 0) finish('complete')
  })
  client.onEvent('output:gen-ai:chat:complete', event => {
    if (!observe(event.data)) return
    result.matchedCompleteEvents += 1
    if (result.replyCharacters > 0) finish('complete')
  })
  await client.connect({ timeout: Math.max(1, Math.min(15000, deadline - Date.now())) })
  if (abort.signal.aborted || Date.now() >= deadline) throw Object.assign(new Error('TIMEOUT'), { code: 'TEST_TIMEOUT' })
  client.sendOrThrow({
    type: 'input:text',
    data: { text: syntheticText, overrides: { binding } },
    route: { destinations: [{ type: 'module', modules: ['proj-airi:stage-tamagotchi'] }], delivery: { mode: 'broadcast' } },
  })
  result.inputSent = true
  const reason = await done
  if (reason !== 'complete') result.status = 'timeout-or-incomplete'
  else {
    result.after = await health()
    result.gatewayMetricDelta = Object.fromEntries(counters.map(key => [key,
      result.before.metrics[key] === null || result.after.metrics[key] === null ? null : result.after.metrics[key] - result.before.metrics[key],
    ]))
    result.gatewayCompletionObserved = (result.gatewayMetricDelta.completed ?? 0) > 0
    result.status = result.matchedCompleteEvents > 0 && result.replyCharacters > 0 && result.expectedPhraseObserved
      ? result.gatewayCompletionObserved ? 'online-text-observation-pass' : 'text-pass-without-gateway-completion-observation'
      : 'unexpected-synthetic-reply'
  }
} catch (error) {
  result.status = abort.signal.aborted ? 'timeout-or-incomplete' : 'error'
  const code = String(error?.code || error?.name || 'ERROR')
  result.errorCode = /^[A-Za-z0-9_.-]{1,90}$/.test(code) ? code : 'ERROR'
} finally {
  clearTimeout(timeout)
  abort.abort()
  try { client?.close() } catch { result.connectionErrorCount += 1 }
  result.elapsedMs = Date.now() - started
  result.finishedAt = new Date().toISOString()
  const output = path.join(here, `result-online-chat-sdk-${result.finishedAt.replace(/[:.]/g, '-')}.json`)
  try { await fs.writeFile(output, JSON.stringify(result, null, 2) + '\n', 'utf8') } catch { result.reportWriteFailed = true }
  await new Promise(resolve => process.stdout.write(JSON.stringify(result) + '\n', resolve))
  process.exit(result.status === 'online-text-observation-pass' && !result.reportWriteFailed ? 0 : 1)
}
