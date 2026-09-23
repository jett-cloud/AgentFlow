import difyClient, { CSRF_HEADER_NAME, DIFY_API_PREFIX, getCsrfToken } from '../../../shared/http/difyClient.js'
import { consumeSseText, parseSseBlock, shouldConsumeAsSse } from '../../../shared/http/difyProtocol.js'
import { refreshAccessTokenOrReLogin } from '../../../shared/auth/difyRefreshToken.js'
import { readBlobErrorMessage } from '../tool-plugin/downloadResponseHelpers.js'

const LONG_TIMEOUT = { timeout: 600000 }

export function generateToolPlugin(payload) {
  return difyClient.post('/workspaces/current/tool-plugin/generate', payload, LONG_TIMEOUT)
}

export function validateToolPlugin(payload) {
  return difyClient.post('/workspaces/current/tool-plugin/validate', payload)
}

export function uninstallToolPlugin(payload) {
  return difyClient.post('/workspaces/current/tool-plugin/uninstall', payload)
}

export function purgeToolPluginByPluginId(payload) {
  return difyClient.post('/workspaces/current/tool-plugin/purge-by-plugin-id', payload)
}

export function testToolPlugin(payload) {
  return difyClient.post('/workspaces/current/tool-plugin/test', payload)
}

export function agentTurnToolPlugin(payload) {
  return difyClient.post('/workspaces/current/tool-plugin/agent/turn', payload, LONG_TIMEOUT)
}

/**
 * Stream agent turn steps via SSE.
 * @param {object} payload
 * @param {{ onEvent?: (event: object) => void, signal?: AbortSignal }} [options]
 */
export async function agentTurnToolPluginStream(payload, { onEvent = () => {}, signal } = {}) {
  async function openStream() {
    const headers = {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    }
    const csrfToken = getCsrfToken(document.cookie)
    if (csrfToken)
      headers[CSRF_HEADER_NAME] = csrfToken

    return fetch(`${DIFY_API_PREFIX}/workspaces/current/tool-plugin/agent/turn/stream`, {
      method: 'POST',
      credentials: 'include',
      headers,
      body: JSON.stringify(payload),
      signal,
    })
  }

  let response = await openStream()
  if (response.status === 401) {
    await refreshAccessTokenOrReLogin()
    response = await openStream()
  }

  if (!response.ok) {
    let errorData = null
    try {
      errorData = await response.json()
    }
    catch {
      // ignore non-JSON
    }
    const error = new Error(errorData?.message || errorData?.error || response.statusText || 'Agent stream failed')
    error.status = response.status
    error.data = errorData
    throw error
  }

  if (!shouldConsumeAsSse(response)) {
    const data = await response.json()
    onEvent(data)
    return data
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let doneEvent = null
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    buffer = consumeSseText(buffer, (event) => {
      onEvent(event)
      if (event?.event === 'done')
        doneEvent = event
    })
    if (done)
      break
  }
  if (buffer.trim()) {
    const payloadEvent = parseSseBlock(buffer)
    if (payloadEvent) {
      onEvent(payloadEvent)
      if (payloadEvent?.event === 'done')
        doneEvent = payloadEvent
    }
  }
  return doneEvent
}

export async function downloadToolPluginZip(payload) {
  try {
    const response = await difyClient.post('/workspaces/current/tool-plugin/download', payload, {
      responseType: 'blob',
      transformResponse: [data => data],
      silent: true,
    })
    if (response instanceof Blob)
      return response
    return new Blob([response], { type: 'application/zip' })
  }
  catch (error) {
    const message = await readBlobErrorMessage(error.response?.data)
    if (message)
      error.message = message
    throw error
  }
}

export function listToolPluginSessions({ includeHidden = false } = {}) {
  const params = includeHidden ? { include_hidden: true } : undefined
  return difyClient.get('/workspaces/current/tool-plugin/sessions', { params })
}

export function createToolPluginSession(payload = {}) {
  return difyClient.post('/workspaces/current/tool-plugin/sessions', payload)
}

export function forkToolPluginSession({ source_session_id, title } = {}) {
  return difyClient.post('/workspaces/current/tool-plugin/session-fork', {
    source_session_id,
    title: title || undefined,
  })
}

export function getToolPluginSession(sessionId) {
  return difyClient.get(`/workspaces/current/tool-plugin/sessions/${sessionId}`)
}

export function updateToolPluginSession(sessionId, payload) {
  return difyClient.put(`/workspaces/current/tool-plugin/sessions/${sessionId}`, payload)
}

export function publishToolPluginSession(sessionId, payload) {
  return difyClient.post(`/workspaces/current/tool-plugin/sessions/${sessionId}/publish`, payload, LONG_TIMEOUT)
}

export function authorizeToolPluginTest(sessionId, payload) {
  return difyClient.post(`/workspaces/current/tool-plugin/sessions/${sessionId}/test-authorization`, payload)
}

export function deleteToolPluginSession(sessionId) {
  return difyClient.delete(`/workspaces/current/tool-plugin/sessions/${sessionId}`)
}

export function hideToolPluginSession(sessionId) {
  return difyClient.post(`/workspaces/current/tool-plugin/sessions/${sessionId}/hide`)
}

export function unhideToolPluginSession(sessionId) {
  return difyClient.post(`/workspaces/current/tool-plugin/sessions/${sessionId}/unhide`)
}
