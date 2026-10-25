async function bootstrapManagedCharacter(config) {
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms))
  const marker = 'airi-offline/managed-characters'
  let cardStore, displayStore
  for (let attempt = 0; attempt < 240; attempt += 1) {
    const app = document.querySelector('#app')?.__vue_app__
    const pinia = app?.config?.globalProperties?.$pinia
    cardStore = pinia?._s?.get('airi-card')
    displayStore = pinia?._s?.get('display-models')
    if (cardStore?.ready && displayStore) break
    await wait(250)
  }
  if (!cardStore?.ready || !displayStore) throw new Error('CHARACTER_STORES_NOT_READY')
  let managed = {}
  try { managed = JSON.parse(localStorage.getItem(marker) || '{}') } catch { throw new Error('INVALID_MANAGED_CHARACTER_STATE') }
  let record = managed[config.id]
  let imported = false
  async function importModel() {
    const response = await fetch(config.modelUrl || `${config.baseUrl}/character/model.zip`)
    if (!response.ok) throw new Error('CHARACTER_MODEL_UNAVAILABLE')
    const file = new File([await response.arrayBuffer()], config.modelName, { type: 'application/zip' })
    const model = await displayStore.addDisplayModel('live2d-zip', file)
    if (!model?.id) throw new Error('CHARACTER_MODEL_IMPORT_FAILED')
    return model
  }
  if (!record || !cardStore.cards.has(record.cardId)) {
    const model = await importModel()
    const cardId = await cardStore.addCard(config.card, 'import', model.id)
    if (!cardId || !cardStore.cards.has(cardId)) throw new Error('CHARACTER_CARD_IMPORT_FAILED')
    record = { cardId, displayModelId: model.id, modelRevision: config.modelRevision, importedAt: new Date().toISOString() }
    managed[config.id] = record
    localStorage.setItem(marker, JSON.stringify(managed))
    imported = true
  } else if (record.modelRevision !== config.modelRevision) {
    const model = await importModel()
    // Replace only the managed character's default model, retaining persona/user edits.
    if (!await cardStore.updateCard(record.cardId, {}, model.id)) throw new Error('CHARACTER_MODEL_UPDATE_FAILED')
    record = { ...record, displayModelId: model.id, modelRevision: config.modelRevision }
    managed[config.id] = record
    localStorage.setItem(marker, JSON.stringify(managed))
    imported = true
  }
  const model = await displayStore.getDisplayModel(record.displayModelId)
  if (!model) throw new Error('MANAGED_CHARACTER_MODEL_MISSING')
  if (config.nameRevision && record.nameRevision !== config.nameRevision) {
    if (!await cardStore.updateCard(record.cardId, { name: config.card.name })) throw new Error('CHARACTER_NAME_UPDATE_FAILED')
    record = { ...record, nameRevision: config.nameRevision }
    managed[config.id] = record
    localStorage.setItem(marker, JSON.stringify(managed))
  }
  if (config.selectionRevision && record.selectionRevision !== config.selectionRevision && config.modulesOverride) {
    const next = JSON.parse(JSON.stringify(cardStore.cards.get(record.cardId)))
    const modules = next?.extensions?.airi?.modules
    if (!modules || typeof modules !== 'object') throw new Error('INVALID_MANAGED_CHARACTER_MODULES')
    for (const name of ['consciousness', 'vision', 'speech']) {
      const selection = config.modulesOverride[name]
      if (!selection || typeof selection !== 'object' || typeof selection.provider !== 'string' || typeof selection.model !== 'string') continue
      const patch = { provider: selection.provider, model: selection.model }
      if (name === 'speech' && typeof selection.voice_id === 'string') patch.voice_id = selection.voice_id
      modules[name] = { ...(modules[name] || {}), ...patch }
    }
    if (!await cardStore.updateCard(record.cardId, { extensions: next.extensions })) throw new Error('CHARACTER_SELECTION_UPDATE_FAILED')
    record = { ...record, selectionRevision: config.selectionRevision }
    managed[config.id] = record
    localStorage.setItem(marker, JSON.stringify(managed))
  }
  if (config.activate !== false && !await cardStore.activateCard(record.cardId)) throw new Error('CHARACTER_ACTIVATION_FAILED')
  // Synced Pinia actions can settle their reactive controls after the action reply.
  for (let attempt = 0; config.activate !== false && attempt < 20 && !cardStore.activeLive2DModelControls?.expressions?.length; attempt += 1) await wait(100)
  const pinia = document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$pinia
  const live2d = pinia?._s?.get('live2d')
  if (config.viewRevision && record.viewRevision !== config.viewRevision && config.view && live2d && config.activate !== false) {
    const view = config.view
    if (![view.x, view.y, view.scale].every(Number.isFinite) || Math.abs(view.x) > 500 || Math.abs(view.y) > 500 || view.scale < 0.01 || view.scale > 3) throw new Error('INVALID_CHARACTER_VIEW')
    live2d.position = { x: view.x, y: view.y }
    live2d.scale = view.scale
    live2d.shouldUpdateView()
    record = { ...record, viewRevision: config.viewRevision }
    managed[config.id] = record
    localStorage.setItem(marker, JSON.stringify(managed))
  }
  // Selection is applied once at startup; subsequent user choices in this run remain theirs.
  const boundCard = cardStore.cards.get(record.cardId)
  const boundAvatar = boundCard?.extensions?.airi?.avatarModels?.find(avatar => avatar.displayModelId === record.displayModelId)
  const isActive = cardStore.activeCardId === record.cardId
  return { phase: config.activate === false ? 'imported' : 'active', imported, cardId: record.cardId, displayModelId: record.displayModelId,
    expressionCount: isActive ? cardStore.activeLive2DModelControls?.expressions?.length || 0 : null,
    active: isActive,
    avatarType: boundAvatar?.type || null,
    modelFormat: model.format,
    view: isActive && live2d ? { position: { ...live2d.position }, scale: live2d.scale } : config.view || null,
    modules: JSON.parse(JSON.stringify(cardStore.getModules(record.cardId))) }
}
