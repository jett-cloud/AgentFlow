import { normalizeToolProviderType } from '../../../integrations/state/toolCatalog.js'
import {
  ToolVarKind,
  buildEmptyToolConfigurations,
  buildEmptyToolParameters,
  getToolParamEditorKind,
  isGraphonConfigurationValue,
  isLlmToolParam,
  isToolFileParam,
  isToolFileVariable,
  normalizeToolParameter,
  normalizeToolParameters,
  setToolParamEnvelope,
  syncToolFormConfiguration,
} from '../../model/toolParamInputs.js'
import { getToolDeclaredOutputVars } from '../../model/variableOutputs.js'

export const TOOL_DEFAULTS = Object.freeze({
  provider_id: '', provider_type: 'builtin', provider_name: '', provider_icon: null,
  tool_name: '', tool_label: '', tool_parameters: {}, tool_configurations: {},
  credential_id: '', tool_node_version: '2',
})

export { getToolParamEditorKind, isLlmToolParam, isToolFileParam, isToolFileVariable }

function mergeFormConfigurations(data = {}, parameters = {}) {
  const configs = data.tool_configurations && typeof data.tool_configurations === 'object' && !Array.isArray(data.tool_configurations)
    ? { ...data.tool_configurations }
    : {}
  for (const param of Array.isArray(data.parameters) ? data.parameters : []) {
    if (!param?.name || isLlmToolParam(param) || configs[param.name] !== undefined)
      continue
    const envelope = parameters[param.name]
    if (!envelope)
      continue
    const value = normalizeToolParameter(envelope).value
    if (isGraphonConfigurationValue(value))
      configs[param.name] = value
  }
  return configs
}

export function normalizeToolNodeData(data = {}) {
  const tool_parameters = normalizeToolParameters(data.tool_parameters)
  return {
    ...data,
    provider_id: String(data.provider_id || ''),
    provider_type: String(data.provider_type || 'builtin'),
    provider_name: String(data.provider_name || ''),
    tool_name: String(data.tool_name || data.toolName || ''),
    tool_label: String(data.tool_label || data.toolLabel || ''),
    tool_parameters,
    tool_configurations: mergeFormConfigurations(data, tool_parameters),
    credential_id: data.credential_id == null ? '' : String(data.credential_id),
  }
}

export function isToolConfigured(data = {}) {
  return Boolean(String(data.provider_id || '').trim() && String(data.tool_name || data.toolName || '').trim())
}

export function sameToolIdentity(data = {}, tool = {}) {
  return String(data.provider_id || '') === String(tool.provider_id || '')
    && String(data.tool_name || data.toolName || '') === String(tool.tool_name || '')
    && normalizeToolProviderType(data.provider_type || 'builtin') === normalizeToolProviderType(tool.provider_type || 'builtin')
}

export function applyToolSelection(data = {}, tool) {
  if (!tool)
    return normalizeToolNodeData(data)
  const same = sameToolIdentity(data, tool)
  const previous = same ? normalizeToolParameters(data.tool_parameters) : {}
  const seeded = buildEmptyToolParameters(tool.parameters || [])
  for (const name of Object.keys(seeded)) {
    if (previous[name] !== undefined)
      seeded[name] = normalizeToolParameter(previous[name])
  }
  const seededConfigs = buildEmptyToolConfigurations(tool.parameters || [])
  const next = {
    ...data,
    provider_id: tool.provider_id,
    provider_type: tool.provider_type,
    provider_name: tool.provider_name,
    provider_icon: tool.icon ?? tool.icon_small ?? null,
    tool_name: tool.tool_name,
    tool_label: tool.tool_label,
    tool_parameters: seeded,
    tool_configurations: same
      ? { ...seededConfigs, ...(data.tool_configurations || {}) }
      : seededConfigs,
    credential_id: same ? (data.credential_id || '') : '',
    tool_node_version: data.tool_node_version || '2',
    is_team_authorization: tool.is_team_authorization,
    parameters: tool.parameters || [],
    output_schema: tool.output_schema || {},
    title: tool.tool_label || tool.tool_name || data.title,
  }
  if (tool.plugin_unique_identifier)
    next.plugin_unique_identifier = tool.plugin_unique_identifier
  else if (!same)
    delete next.plugin_unique_identifier
  return normalizeToolNodeData(next)
}

export function applyToolParamUpdate(data, param, envelope) {
  const name = param?.name
  if (!name)
    return normalizeToolNodeData(data)
  const normalized = normalizeToolNodeData(data)
  const tool_parameters = setToolParamEnvelope(normalized.tool_parameters, name, envelope)
  return normalizeToolNodeData({
    ...normalized,
    tool_parameters,
    tool_configurations: syncToolFormConfiguration(normalized.tool_configurations, param, tool_parameters[name]),
  })
}

export function setToolErrorStrategy(data, strategy) {
  const normalized = normalizeToolNodeData(data)
  if (!strategy || strategy === 'none') {
    const { error_strategy: _strategy, default_value: _defaultValue, ...rest } = normalized
    return rest
  }
  const next = { ...normalized, error_strategy: strategy }
  if (strategy === 'default-value') {
    const current = Array.isArray(normalized.default_value) ? normalized.default_value : []
    const byKey = new Map(current.map(item => [item?.key, item]))
    const keys = getToolDeclaredOutputVars(normalized)
    next.default_value = keys.map(item => ({
      value: '',
      ...(byKey.get(item.variable) || {}),
      key: item.variable,
      type: item.type,
    }))
  }
  else {
    delete next.default_value
  }
  return next
}

export function updateToolDefaultValue(data, key, value) {
  const normalized = setToolErrorStrategy(data, 'default-value')
  return {
    ...normalized,
    default_value: (normalized.default_value || []).map(item => (
      item.key === key ? { ...item, value } : item
    )),
  }
}

export { ToolVarKind }
