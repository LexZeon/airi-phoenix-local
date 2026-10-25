function installManagedCharacterViews(entries) {
  const pinia = document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$pinia
  const cards = pinia?._s?.get('airi-card')
  const live2d = pinia?._s?.get('live2d')
  if (!cards || !live2d) throw new Error('CHARACTER_VIEW_STORES_NOT_READY')
  const key = 'airi-offline/character-views'
  const defaults = new Map(entries.filter(entry => entry.view && entry.cardId).map(entry => [entry.cardId, entry]))
  let saved
  try { saved = JSON.parse(localStorage.getItem(key) || '{}') } catch { throw new Error('INVALID_CHARACTER_VIEWS') }
  const valid = view => view && [view.x, view.y, view.scale].every(Number.isFinite) && Math.abs(view.x) <= 500 && Math.abs(view.y) <= 500 && view.scale >= 0.01 && view.scale <= 3
  for (const entry of defaults.values()) if (!valid(entry.view)) throw new Error('INVALID_CHARACTER_VIEW')
  globalThis.__airiManagedViewController?.dispose()
  let previous = ''
  function apply() {
    const id = cards.activeCardId
    if (previous === id) return
    if (defaults.has(previous)) {
      const view = { ...live2d.position, scale: live2d.scale }
      if (valid(view)) saved[previous] = { revision: defaults.get(previous).revision, view }
      localStorage.setItem(key, JSON.stringify(saved))
    }
    previous = id
    const entry = defaults.get(id)
    if (!entry) return
    const stored = saved[id]
    const view = stored?.revision === entry.revision && valid(stored.view) ? stored.view : entry.view
    live2d.position = { x: view.x, y: view.y }
    live2d.scale = view.scale
    live2d.shouldUpdateView()
  }
  const dispose = cards.$subscribe(apply, { detached: true, flush: 'post' })
  globalThis.__airiManagedViewController = { dispose }
  apply()
  return { installed: true, managedViews: defaults.size }
}
