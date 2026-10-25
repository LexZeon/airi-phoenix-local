'use strict'

const { contextBridge, ipcRenderer } = require('electron')

const CHANNEL = 'airi-offline'
const MARKER = 'airi-offline/profile-revision'

// Only AIRI's own local main frames receive this narrow IPC bridge; main validates the sender again.
if (process.isMainFrame && location.protocol === 'file:') {
  contextBridge.exposeInMainWorld('airiOfflineScreen', {
    getState: () => ipcRenderer.invoke(`${CHANNEL}:get-screen-state`),
    setEnabled: enabled => {
      if (typeof enabled !== 'boolean') return Promise.reject(new Error('INVALID_SCREEN_CONTROL_REQUEST'))
      return ipcRenderer.invoke(`${CHANNEL}:set-screen-enabled`, enabled)
    },
    reportState: status => ipcRenderer.send(`${CHANNEL}:screen-control-status`, status),
    onState: callback => {
      if (typeof callback !== 'function') throw new Error('INVALID_SCREEN_CONTROL_CALLBACK')
      const listener = (_event, state) => callback(state)
      ipcRenderer.on(`${CHANNEL}:screen-state`, listener)
      return () => ipcRenderer.removeListener(`${CHANNEL}:screen-state`, listener)
    },
  })
}

function object(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function parseObject(raw, fallback = {}) {
  if (raw === null || raw === '') return fallback
  const value = JSON.parse(raw)
  if (!object(value)) throw new Error('INVALID_STORED_OBJECT')
  return value
}

function migrate() {
  if (!process.isMainFrame || location.protocol !== 'file:') return
  const response = ipcRenderer.sendSync(`${CHANNEL}:get-preset`)
  if (!response || !response.ok) return
  const preset = response.preset
  if (localStorage.getItem(MARKER) === preset.revision) {
    ipcRenderer.send(`${CHANNEL}:migration-status`, { applied: true, changed: false, revision: preset.revision })
    return
  }

  const keys = new Set([
    ...Object.keys(preset.storage),
    'settings/providers/configured',
    'settings/providers/added',
    'settings/audio/input',
    'airi-card-module-defaults',
    'airi-cards',
    'settings/feature-flags',
    MARKER,
  ])
  const previous = Object.fromEntries([...keys].map(key => [key, localStorage.getItem(key)]))
  const backup = ipcRenderer.sendSync(`${CHANNEL}:backup`, { revision: preset.revision, values: previous })
  if (!backup || !backup.ok) throw new Error('PROFILE_BACKUP_FAILED')

  const providers = parseObject(previous['settings/providers/configured'])
  const added = parseObject(previous['settings/providers/added'])
  for (const [id, provider] of Object.entries(preset.providers)) {
    providers[id] = provider
    added[id] = true
  }
  const defaults = parseObject(previous['airi-card-module-defaults'])
  for (const [name, selection] of Object.entries(preset.modules)) {
    defaults[name] = { ...(object(defaults[name]) ? defaults[name] : {}), ...selection }
  }
  const changes = {
    ...preset.storage,
    'settings/providers/configured': JSON.stringify(providers),
    'settings/providers/added': JSON.stringify(added),
    'airi-card-module-defaults': JSON.stringify(defaults),
  }

  // Existing cards keep their per-card overrides. Managed characters are added
  // through the application's own addCard/model APIs after stores are ready.

  const flags = parseObject(previous['settings/feature-flags'])
  flags[JSON.stringify(['character-card-sync', null])] = false
  flags[JSON.stringify(['display-model-sync', null])] = false
  changes['settings/feature-flags'] = JSON.stringify(flags)

  // Preserve the selected microphone. An empty value already selects the system default.
  if (localStorage.getItem('settings/audio/input') === null) changes['settings/audio/input'] = ''
  try {
    for (const [key, value] of Object.entries(changes)) localStorage.setItem(key, value)
    localStorage.setItem(MARKER, preset.revision)
  } catch (error) {
    for (const [key, value] of Object.entries(previous)) {
      if (value === null) localStorage.removeItem(key)
      else localStorage.setItem(key, value)
    }
    throw error
  }
  ipcRenderer.send(`${CHANNEL}:migration-status`, {
    applied: true,
    changed: true,
    revision: preset.revision,
    keyCount: Object.keys(changes).length,
  })
}

try {
  migrate()
} catch (error) {
  ipcRenderer.send(`${CHANNEL}:migration-status`, {
    applied: false,
    changed: false,
    errorCode: /^[A-Z_]+$/.test(String(error.message)) ? error.message : error.name,
  })
}
