import { resolveRemoteMcpIcon } from '../lib/remoteMcpPresentation.js'

export function normalizeToolProviderType(type) {
  const value = String(type || 'builtin')
  return value === 'plugin' ? 'builtin' : value
}

export function toolIdentityMatches(item, query = {}) {
  if (!item)
    return false
  if (query.provider_type && normalizeToolProviderType(item.provider_type) !== normalizeToolProviderType(query.provider_type))
    return false
  return item.provider_id === query.provider_id && item.tool_name === query.tool_name
}

const TOOL_GROUPS = Object.freeze([
  Object.freeze({ type: 'builtin', label: '工具插件' }),
  Object.freeze({ type: 'api', label: 'API 工具' }),
  Object.freeze({ type: 'workflow', label: '工作流工具' }),
  Object.freeze({ type: 'mcp', label: 'MCP 工具' }),
])

function localized(value, fallback = '') {
  if (typeof value === 'string')
    return value
  return value?.zh_Hans || value?.en_US || fallback
}

export function flattenToolCatalog(groups) {
  const list = []
  for (const group of TOOL_GROUPS) {
    for (const provider of groups?.[group.type] || []) {
      const providerId = provider.server_identifier
        || provider.id
        || provider.provider
        || provider.name
        || ''
      const providerName = localized(
        provider.label,
        provider.name || provider.provider || providerId,
      )
      const providerMeta = {
        provider_id: providerId,
        provider_type: group.type,
        provider_name: providerName,
        provider_catalogue_name: providerId,
        allow_delete: !!provider.allow_delete,
        is_team_authorization: provider.is_team_authorization,
        icon: group.type === 'mcp'
          ? { content: resolveRemoteMcpIcon({ ...provider, name: providerName }).value, background: '#eff4ff' }
          : provider.icon,
        icon_small: provider.icon_small,
        plugin_id: provider.plugin_id,
        plugin_unique_identifier: provider.plugin_unique_identifier,
      }
      if (group.type === 'mcp' && providerId) {
        list.push({
          ...providerMeta,
          tool_name: null,
          tool_label: '全部工具',
          description: '',
          parameters: [],
          output_schema: {},
        })
      }
      for (const tool of Array.isArray(provider.tools) ? provider.tools : []) {
        list.push({
          ...providerMeta,
          tool_name: tool.name || tool.tool_name,
          tool_label: localized(tool.label, tool.name || tool.tool_name),
          description: localized(tool.description, ''),
          parameters: tool.parameters || [],
          output_schema: tool.output_schema || {},
        })
      }
    }
  }
  return list.filter(item => item.provider_id && (item.tool_name || item.tool_name === null))
}

export function groupSelectableTools(tools) {
  return TOOL_GROUPS
    .map(group => ({
      ...group,
      tools: (Array.isArray(tools) ? tools : [])
        .filter(tool => tool.provider_type === group.type),
    }))
    .filter(group => group.tools.length)
}
