/**
 * Agent Soul dify_tools helpers (catalog tool ↔ soul config).
 */

import { normalizeDifyTool } from './agentSoul.js'

/** Providers that must not be attached as Agent tools (knowledge path only). */
export const AGENT_TOOL_BLOCKED_PROVIDER_TYPES = new Set(['dataset-retrieval', 'dataset_retrieval'])

function isMcpProviderLevel(catalogTool) {
  if ((catalogTool?.provider_type || '') !== 'mcp')
    return false
  const rawName = catalogTool?.tool_name
  return rawName == null || String(rawName).trim() === '' || rawName === '*'
}

function sameDifyProvider(left, right) {
  return (left?.provider_type || 'builtin') === (right?.provider_type || 'builtin')
    && String(left?.provider_id || left?.provider || '') === String(right?.provider_id || right?.provider || '')
}

/**
 * @param {object} catalogTool
 * @param {{ credentialId?: string, runtimeParameters?: object, enabled?: boolean }} [options]
 */
export function catalogToolToDifyTool(catalogTool, options = {}) {
  if (!catalogTool || typeof catalogTool !== 'object')
    return null
  if (AGENT_TOOL_BLOCKED_PROVIDER_TYPES.has(String(catalogTool.provider_type || '')))
    return null

  const providerId = String(catalogTool.provider_id || '').trim()
  if (!providerId)
    return null
  const toolName = isMcpProviderLevel(catalogTool) ? null : String(catalogTool.tool_name || '').trim()
  if (!toolName && !isMcpProviderLevel(catalogTool))
    return null

  const credentialId = String(options.credentialId || catalogTool.credential_id || '').trim()
  return normalizeDifyTool({
    enabled: options.enabled !== false,
    provider_type: catalogTool.provider_type || 'builtin',
    provider_id: providerId,
    provider: catalogTool.provider_name || providerId,
    plugin_id: catalogTool.plugin_id || undefined,
    tool_name: toolName,
    description: catalogTool.description || undefined,
    credential_type: credentialId ? 'api-key' : 'unauthorized',
    credential_ref: credentialId
      ? { type: 'provider', id: credentialId, provider: providerId }
      : undefined,
    runtime_parameters: options.runtimeParameters || {},
  })
}

/**
 * Stable identity for a soul tool entry.
 * @param {object} tool
 */
export function difyToolKey(tool) {
  const providerType = tool?.provider_type || 'builtin'
  const provider = tool?.provider_id || tool?.provider || tool?.plugin_id || ''
  const name = tool?.tool_name || '*'
  return `${providerType}::${provider}::${name}`
}

/**
 * @param {object[]} tools
 * @param {object} catalogTool
 * @param {{ credentialId?: string }} [options]
 */
export function addDifyTool(tools, catalogTool, options = {}) {
  const entry = catalogToolToDifyTool(catalogTool, options)
  if (!entry)
    return Array.isArray(tools) ? [...tools] : []
  const list = Array.isArray(tools) ? [...tools] : []
  if (list.some(item => difyToolKey(item) === difyToolKey(entry)))
    return list
  if (!entry.tool_name)
    return [...list.filter(item => !sameDifyProvider(item, entry)), entry]
  if (list.some(item => sameDifyProvider(item, entry) && !item.tool_name))
    return list
  list.push(entry)
  return list
}

/**
 * True when the catalog option is already covered by the Soul tool list.
 * A provider-level MCP entry (`tool_name` null) covers every tool of that server.
 * @param {object[]} tools
 * @param {object} catalogTool
 */
export function isCatalogToolSelected(tools, catalogTool) {
  const list = Array.isArray(tools) ? tools : []
  const key = difyToolKey(catalogTool)
  if (list.some(item => difyToolKey(item) === key))
    return true
  return list.some(item => sameDifyProvider(item, catalogTool) && !item.tool_name)
}

/**
 * @param {object[]} tools
 * @param {string} key
 */
export function removeDifyTool(tools, key) {
  return (Array.isArray(tools) ? tools : []).filter(item => difyToolKey(item) !== key)
}

/**
 * @param {object[]} tools
 * @param {string} key
 * @param {boolean} enabled
 */
export function setDifyToolEnabled(tools, key, enabled) {
  return (Array.isArray(tools) ? tools : []).map((item) => {
    if (difyToolKey(item) !== key)
      return item
    return normalizeDifyTool({ ...item, enabled: !!enabled })
  }).filter(Boolean)
}

/**
 * @param {object[]} tools
 * @param {string} key
 * @param {string} credentialId
 */
export function setDifyToolCredential(tools, key, credentialId) {
  const id = String(credentialId || '').trim()
  return (Array.isArray(tools) ? tools : []).map((item) => {
    if (difyToolKey(item) !== key)
      return item
    return normalizeDifyTool({
      ...item,
      credential_type: id ? 'api-key' : 'unauthorized',
      credential_ref: id
        ? { type: 'provider', id, provider: item.provider_id || item.provider }
        : undefined,
      credential_id: undefined,
    })
  }).filter(Boolean)
}

/**
 * Display label for a soul tool.
 * @param {object} tool
 * @param {(query: { provider_id: string, tool_name: string }) => object | null} [findCatalogTool]
 */
export function difyToolLabel(tool, findCatalogTool) {
  const catalog = findCatalogTool?.({
    provider_type: tool?.provider_type,
    provider_id: tool?.provider_id,
    tool_name: tool?.tool_name,
  })
  if (catalog)
    return `${catalog.provider_name} / ${catalog.tool_label || catalog.tool_name}`
  const provider = tool?.provider || tool?.provider_id || 'tool'
  return tool?.tool_name ? `${provider} / ${tool.tool_name}` : String(provider)
}
