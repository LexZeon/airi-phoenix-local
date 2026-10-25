async function installOnlineChatCompatibility() {
  if (window.__airiOnlineChatCompatibility) return { ok: true, reused: true, actionHookInstalled: true }
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms))
  let llm
  for (let attempt = 0; attempt < 240; attempt += 1) {
    const pinia = document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$pinia
    llm = pinia?._s?.get('llm')
    if (typeof llm?.stream === 'function' && typeof llm?.$onAction === 'function') break
    await wait(250)
  }
  if (typeof llm?.stream !== 'function' || typeof llm?.$onAction !== 'function') throw new Error('ONLINE_CHAT_COMPATIBILITY_NOT_READY')
  let guardedCalls = 0
  const close = llm.$onAction(({ name, args }) => {
    if (name !== 'stream' || args[0] !== 'chatgpt-codex-text' || typeof args[1]?.generation !== 'function') return
    let request, url
    try { request = args[1].generation(args[0]); url = new URL(String(request?.config?.baseURL)) } catch { return }
    if (request?.protocol !== 'chat-completions' || url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || url.port !== '9948' || !['/v1', '/v1/'].includes(url.pathname)) return
    const options = args[3] && typeof args[3] === 'object' && !Array.isArray(args[3]) ? args[3] : {}
    // llm's compatibility Maps are private. Its public stream options are applied before tool resolution.
    args[3] = { ...options, supportsTools: false, taskTools: [], tools: [] }
    guardedCalls += 1
  }, true)
  window.__airiOnlineChatCompatibility = { close, guardedCalls: () => guardedCalls }
  window.addEventListener('pagehide', () => { close(); delete window.__airiOnlineChatCompatibility }, { once: true })
  return { ok: true, reused: false, model: 'chatgpt-codex-text', toolExecutionRequested: false, actionHookInstalled: true }
}
