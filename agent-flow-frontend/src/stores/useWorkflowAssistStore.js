import { defineStore } from 'pinia'

const LEGACY_MODEL_STORAGE_KEY = 'workflow-assist:model'
const PREFERENCES_STORAGE_KEY = 'workflow-assist:prefs'
const COORDINATION_STORAGE_PREFIX = 'workflow-assist:v2:'

function emptyCoordination() {
  return {
    conversation_id: '',
    run_id: '',
    epoch: null,
    cursor: 0,
  }
}

function nonNegativeInteger(value, fallback) {
  const numeric = Number(value)
  return Number.isInteger(numeric) && numeric >= 0 ? numeric : fallback
}

function sanitizeCoordination(value) {
  if (!value || typeof value !== 'object')
    return emptyCoordination()
  const conversationId = String(value.conversation_id || '')
  const runId = conversationId ? String(value.run_id || '') : ''
  if (!runId)
    return { conversation_id: conversationId, run_id: '', epoch: null, cursor: 0 }
  return {
    conversation_id: conversationId,
    run_id: runId,
    epoch: nonNegativeInteger(value.epoch, null),
    cursor: nonNegativeInteger(value.cursor, 0),
  }
}

function workflowAssistSessionKey(appId) {
  return `${COORDINATION_STORAGE_PREFIX}${String(appId || '')}`
}

function readStoredCoordination(appId) {
  if (!appId || typeof sessionStorage === 'undefined')
    return emptyCoordination()
  try {
    return sanitizeCoordination(JSON.parse(sessionStorage.getItem(workflowAssistSessionKey(appId)) || ''))
  }
  catch {
    return emptyCoordination()
  }
}

function writeStoredCoordination(appId, coordination) {
  if (!appId || typeof sessionStorage === 'undefined')
    return
  try {
    sessionStorage.setItem(workflowAssistSessionKey(appId), JSON.stringify(coordination))
  }
  catch {
    // ignore quota / private mode
  }
}

function removeStoredCoordination(appId) {
  if (!appId || typeof sessionStorage === 'undefined')
    return
  try {
    sessionStorage.removeItem(workflowAssistSessionKey(appId))
  }
  catch {
    // ignore private mode
  }
}

function emptyModel() {
  return {
    provider: '',
    name: '',
    mode: 'chat',
    completion_params: {},
  }
}

function readStoredModel() {
  if (typeof localStorage === 'undefined')
    return emptyModel()
  try {
    const raw = localStorage.getItem(LEGACY_MODEL_STORAGE_KEY)
    if (!raw)
      return emptyModel()
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object')
      return emptyModel()
    return {
      provider: String(parsed.provider || ''),
      name: String(parsed.name || ''),
      mode: String(parsed.mode || 'chat'),
      completion_params: parsed.completion_params && typeof parsed.completion_params === 'object'
        ? parsed.completion_params
        : {},
    }
  }
  catch {
    return emptyModel()
  }
}

function writeStoredModel(model) {
  if (typeof localStorage === 'undefined')
    return
  try {
    localStorage.setItem(LEGACY_MODEL_STORAGE_KEY, JSON.stringify(model))
  }
  catch {
    // ignore quota / private mode
  }
}

function readStoredPreferences() {
  const empty = { preferredTools: [], preferredDatasets: [] }
  if (typeof localStorage === 'undefined')
    return empty
  try {
    const parsed = JSON.parse(localStorage.getItem(PREFERENCES_STORAGE_KEY) || '')
    if (!parsed || typeof parsed !== 'object')
      return empty
    return {
      preferredTools: Array.isArray(parsed.preferredTools) ? parsed.preferredTools : [],
      preferredDatasets: Array.isArray(parsed.preferredDatasets) ? parsed.preferredDatasets : [],
    }
  }
  catch {
    return empty
  }
}

function writeStoredPreferences(preferredTools, preferredDatasets) {
  if (typeof localStorage === 'undefined')
    return
  try {
    localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify({ preferredTools, preferredDatasets }))
  }
  catch {
    // ignore quota / private mode
  }
}

export const useWorkflowAssistStore = defineStore('workflowAssist', {
  state: () => {
    const preferences = readStoredPreferences()
    return {
      panelOpen: false,
      panelWidth: 420,
      selectedModel: readStoredModel(),
      toolCatalogue: null,
      toolCatalogueError: '',
      knowledgeCatalogue: null,
      knowledgeCatalogueError: '',
      preferredTools: preferences.preferredTools,
      preferredDatasets: preferences.preferredDatasets,
      coordinationByApp: {},
    }
  },

  getters: {
    hasSelectedModel(state) {
      return Boolean(state.selectedModel?.provider && state.selectedModel?.name)
    },
  },

  actions: {
    open() {
      this.panelOpen = true
    },

    close() {
      this.panelOpen = false
    },

    toggle() {
      this.panelOpen = !this.panelOpen
    },

    setPanelWidth(width) {
      const numeric = Number(width)
      const next = Number.isFinite(numeric) ? numeric : 420
      this.panelWidth = Math.min(560, Math.max(360, next))
    },

    getAppCoordination(appId) {
      return this.coordinationByApp[String(appId || '')] || emptyCoordination()
    },

    setAppCoordination(appId, value) {
      const id = String(appId || '')
      if (!id)
        return emptyCoordination()
      const coordination = sanitizeCoordination(value)
      this.coordinationByApp = { ...this.coordinationByApp, [id]: coordination }
      writeStoredCoordination(id, coordination)
      return coordination
    },

    hydrateAppCoordination(appId) {
      const id = String(appId || '')
      if (!id)
        return emptyCoordination()
      const coordination = readStoredCoordination(id)
      this.coordinationByApp = { ...this.coordinationByApp, [id]: coordination }
      return coordination
    },

    advanceAppCursor(appId, sequence) {
      const current = this.getAppCoordination(appId)
      const cursor = nonNegativeInteger(sequence, -1)
      if (!current.run_id || cursor <= current.cursor)
        return current
      return this.setAppCoordination(appId, { ...current, cursor })
    },

    reconcileAppCoordination(appId, server) {
      const current = this.getAppCoordination(appId)
      const conversationId = Object.hasOwn(server || {}, 'conversation_id')
        ? String(server?.conversation_id || '')
        : current.conversation_id
      const conversationChanged = conversationId !== current.conversation_id
      const hasRunSummary = Object.hasOwn(server || {}, 'active_run')
        || Object.hasOwn(server || {}, 'latest_run')
      if (!hasRunSummary)
        return this.setAppCoordination(appId, conversationChanged
          ? { conversation_id: conversationId }
          : current)

      const run = server?.active_run || server?.latest_run
      if (!run)
        return this.setAppCoordination(appId, { conversation_id: conversationId })

      const runId = String(run.run_id || '')
      const epoch = nonNegativeInteger(run.epoch, null)
      const sameRun = conversationId === current.conversation_id
        && runId === current.run_id
        && epoch === current.epoch
      return this.setAppCoordination(appId, {
        conversation_id: conversationId,
        run_id: runId,
        epoch,
        cursor: sameRun ? current.cursor : 0,
      })
    },

    clearAppCoordination(appId) {
      const id = String(appId || '')
      if (!id)
        return
      const next = { ...this.coordinationByApp }
      delete next[id]
      this.coordinationByApp = next
      removeStoredCoordination(id)
    },

    setSelectedModel(model) {
      const next = {
        provider: String(model?.provider || ''),
        name: String(model?.name || ''),
        mode: String(model?.mode || 'chat'),
        completion_params: model?.completion_params && typeof model.completion_params === 'object'
          ? model.completion_params
          : {},
      }
      this.selectedModel = next
      writeStoredModel(next)
    },

    setToolCatalogue(payload) {
      this.toolCatalogue = payload
      this.toolCatalogueError = ''
    },

    setToolCatalogueError(message) {
      this.toolCatalogueError = message || '加载工具目录失败'
    },

    setKnowledgeCatalogue(payload) {
      this.knowledgeCatalogue = payload
      this.knowledgeCatalogueError = ''
    },

    setKnowledgeCatalogueError(message) {
      this.knowledgeCatalogueError = message || '加载知识库目录失败'
    },

    addPreferredTool(tool) {
      const providerName = String(tool?.provider_name || '')
      const toolName = String(tool?.tool_name || '')
      if (!providerName || !toolName || this.preferredTools.some(item => (
        item.provider_name === providerName && item.tool_name === toolName
      )))
        return
      this.preferredTools.push({
        provider_name: providerName,
        tool_name: toolName,
        ...(tool.label ? { label: String(tool.label) } : {}),
      })
      writeStoredPreferences(this.preferredTools, this.preferredDatasets)
    },

    removePreferredTool(tool) {
      this.preferredTools = this.preferredTools.filter(item => (
        item.provider_name !== tool?.provider_name || item.tool_name !== tool?.tool_name
      ))
      writeStoredPreferences(this.preferredTools, this.preferredDatasets)
    },

    addPreferredDataset(dataset) {
      const id = String(dataset?.id || '')
      if (!id || this.preferredDatasets.some(item => item.id === id))
        return
      this.preferredDatasets.push({ id, name: String(dataset?.name || id) })
      writeStoredPreferences(this.preferredTools, this.preferredDatasets)
    },

    removePreferredDataset(dataset) {
      const id = String(typeof dataset === 'string' ? dataset : dataset?.id || '')
      this.preferredDatasets = this.preferredDatasets.filter(item => item.id !== id)
      writeStoredPreferences(this.preferredTools, this.preferredDatasets)
    },
  },
})

export {
  COORDINATION_STORAGE_PREFIX,
  PREFERENCES_STORAGE_KEY,
  emptyCoordination,
  emptyModel,
  workflowAssistSessionKey,
}
