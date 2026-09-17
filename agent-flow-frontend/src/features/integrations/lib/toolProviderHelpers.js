import { resolveConsoleAssetUrl } from './modelProviderHelpers.js'

export function localizeToolText(value, fallback = '') {
  if (!value) return fallback
  if (typeof value === 'string') return value
  return value.zh_Hans || value.en_US || fallback
}

/** Resolve builtin/plugin tool provider icon URL or emoji content. */
export function toolProviderIcon(provider) {
  const icon = provider?.icon ?? provider?.icon_small ?? provider?.raw?.icon ?? provider?.raw?.icon_small
  if (!icon) {
    return { type: 'letter', value: (provider?.label || provider?.provider || '?').slice(0, 1) }
  }
  if (typeof icon === 'string') {
    const url = resolveConsoleAssetUrl(icon)
    if (url.startsWith('http') || url.startsWith('/'))
      return { type: 'url', value: url }
    return { type: 'emoji', value: icon, background: '#eff4ff' }
  }
  if (typeof icon === 'object') {
    if (icon.content && (icon.background || icon.content.length <= 4)) {
      return {
        type: 'emoji',
        value: icon.content,
        background: icon.background || '#eff4ff',
      }
    }
    const url = resolveConsoleAssetUrl(localizeToolText(icon, ''))
    if (url)
      return { type: 'url', value: url }
  }
  return { type: 'letter', value: (provider?.label || '?').slice(0, 1) }
}

export function marketplaceIconUrl(plugin) {
  const icon = plugin?.icon
  if (typeof icon === 'string' && (icon.startsWith('http') || icon.startsWith('/') || icon.startsWith('data:')))
    return icon
  const org = plugin?.org
  const name = plugin?.name
  if (!org || !name) return ''
  const kind = plugin?.type === 'bundle' ? 'bundles' : 'plugins'
  return `https://marketplace.dify.ai/api/v1/${kind}/${encodeURIComponent(org)}/${encodeURIComponent(name)}/icon`
}
