import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { randomUUID } from 'node:crypto'

const here = path.dirname(fileURLToPath(import.meta.url))
const base = process.env.AIRI_COMPANIONS_ROOT || path.resolve(here, '..', '..', '..')
const userData = process.env.APP_USER_DATA_PATH || path.join(base, 'runtime', 'airi-data')
const sdkPath = process.env.AIRI_SERVER_SDK_PATH || path.join(base, 'airi', 'packages', 'server-sdk', 'dist', 'index.mjs')
const binding = `airi-offline-synthetic-verification-${randomUUID()}`
const expected = '离线语音测试通过'
const syntheticText = `这是本机离线自动验收消息，不要调用工具，不要描述屏幕。请只回复“${expected}”。`
const started = Date.now()
// The installed AIRI runtime currently has no registered chat-ingestion consumer.
// A structured module destination + broadcast reaches only AIRI's own peer and
// preserves an independent synthetic binding. Set consumer-group for diagnostics.
const deliveryMode = process.env.AIRI_TEST_DELIVERY === 'consumer-group' ? 'consumer-group' : 'broadcast'
const timeoutMs = Math.max(5000, Number(process.env.AIRI_TEST_TIMEOUT_MS) || 180000)
const speechHealth = process.env.AIRI_TEST_TTS_HEALTH || 'http://127.0.0.1:9942/health'
if (!/^http:\/\/127\.0\.0\.1:(9942|9945)\/health$/.test(speechHealth)) throw new Error('INVALID_TEST_TTS_HEALTH')
const result = {
  test: 'airi-sdk-synthetic-text-with-global-tts-observation',
  causalVoiceChainStatus: 'INCONCLUSIVE',
  ttsMetricsScope: 'Global counter only; not correlated to this synthetic binding',
  tokenTimingScope: 'message/complete are completed assistant events, not first-token timings',
  syntheticOnly: true,
  startedAt: new Date().toISOString(),
  inputSent: false,
  matchedAssistantEvents: 0,
  matchedCompleteEvents: 0,
  replyCharacters: 0,
  expectedPhraseObserved: false,
  connectionErrorCount: 0,
  ttsRequestDelta: 0,
  deliveryMode,
  serverErrorKinds: [],
  status: 'running',
}
let client

async function health(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(5000) })
  if (!response.ok) throw Object.assign(new Error('HEALTH_HTTP_ERROR'), { code: `HEALTH_HTTP_${response.status}` })
  return response.json()
}

function safeHelper(health) {
  return {
    rendererErrorCount: health.rendererDiagnostics?.errorCount ?? null,
    blockedAssetPaths: health.network?.blockedAssetPaths ?? [],
    redirectedVadRequests: health.network?.redirectedVadRequests ?? null,
    redirectedBundledAssetRequests: health.network?.redirectedBundledAssetRequests ?? null,
    servedAssetRequests: health.network?.servedAssetRequests ?? null,
    screenFailureCount: health.screen?.failureCount ?? null,
  }
}

function belongsToTest(payload) {
  return payload?.overrides?.binding === binding
    || payload?.['gen-ai:chat']?.input?.data?.overrides?.binding === binding
}

function observeReply(payload) {
  // Only this synthetic binding is inspected. No event payload or reply text is saved or printed.
  if (!belongsToTest(payload)) return false
  const content = payload.message?.content
  const text = typeof content === 'string' ? content
    : Array.isArray(content) ? content.filter(part => part.type === 'text').map(part => part.text || '').join('') : ''
  result.replyCharacters = Math.max(result.replyCharacters, text.length)
  result.expectedPhraseObserved ||= text.includes(expected)
  return true
}

try {
  const beforeSpeech = await health(speechHealth)
  result.before = { ttsRequests: beforeSpeech.metrics?.tts_requests ?? null, helper: safeHelper(await health('http://127.0.0.1:9943/health')) }
  const config = JSON.parse((await fs.readFile(path.join(userData, 'server-channel-config.json'), 'utf8')).replace(/^\uFEFF/, ''))
  const { Client } = await import(pathToFileURL(sdkPath).href)
  const extension = { id: 'local-offline-verification' }
  client = new Client({
    name: 'local-offline-verification',
    url: `ws://127.0.0.1:${Number(process.env.SERVER_CHANNEL_PORT || 6121)}/ws`,
    token: config.authToken,
    extension,
    identity: { id: `synthetic-${randomUUID()}`, extension },
    possibleEvents: ['output:gen-ai:chat:message', 'output:gen-ai:chat:complete', 'error'],
    autoConnect: false,
    autoReconnect: false,
    onError: () => { result.connectionErrorCount += 1 },
  })
  client.onEvent('output:gen-ai:chat:message', (event) => {
    if (observeReply(event.data)) result.matchedAssistantEvents += 1
  })
  client.onEvent('output:gen-ai:chat:complete', (event) => {
    if (observeReply(event.data)) result.matchedCompleteEvents += 1
  })
  client.onEvent('error', (event) => {
    const message = String(event.data?.message || '')
    const kind = /no consumer registered/i.test(message) ? 'no-consumer-registered'
      : /auth|token/i.test(message) ? 'authentication-error' : 'other-protocol-error'
    if (!result.serverErrorKinds.includes(kind)) result.serverErrorKinds.push(kind)
  })
  await client.connect({ timeout: 15000 })
  client.sendOrThrow({
    type: 'input:text',
    data: { text: syntheticText, overrides: { binding } },
    route: {
      // Structured module targeting preserves ':' inside AIRI's module name.
      destinations: [{ type: 'module', modules: ['proj-airi:stage-tamagotchi'] }],
      delivery: deliveryMode === 'broadcast' ? { mode: 'broadcast' }
        : { mode: 'consumer-group', group: 'chat-ingestion', selection: 'first', required: true },
    },
  })
  result.inputSent = true
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 1500))
    const speech = await health(speechHealth)
    result.ttsRequestDelta = (speech.metrics?.tts_requests ?? 0) - (result.before.ttsRequests ?? 0)
    if (result.serverErrorKinds.includes('no-consumer-registered')) break
    if (result.matchedCompleteEvents > 0 && result.replyCharacters > 0) break
  }
  result.after = { helper: safeHelper(await health('http://127.0.0.1:9943/health')), ttsRequests: (await health(speechHealth)).metrics?.tts_requests ?? null }
  result.status = result.matchedCompleteEvents > 0 && result.replyCharacters > 0 ? 'text-reply-observed'
    : result.serverErrorKinds.includes('no-consumer-registered') ? 'no-chat-consumer' : 'timeout-or-incomplete'
} catch (error) {
  result.status = 'error'
  const code = String(error?.code || error?.name || 'ERROR')
  result.errorCode = /^[A-Za-z0-9_.-]{1,90}$/.test(code) ? code : 'ERROR'
} finally {
  client?.close()
  result.elapsedMs = Date.now() - started
  result.finishedAt = new Date().toISOString()
  const output = path.join(here, `result-${result.finishedAt.replace(/[:.]/g, '-')}.json`)
  await fs.writeFile(output, JSON.stringify(result, null, 2), 'utf8')
  console.log(JSON.stringify({ ...result, reportPath: output }, null, 2))
  process.exit(result.status === 'text-reply-observed' ? 0 : 1)
}
