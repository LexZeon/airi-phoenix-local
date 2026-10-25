async function installOfflineScreenControls() {
  if (window.__airiOfflineScreenControls) return { ok: true, reused: true }
  const bridge = window.airiOfflineScreen
  if (!bridge?.getState || !bridge?.setEnabled || !bridge?.onState) throw new Error('SCREEN_CONTROL_BRIDGE_NOT_READY')
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms))
  let pinia, selection, tools
  for (let attempt = 0; attempt < 240; attempt += 1) {
    pinia = document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$pinia
    selection = pinia?._s?.get('tamagotchi-tool-selection')
    tools = pinia?._s?.get('llm-tools')
    if (selection?.$subscribe && tools?.getToolsByNames && tools?.addTools && tools?.$onAction) break
    await wait(250)
  }
  if (!selection?.$subscribe || !tools?.$onAction) throw new Error('SCREEN_CONTROL_STORES_NOT_READY')

  let applying = false
  let latest = { enabled: false, epoch: -1 }
  let pendingValue
  let capabilityState
  const capabilityWriter = 'local-offline-capabilities:screen-permission'
  const guarded = new WeakSet()
  const names = new Set(['computer_use', 'computer_use_read_image'])
  function apply(value) {
    if (!value || typeof value.enabled !== 'boolean' || !Number.isInteger(value.epoch) || value.epoch < latest.epoch) return
    latest = value
    applying = true
    try {
      selection.computerUseEnabled = value.enabled
      const context = pinia._s.get('chat-context')
      if (context?.removeContextWriter && context?.ingestContextMessage && capabilityState !== value.enabled) {
        context.removeContextWriter(capabilityWriter)
        if (!value.enabled) context.ingestContextMessage({
          id: 'screen-permission', contextId: 'capability:screen-access', strategy: 'replace-self',
          source: capabilityWriter, createdAt: Date.now(),
          text: '屏幕观察和电脑控制已关闭。旧记录不是当前界面，不得声称现在看见用户屏幕，也不得自动截图或控制电脑。只有用户手动打开屏幕开关后，才可恢复这些能力。',
        })
        capabilityState = value.enabled
      }
      if (!value.enabled) {
        // A manually opened vision-debug ticker must not outlive the unified off switch.
        pinia._s.get('vision-processing')?.stopTicker?.()
        const ambient = pinia._s.get('settings-screen-ambient-light')
        if (ambient?.screenAmbientLightSource === 'screen-capture') ambient.screenAmbientLightEnabled = false
      }
      const snapshot = context?.getContextsSnapshot?.()
      bridge.reportState?.({
        computerUseEnabled: selection.computerUseEnabled === true,
        capabilityStatusPresent: Boolean(snapshot && Object.hasOwn(snapshot, capabilityWriter)),
        screenWriterPresent: Boolean(snapshot && Object.hasOwn(snapshot, 'local-offline-vision:screen-observer')),
        visionTickerRunning: pinia._s.get('vision-processing')?.isRunning === true,
      })
    } finally { applying = false }
  }
  function guardExecute(execute) {
    if (typeof execute !== 'function' || guarded.has(execute)) return execute
    const wrapped = async (...args) => {
      const before = await bridge.getState()
      if (!before.enabled) throw new Error('屏幕感知已关闭，请先打开聊天框中的屏幕开关。')
      const result = await execute(...args)
      const after = await bridge.getState()
      if (!after.enabled || before.epoch !== after.epoch) throw new Error('屏幕权限已改变，本次工具结果已丢弃。')
      return result
    }
    guarded.add(wrapped)
    return wrapped
  }
  function guardedTool(tool, execute = tool.execute) {
    // Pinia exposes reactive definitions, including nested function/JSON-schema
    // objects. addTools structured-clones these exact fields; a shallow spread
    // retains their Proxy objects and throws DataCloneError. Definitions are
    // JSON data, while the local executor must remain outside that data clone.
    const definition = JSON.parse(JSON.stringify({
      id: tool.id,
      type: tool.type,
      function: tool.function,
      ...(tool.defaultActive === undefined ? {} : { defaultActive: tool.defaultActive }),
      ...(tool.requiresExplicitSelection === undefined ? {} : { requiresExplicitSelection: tool.requiresExplicitSelection }),
      ...(tool.icon === undefined ? {} : { icon: tool.icon }),
    }))
    return { ...definition, execute: guardExecute(execute) }
  }

  apply(await bridge.getState())
  const stopState = bridge.onState(apply)
  const stopSelection = selection.$subscribe(() => {
    // Replicated Pinia state is not a grant of permission. In particular, a late startup default must not enable capture.
    if (!applying && selection.computerUseEnabled !== latest.enabled) apply(latest)
  }, { detached: true, flush: 'sync' })
  function requestEnabled(desired) {
    if (desired === pendingValue || (pendingValue === undefined && desired === latest.enabled)) return
    pendingValue = desired
    applying = true
    try { selection.computerUseEnabled = desired } finally { applying = false }
    void bridge.setEnabled(desired).then(apply).catch(async () => {
      try { apply(await bridge.getState()) } catch { apply({ enabled: false, epoch: latest.epoch }) }
    }).finally(() => {
      if (pendingValue === desired) pendingValue = undefined
    })
  }
  const clickScreenToggle = event => {
    const button = event.target?.closest?.('[data-testid="computer-use-toggle"]')
    if (!button || button.disabled) return
    event.preventDefault()
    event.stopImmediatePropagation()
    requestEnabled(!(pendingValue === undefined ? latest.enabled : pendingValue))
  }
  document.addEventListener('click', clickScreenToggle, true)

  // Guard both registered and future executors. A queued tool call must re-check the main-process switch.
  const stopTools = tools.$onAction(({ name, args }) => {
    if (name !== 'addTools') return
    for (let index = 0; index < args.length; index += 1) {
      const tool = args[index]
      if (names.has(tool?.function?.name)) args[index] = guardedTool(tool)
    }
  }, true)
  for (const definition of [...tools.tools]) {
    if (!names.has(definition.function?.name)) continue
    const executable = tools.getToolsByNames(definition.function.name)[0]
    if (executable?.execute) tools.addTools(guardedTool(definition, executable.execute))
  }
  const close = () => { stopState(); stopSelection(); stopTools(); document.removeEventListener('click', clickScreenToggle, true); delete window.__airiOfflineScreenControls }
  window.addEventListener('pagehide', close, { once: true })
  window.__airiOfflineScreenControls = { close, getState: () => ({ enabled: latest.enabled, epoch: latest.epoch }) }
  return { ok: true, reused: false, enabled: latest.enabled, guardedToolNames: [...names] }
}
