// Console plugin install APIs + public marketplace lookups.
import axios from 'axios'
import difyClient from '../../../shared/http/difyClient.js'

const MARKETPLACE_API = 'https://marketplace.dify.ai/api/v1'

export function installPluginsFromMarketplace(pluginUniqueIdentifiers) {
  return difyClient.post('/workspaces/current/plugin/install/marketplace', {
    plugin_unique_identifiers: pluginUniqueIdentifiers,
  })
}

export function fetchPluginInstallTask(taskId) {
  return difyClient.get(`/workspaces/current/plugin/tasks/${encodeURIComponent(taskId)}`)
}

export function fetchInstalledPlugins({ page = 1, page_size = 100 } = {}) {
  return difyClient.get('/workspaces/current/plugin/list', {
    params: { page, page_size },
  })
}

export function uninstallPlugin(pluginInstallationId) {
  return difyClient.post('/workspaces/current/plugin/uninstall', {
    plugin_installation_id: pluginInstallationId,
  })
}

/** Uninstall plugin and optionally delete AI studio sessions linked to it. */
export function uninstallToolPluginWithSessions({
  plugin_installation_id,
  delete_studio_sessions = true,
  plugin_unique_identifier,
} = {}) {
  const payload = {
    plugin_installation_id,
    delete_studio_sessions,
  }
  if (plugin_unique_identifier)
    payload.plugin_unique_identifier = plugin_unique_identifier
  return difyClient.post('/workspaces/current/tool-plugin/uninstall', payload)
}

export function fetchStudioSessionsByInstallation({
  installation_id,
  plugin_unique_identifier,
} = {}) {
  return difyClient.get('/workspaces/current/tool-plugin/sessions/by-installation', {
    params: {
      installation_id: installation_id || undefined,
      plugin_unique_identifier: plugin_unique_identifier || undefined,
    },
  })
}

function localizeMarketplaceText(value, fallback = '') {
  if (!value) return fallback
  if (typeof value === 'string') return value
  return value.zh_Hans || value.en_US || fallback
}

/** Same as Dify web getPluginIconInMarketplace — icons are not inline fields. */
export function getMarketplacePluginIconUrl(plugin) {
  const org = plugin?.org || ''
  const name = plugin?.name || ''
  if (!org || !name) return ''
  if (plugin?.type === 'bundle')
    return `${MARKETPLACE_API}/bundles/${encodeURIComponent(org)}/${encodeURIComponent(name)}/icon`
  return `${MARKETPLACE_API}/plugins/${encodeURIComponent(org)}/${encodeURIComponent(name)}/icon`
}

function normalizeMarketplacePlugin(plugin, org, name) {
  if (!plugin) return null
  const resolvedOrg = plugin.org || org || ''
  const resolvedName = plugin.name || name || ''
  const normalized = {
    plugin_id: plugin.plugin_id || `${resolvedOrg}/${resolvedName}`,
    name: resolvedName,
    org: resolvedOrg,
    type: plugin.type || 'plugin',
    label: localizeMarketplaceText(plugin.label || plugin.labels, resolvedName),
    brief: localizeMarketplaceText(plugin.brief, '') || localizeMarketplaceText(plugin.description, ''),
    description: localizeMarketplaceText(plugin.description, '') || localizeMarketplaceText(plugin.brief, ''),
    category: plugin.category || '',
    latest_package_identifier: plugin.latest_package_identifier,
    latest_version: plugin.latest_version,
    install_count: plugin.install_count,
    verified: !!plugin.verified,
  }
  normalized.icon = getMarketplacePluginIconUrl(normalized)
  return normalized
}

/** Public marketplace plugin detail (no Console auth). */
export async function fetchMarketplacePlugin(org, name) {
  const { data } = await axios.get(`${MARKETPLACE_API}/plugins/${encodeURIComponent(org)}/${encodeURIComponent(name)}`, {
    timeout: 30000,
  })
  const plugin = data?.data?.plugin || data?.plugin || data?.data || null
  const normalized = normalizeMarketplacePlugin(plugin, org, name)
  if (!normalized?.latest_package_identifier)
    throw new Error(`未找到插件 ${org}/${name}`)
  return normalized
}

/** Mainstream model plugins shown under marketplace. */
export const SUGGESTED_MODEL_PLUGINS = [
  { org: 'langgenius', name: 'openai', title: 'OpenAI' },
  { org: 'langgenius', name: 'anthropic', title: 'Anthropic' },
  { org: 'langgenius', name: 'gemini', title: 'Gemini' },
  { org: 'langgenius', name: 'deepseek', title: 'DeepSeek' },
  { org: 'langgenius', name: 'tongyi', title: '通义千问' },
  { org: 'langgenius', name: 'x', title: 'xAI' },
  { org: 'langgenius', name: 'zhipuai', title: '智谱 AI' },
  { org: 'langgenius', name: 'moonshot', title: 'Moonshot' },
  { org: 'langgenius', name: 'siliconflow', title: 'SiliconFlow' },
  { org: 'langgenius', name: 'ollama', title: 'Ollama' },
  { org: 'langgenius', name: 'azure_openai', title: 'Azure OpenAI' },
  { org: 'langgenius', name: 'openai_api_compatible', title: 'OpenAI-API-compatible' },
  { org: 'langgenius', name: 'volcengine_maas', title: '火山方舟' },
  { org: 'langgenius', name: 'huggingface_hub', title: 'Hugging Face' },
]

/** Common tool plugins for workflow Tool nodes. */
export const SUGGESTED_TOOL_PLUGINS = [
  { org: 'langgenius', name: 'google', title: 'Google 搜索' },
  { org: 'langgenius', name: 'duckduckgo', title: 'DuckDuckGo' },
  { org: 'langgenius', name: 'tavily', title: 'Tavily 搜索' },
  { org: 'langgenius', name: 'jina', title: 'Jina' },
  { org: 'langgenius', name: 'firecrawl', title: 'Firecrawl' },
  { org: 'langgenius', name: 'searxng', title: 'SearXNG' },
  { org: 'langgenius', name: 'wikipedia', title: 'Wikipedia' },
  { org: 'langgenius', name: 'github', title: 'GitHub' },
  { org: 'langgenius', name: 'notion', title: 'Notion' },
  { org: 'langgenius', name: 'slack', title: 'Slack' },
  { org: 'langgenius', name: 'email', title: 'Email' },
  { org: 'langgenius', name: 'feishu', title: '飞书' },
  { org: 'langgenius', name: 'dingtalk', title: '钉钉' },
  { org: 'langgenius', name: 'gaode', title: '高德地图' },
  { org: 'langgenius', name: 'youtube', title: 'YouTube' },
  { org: 'langgenius', name: 'chart', title: 'Chart' },
  { org: 'langgenius', name: 'dalle', title: 'DALL·E' },
  { org: 'langgenius', name: 'stability', title: 'Stability' },
]

/**
 * Search marketplace plugins by category.
 * Returns { plugins, total, page, page_size, has_more } like Dify web marketplace.
 */
export async function searchMarketplacePlugins({
  category = 'tool',
  query = '',
  page = 1,
  page_size = 40,
} = {}) {
  const { data } = await axios.post(
    `${MARKETPLACE_API}/plugins/search/advanced`,
    {
      page,
      page_size,
      query,
      category: category === 'all' ? '' : category,
      sort_by: 'install_count',
      sort_order: 'DESC',
    },
    { timeout: 30000 },
  )
  const payload = data?.data || data || {}
  const plugins = (payload.plugins || payload.bundles || [])
    .map(plugin => normalizeMarketplacePlugin(plugin))
    .filter(item => item?.latest_package_identifier)
    .map(item => ({
      ...item,
      key: `${item.org}/${item.name}`,
    }))
  const total = Number(payload.total ?? plugins.length) || 0
  return {
    plugins,
    total,
    page,
    page_size,
    has_more: page * page_size < total,
  }
}

export function unwrapPluginList(payload) {
  if (Array.isArray(payload?.plugins)) return payload.plugins
  if (Array.isArray(payload?.data?.plugins)) return payload.data.plugins
  if (Array.isArray(payload?.data)) return payload.data
  if (Array.isArray(payload)) return payload
  return []
}

/** Match installed plugin row by tool/model plugin id. */
export function findInstallationForPluginId(plugins, pluginId) {
  const target = String(pluginId || '')
  if (!target) return null
  return (plugins || []).find((plugin) => {
    const id = plugin.plugin_id || plugin.pluginId || ''
    const unique = plugin.plugin_unique_identifier || ''
    const name = plugin.name || ''
    return id === target
      || unique.startsWith(`${target}:`)
      || unique === target
      || `${plugin.org || ''}/${name}` === target
      || name === target
  }) || null
}
