import { localizeToolText } from './toolProviderHelpers.js'

function providerInitials(provider) {
  const name = String(provider.name || provider.server_identifier || 'MCP').trim()
  const parts = name
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .split(/[\s_-]+/)
    .filter(Boolean)
  if (parts.length > 1)
    return parts.slice(0, 2).map(part => [...part][0]).join('').toUpperCase()
  return [...(parts[0] || 'MCP')].slice(0, 2).join('').toUpperCase()
}

export function resolveRemoteMcpIcon(provider = {}) {
  return { type: 'letters', value: providerInitials(provider), variant: 'initials' }
}

export function normalizeRemoteMcpProvider(item) {
  const value = item?.data ?? item ?? {}
  const provider = {
    ...value,
    id: value.id || value.server_identifier,
    name: localizeToolText(value.label, value.name || value.server_identifier || 'Remote MCP'),
    tools: Array.isArray(value.tools) ? value.tools : [],
    authed: Boolean(value.is_team_authorization || value.authed),
  }
  return { ...provider, iconMeta: resolveRemoteMcpIcon(provider) }
}

export function mcpToolsLocation() {
  return { path: '/integrations', query: { tab: 'mcp' } }
}

function searchableText(value) {
  if (typeof value === 'string')
    return value
  if (value && typeof value === 'object')
    return Object.values(value).filter(item => typeof item === 'string').join(' ')
  return ''
}

export function filterRemoteMcpTools(tools, query) {
  const normalizedQuery = String(query || '').trim().toLowerCase()
  if (!normalizedQuery)
    return tools
  return tools.filter((tool) => {
    const haystack = [tool.name, tool.tool_name, searchableText(tool.label), searchableText(tool.description)]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return haystack.includes(normalizedQuery)
  })
}
