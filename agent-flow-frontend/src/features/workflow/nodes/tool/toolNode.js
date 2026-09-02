import { normalizeToolProviderType } from '../../../integrations/state/toolCatalog.js'

export const TOOL_DEFAULTS = Object.freeze({
  provider_id: '', provider_type: 'builtin', provider_name: '', provider_icon: null,
  tool_name: '', tool_label: '', tool_parameters: {}, tool_configurations: {},
  credential_id: '', tool_node_version: '2',
})

export function normalizeToolNodeData(data = {}) {
  return {
    ...data,
    provider_id: String(data.provider_id || ''),
    provider_type: normalizeToolProviderType(data.provider_type || 'builtin'),
    provider_name: String(data.provider_name || ''),
    tool_name: String(data.tool_name || data.toolName || ''),
    tool_label: String(data.tool_label || data.toolLabel || ''),
    tool_parameters: data.tool_parameters && typeof data.tool_parameters === 'object' ? { ...data.tool_parameters } : {},
    tool_configurations: data.tool_configurations && typeof data.tool_configurations === 'object' ? { ...data.tool_configurations } : {},
  }
}

export function isToolConfigured(data = {}) {
  return Boolean(String(data.provider_id || '').trim() && String(data.tool_name || data.toolName || '').trim())
}
