// Agent-v2 composer / roster APIs.
import difyClient from '../../../shared/http/difyClient.js'

function composerPath(appId, nodeId, suffix = '') {
  return `/apps/${encodeURIComponent(appId)}/workflows/draft/nodes/${encodeURIComponent(nodeId)}/agent-composer${suffix}`
}

export function loadAgentComposer(appId, nodeId, { snapshotId } = {}) {
  return difyClient.get(composerPath(appId, nodeId), {
    params: snapshotId ? { snapshot_id: snapshotId } : undefined,
  })
}

export function saveAgentComposer(appId, nodeId, payload) {
  return difyClient.put(composerPath(appId, nodeId), payload)
}

export function validateAgentComposer(appId, nodeId, payload) {
  return difyClient.post(composerPath(appId, nodeId, '/validate'), payload)
}

export function fetchAgentComposerCandidates(appId, nodeId) {
  return difyClient.get(composerPath(appId, nodeId, '/candidates'))
}

export function copyAgentFromRoster(appId, nodeId, payload) {
  return difyClient.post(composerPath(appId, nodeId, '/copy-from-roster'), payload)
}

export function listRosterAgents({ page = 1, limit = 30, keyword = '' } = {}) {
  return difyClient.get('/agent', {
    params: {
      page,
      limit,
      ...(keyword ? { keyword } : {}),
    },
  })
}

/**
 * Classic Agent strategy providers.
 * Contrasts Dify GET /workspaces/current/agent-providers
 */
export function listAgentStrategies() {
  return difyClient.get('/workspaces/current/agent-providers', { silent: true })
}
