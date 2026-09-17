/** Mirror Dify FixedModelProvider in model-provider-page/index.tsx */
export const FIXED_MODEL_PROVIDERS = [
  'langgenius/openai/openai',
  'langgenius/anthropic/anthropic',
]

/** Mirror Dify providerToPluginId: langgenius/openai/openai -> langgenius/openai */
export function providerToPluginId(providerKey) {
  const key = String(providerKey || '')
  const lastSlash = key.lastIndexOf('/')
  return lastSlash > 0 ? key.slice(0, lastSlash) : ''
}

export const ConfigurationMethodEnum = {
  predefinedModel: 'predefined-model',
  customizableModel: 'customizable-model',
  fetchFromRemote: 'fetch-from-remote',
}

export function i18nText(value, fallback = '') {
  if (!value) return fallback
  if (typeof value === 'string') return value
  return value.zh_Hans || value.en_US || fallback
}

export function providerLabel(provider) {
  return i18nText(provider?.label, provider?.provider || '')
}

/**
 * Icon URLs from API may be absolute (`CONSOLE_API_URL + /console/api/...`).
 * Rewrite to same-origin `/console/api/...` so Vite proxy + session cookies work.
 */
export function resolveConsoleAssetUrl(url) {
  const raw = String(url || '').trim()
  if (!raw) return ''
  if (raw.startsWith('/')) return raw
  try {
    const parsed = new URL(raw)
    if (parsed.pathname.includes('/console/api/'))
      return `${parsed.pathname}${parsed.search}`
  }
  catch {
    // keep original
  }
  return raw
}

export function providerIconUrl(provider) {
  return resolveConsoleAssetUrl(i18nText(provider?.icon_small, ''))
}

/** Same configured rule as Dify model-provider-page/index.tsx */
export function isProviderConfigured(provider) {
  const custom = provider?.custom_configuration
  const system = provider?.system_configuration
  if (custom?.status === 'active') return true
  if (system?.enabled === true) {
    const quotas = system.quota_configurations || []
    return quotas.some(item => item.quota_type === system.current_quota_type)
  }
  return false
}

export function modelTypeFormat(modelType) {
  if (modelType === 'text-embedding') return 'TEXT EMBEDDING'
  return String(modelType || '').toUpperCase()
}

export function sortConfiguredProviders(list) {
  return [...list].sort((a, b) => {
    const ai = FIXED_MODEL_PROVIDERS.indexOf(a.provider)
    const bi = FIXED_MODEL_PROVIDERS.indexOf(b.provider)
    if (ai >= 0 && bi >= 0) return ai - bi
    if (ai >= 0) return -1
    if (bi >= 0) return 1
    return 0
  })
}

export function filterProvidersBySearch(list, searchText) {
  const keyword = String(searchText || '').trim().toLowerCase()
  if (!keyword) return list
  return list.filter((provider) => {
    const label = providerLabel(provider).toLowerCase()
    const id = String(provider.provider || '').toLowerCase()
    const labelValues = typeof provider.label === 'object'
      ? Object.values(provider.label).map(v => String(v).toLowerCase())
      : []
    return id.includes(keyword)
      || label.includes(keyword)
      || labelValues.some(text => text.includes(keyword))
  })
}

export function normalizeProviderModels(payload) {
  const data = payload?.data || payload
  if (!Array.isArray(data)) return []
  return data.map(item => ({
    model: item.model || '',
    label: i18nText(item.label, item.model || ''),
    model_type: item.model_type || '',
    status: item.status || 'unknown',
    features: item.features || [],
    fetch_from: item.fetch_from || '',
    mode: item.model_properties?.mode || '',
  })).filter(item => item.model)
}
