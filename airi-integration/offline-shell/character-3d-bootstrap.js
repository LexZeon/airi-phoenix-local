async function bootstrapManaged3DCharacter(config) {
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms))
  const marker = 'airi-offline/managed-3d-characters'
  if (!config || !/^[a-z][a-z0-9-]*-3d$/.test(config.id || '')) throw new Error('INVALID_3D_CHARACTER_ID')
  if (!config.card || typeof config.card.name !== 'string') throw new Error('INVALID_3D_CHARACTER_CARD')
  const modelUrl = new URL(config.modelUrl)
  if (modelUrl.protocol !== 'http:' || modelUrl.hostname !== '127.0.0.1' || modelUrl.port !== '9943' || modelUrl.username || modelUrl.password || modelUrl.search || modelUrl.hash) throw new Error('INVALID_LOCAL_3D_MODEL_URL')
  let cardStore, displayStore, pinia
  for (let attempt = 0; attempt < 240; attempt += 1) {
    const app = document.querySelector('#app')?.__vue_app__
    pinia = app?.config?.globalProperties?.$pinia
    cardStore = pinia?._s?.get('airi-card')
    displayStore = pinia?._s?.get('display-models')
    if (cardStore?.ready && displayStore?.addDisplayModel && displayStore?.getDisplayModel) break
    await wait(250)
  }
  if (!cardStore?.ready || !displayStore?.addDisplayModel) throw new Error('CHARACTER_3D_STORES_NOT_READY')
  const activeCardIdBefore = cardStore.activeCardId
  let managed
  try { managed = JSON.parse(localStorage.getItem(marker) || '{}') } catch { throw new Error('INVALID_MANAGED_3D_STATE') }
  if (!managed || Array.isArray(managed) || typeof managed !== 'object') throw new Error('INVALID_MANAGED_3D_STATE')
  let record = managed[config.id]
  if (record && cardStore.cards.has(record.cardId)) {
    const registered = cardStore.cards.get(record.cardId)
    const binding = registered?.extensions?.airi?.avatarModels?.find(model => model.displayModelId === record.displayModelId)
    // A stale/tampered 3D marker must never turn an existing Live2D card into MMD.
    if (!binding || binding.type !== 'mmd') record = undefined
  }
  let imported = false, modelChanged = false, modulesChanged = false
  const clone = value => JSON.parse(JSON.stringify(value))
  const modulePatch = {}
  for (const key of ['consciousness', 'vision', 'speech']) {
    if (config.modulesOverride?.[key]) modulePatch[key] = clone(config.modulesOverride[key])
  }
  async function importModel() {
    const response = await fetch(modelUrl.href, { cache: 'no-store', credentials: 'omit' })
    if (!response.ok) throw new Error('CHARACTER_3D_MODEL_UNAVAILABLE')
    const buffer = await response.arrayBuffer()
    const bytes = new Uint8Array(buffer)
    if (bytes.length < 4 || bytes.length > 128 * 1024 * 1024 || bytes[0] !== 0x50 || bytes[1] !== 0x4b || bytes[2] !== 3 || bytes[3] !== 4) throw new Error('INVALID_3D_MODEL_ARCHIVE')
    if (config.modelSha256) {
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', buffer)), value => value.toString(16).padStart(2, '0')).join('')
      if (hash !== config.modelSha256) throw new Error('CHARACTER_3D_MODEL_HASH_MISMATCH')
    }
    const file = new File([buffer], config.modelName || 'Private3D.pmx.zip', { type: 'application/zip' })
    const model = await displayStore.addDisplayModel('pmx-zip', file)
    if (!model?.id || model.format !== 'pmx-zip') throw new Error('CHARACTER_3D_MODEL_IMPORT_FAILED')
    const stored = await displayStore.getDisplayModel(model.id)
    if (!stored || stored.format !== 'pmx-zip') throw new Error('CHARACTER_3D_MODEL_PERSISTENCE_FAILED')
    return stored
  }
  if (!record || !cardStore.cards.has(record.cardId)) {
    const model = await importModel()
    const card = clone(config.card)
    card.extensions ||= {}
    card.extensions.airi ||= { avatarModels: [], modules: {}, agents: {} }
    card.extensions.airi.avatarModels = []
    delete card.extensions.airi.defaultAvatarModelId
    card.extensions.airi.modules = { ...card.extensions.airi.modules, ...modulePatch }
    const cardId = await cardStore.addCard(card, 'import', model.id)
    if (!cardId || !cardStore.cards.has(cardId)) throw new Error('CHARACTER_3D_CARD_IMPORT_FAILED')
    record = { cardId, displayModelId: model.id, modelRevision: config.modelRevision,
      selectionRevision: config.selectionRevision, importedAt: new Date().toISOString(), privateLocal: true }
    imported = true
  } else {
    const existingModel = await displayStore.getDisplayModel(record.displayModelId)
    if (!existingModel || existingModel.format !== 'pmx-zip' || record.modelRevision !== config.modelRevision) {
      const model = await importModel()
      if (!await cardStore.updateCard(record.cardId, {}, model.id)) throw new Error('CHARACTER_3D_MODEL_UPDATE_FAILED')
      record = { ...record, displayModelId: model.id, modelRevision: config.modelRevision }
      modelChanged = true
    }
    if (record.selectionRevision !== config.selectionRevision) {
      const existing = cardStore.cards.get(record.cardId)
      const extension = existing.extensions?.airi || {}
      if (!await cardStore.updateCard(record.cardId, {
        extensions: { ...clone(existing.extensions || {}), airi: { ...clone(extension), modules: { ...clone(extension.modules || {}), ...modulePatch } } },
      })) throw new Error('CHARACTER_3D_MODULE_UPDATE_FAILED')
      record = { ...record, selectionRevision: config.selectionRevision }
      modulesChanged = true
    }
  }
  const card = cardStore.cards.get(record.cardId)
  const avatar = card?.extensions?.airi?.avatarModels?.find(model => model.displayModelId === record.displayModelId)
  if (!avatar || avatar.type !== 'mmd') throw new Error('CHARACTER_3D_AVATAR_BINDING_FAILED')
  if (config.behaviorRevision && record.behaviorRevision !== config.behaviorRevision && typeof config.behaviorSuffix === 'string') {
    if (config.behaviorSuffix.length > 3000) throw new Error('INVALID_3D_BEHAVIOR_SUFFIX')
    const originalPrompt = String(card.systemPrompt || '').replace(/\n\n<!-- AIRI_LOCAL_MMD_CONTROLS -->[\s\S]*?<!-- END_AIRI_LOCAL_MMD_CONTROLS -->/g, '')
    const systemPrompt = originalPrompt + '\n\n<!-- AIRI_LOCAL_MMD_CONTROLS -->\n' + config.behaviorSuffix + '\n<!-- END_AIRI_LOCAL_MMD_CONTROLS -->'
    if (!await cardStore.updateCard(record.cardId, { systemPrompt })) throw new Error('CHARACTER_3D_BEHAVIOR_UPDATE_FAILED')
    record = { ...record, behaviorRevision: config.behaviorRevision }
  }
  managed[config.id] = record
  localStorage.setItem(marker, JSON.stringify(managed))
  // MMD physics is an application-wide MMD store setting, not a per-card field.
  // This does not alter Live2D model placement or controls.
  localStorage.setItem('settings/mmd/physics-enabled', JSON.stringify(false))
  const mmd = pinia?._s?.get('mmd')
  if (mmd) mmd.physicsEnabled = false
  if (config.activate && !await cardStore.activateCard(record.cardId)) throw new Error('CHARACTER_3D_ACTIVATION_FAILED')
  return { phase: config.activate ? 'active' : 'imported', imported, modelChanged, modulesChanged, cardId: record.cardId,
    displayModelId: record.displayModelId, avatarModelId: avatar.id, format: 'pmx-zip',
    activated: Boolean(config.activate), activeCardPreserved: cardStore.activeCardId === activeCardIdBefore,
    physicsEnabled: false, selectionRevision: record.selectionRevision }
}
