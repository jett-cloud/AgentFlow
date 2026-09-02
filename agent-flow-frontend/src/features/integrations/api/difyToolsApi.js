// Console tool catalog / credential APIs.
import difyClient from '../../../shared/http/difyClient.js'

/** Keep slash-separated plugin ids for Flask `<path:...>` routes. */
export function encodeProviderPath(provider) {
  return String(provider || '')
    .split('/')
    .map(segment => encodeURIComponent(segment))
    .join('/')
}

export function fetchToolProviders() {
  return difyClient.get('/workspaces/current/tool-providers')
}

export function fetchBuiltinTools(config) {
  return difyClient.get('/workspaces/current/tools/builtin', config)
}

export function fetchMcpTools(config) {
  return difyClient.get('/workspaces/current/tools/mcp', config)
}

export function fetchMcpProviders(config) {
  return difyClient.get('/workspaces/current/tool-providers', {
    ...config,
    params: { ...config?.params, type: 'mcp' },
  })
}

export function fetchMcpProvider(providerId, config) {
  return difyClient.get(
    `/workspaces/current/tool-provider/mcp/tools/${encodeProviderPath(providerId)}`,
    config,
  )
}

export function createMcpProvider(payload) {
  return difyClient.post('/workspaces/current/tool-provider/mcp', payload)
}

export function updateMcpProvider(payload) {
  return difyClient.put('/workspaces/current/tool-provider/mcp', payload)
}

export function deleteMcpProvider(providerId) {
  return difyClient.delete('/workspaces/current/tool-provider/mcp', {
    data: { provider_id: providerId },
  })
}

export function authorizeMcpProvider(providerId) {
  return difyClient.post('/workspaces/current/tool-provider/mcp/auth', {
    provider_id: providerId,
  })
}

export function refreshMcpProviderTools(providerId) {
  return difyClient.get(
    `/workspaces/current/tool-provider/mcp/update/${encodeProviderPath(providerId)}`,
  )
}

export async function fetchAllTools(fetchers = {
  builtin: fetchBuiltinTools,
  mcp: fetchMcpTools,
}) {
  const silent = { silent: true }
  const [builtin, mcp] = await Promise.all([
    fetchers.builtin?.(silent).catch(() => []) ?? [],
    fetchers.mcp?.(silent).catch(() => []) ?? [],
  ])
  return {
    builtin: unwrapList(builtin),
    mcp: unwrapList(mcp),
  }
}

export function fetchBuiltinProviderTools(provider) {
  return difyClient.get(
    `/workspaces/current/tool-provider/builtin/${encodeProviderPath(provider)}/tools`,
  )
}

export function fetchBuiltinCredentials(provider) {
  return difyClient.get(
    `/workspaces/current/tool-provider/builtin/${encodeProviderPath(provider)}/credentials`,
  )
}

export function fetchBuiltinCredentialInfo(provider, config) {
  return difyClient.get(
    `/workspaces/current/tool-provider/builtin/${encodeProviderPath(provider)}/credential/info`,
    config,
  )
}

/** Current Console route: /credential/schema/{credential_type} (legacy path removed). */
export function fetchBuiltinCredentialSchema(provider, credentialType = 'api-key') {
  return difyClient.get(
    `/workspaces/current/tool-provider/builtin/${encodeProviderPath(provider)}/credential/schema/${encodeURIComponent(credentialType)}`,
  )
}

export function addBuiltinCredential(provider, payload) {
  return difyClient.post(
    `/workspaces/current/tool-provider/builtin/${encodeProviderPath(provider)}/add`,
    payload,
  )
}

export function updateBuiltinCredential(provider, payload) {
  return difyClient.post(
    `/workspaces/current/tool-provider/builtin/${encodeProviderPath(provider)}/update`,
    payload,
  )
}

export function deleteBuiltinCredential(provider, { credential_id }) {
  return difyClient.post(
    `/workspaces/current/tool-provider/builtin/${encodeProviderPath(provider)}/delete`,
    { credential_id },
  )
}

export function setDefaultBuiltinCredential(provider, { id }) {
  return difyClient.post(
    `/workspaces/current/tool-provider/builtin/${encodeProviderPath(provider)}/default-credential`,
    { id },
  )
}

/** Normalize credentials list response (array or wrapped). */
export function unwrapCredentialList(payload) {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.credentials)) return payload.credentials
  if (Array.isArray(payload?.data)) return payload.data
  return []
}

function unwrapList(payload) {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.data)) return payload.data
  return []
}
