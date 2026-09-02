import { resolveConsoleAssetUrl } from './modelProviderHelpers.js'

/** Resolve dataset icon_info ({ icon_type, icon, icon_background, icon_url }) to url | emoji | letter. */
export function datasetIcon(iconInfo, fallbackLabel = '知') {
  if (!iconInfo) {
    return { type: 'letter', value: fallbackLabel.slice(0, 1) }
  }
  if (typeof iconInfo === 'string') {
    const url = resolveConsoleAssetUrl(iconInfo)
    if (url.startsWith('http') || url.startsWith('/') || url.startsWith('data:'))
      return { type: 'url', value: url }
    return { type: 'emoji', value: iconInfo, background: '#eff4ff' }
  }
  if (typeof iconInfo === 'object') {
    const iconUrl = iconInfo.icon_url || (iconInfo.icon_type === 'image' ? iconInfo.icon : '')
    if (iconUrl) {
      const url = resolveConsoleAssetUrl(iconUrl)
      if (url.startsWith('http') || url.startsWith('/') || url.startsWith('data:'))
        return { type: 'url', value: url }
    }
    if (iconInfo.icon) {
      return {
        type: 'emoji',
        value: iconInfo.icon,
        background: iconInfo.icon_background || '#eff4ff',
      }
    }
  }
  return { type: 'letter', value: fallbackLabel.slice(0, 1) }
}
