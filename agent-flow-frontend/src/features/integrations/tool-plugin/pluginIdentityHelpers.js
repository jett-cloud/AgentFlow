/**
 * Plugin / tool / author identity names.
 * - Author / plugin: ToolProviderID segments → [a-z0-9_-]+
 * - Tool: Python module / identity.name → [a-z0-9_]+ only (no hyphen)
 */

export const PLUGIN_IDENTITY_NAME_RE = /^[a-z0-9_-]+$/
export const TOOL_IDENTITY_NAME_RE = /^[a-z0-9_]+$/

export const PLUGIN_IDENTITY_NAME_HINT = '仅支持小写字母、数字、下划线和连字符'
export const TOOL_IDENTITY_NAME_HINT = '仅支持小写字母、数字和下划线（不能用连字符）'

export const AUTHOR_FIELD_PLACEHOLDER = '例：ghy'
export const PLUGIN_FIELD_PLACEHOLDER = '例：remove-bg 或 weather_plugin'
export const TOOL_FIELD_PLACEHOLDER = '例：remove_image_background'

export const AUTHOR_FIELD_HELP = '发布者 ID，小写字母 / 数字 / _ / -'
export const PLUGIN_FIELD_HELP = '整个插件包的名字（一个插件可含多个工具）'
export const TOOL_FIELD_HELP = '单个工具的英文标识，用下划线，不要用连字符'

/**
 * Sanitize one org/plugin/provider segment / identity field.
 * Invalid chars become "-" so "Remove.bg" → "remove-bg" (`.` never retained).
 * Used for file-path / legacy data normalization — not for live input.
 * @param {unknown} value
 * @returns {string}
 */
export function sanitizePluginIdSegment(value) {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/_{2,}/g, '_')
    .replace(/^[-_]+|[-_]+$/g, '')
}

/**
 * @param {unknown} value
 * @returns {string}
 */
export function sanitizePluginIdentityName(value) {
  return sanitizePluginIdSegment(value)
}

/**
 * Used for file-path / legacy data normalization — not for live input.
 * @param {unknown} value
 * @returns {string}
 */
export function sanitizeToolIdentityName(value) {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/_{2,}/g, '_')
    .replace(/^_+|_+$/g, '')
}

/**
 * @param {unknown} value
 * @returns {boolean}
 */
export function isValidPluginIdentityName(value) {
  const text = String(value ?? '').trim()
  return Boolean(text) && PLUGIN_IDENTITY_NAME_RE.test(text)
}

/**
 * @param {unknown} value
 * @returns {boolean}
 */
export function isValidToolIdentityName(value) {
  const text = String(value ?? '').trim()
  return Boolean(text) && TOOL_IDENTITY_NAME_RE.test(text)
}

/**
 * Field error for author / plugin identity inputs.
 * @param {unknown} value
 * @param {{ required?: boolean }} [opts]
 * @returns {string}
 */
export function pluginIdentityFieldError(value, opts = {}) {
  const text = String(value ?? '').trim()
  if (!text)
    return opts.required ? '不能为空' : ''
  if (!PLUGIN_IDENTITY_NAME_RE.test(text))
    return PLUGIN_IDENTITY_NAME_HINT
  return ''
}

/**
 * @param {unknown} value
 * @param {{ required?: boolean }} [opts]
 * @returns {string}
 */
export function toolIdentityFieldError(value, opts = {}) {
  const text = String(value ?? '').trim()
  if (!text)
    return opts.required ? '不能为空' : ''
  if (!TOOL_IDENTITY_NAME_RE.test(text))
    return TOOL_IDENTITY_NAME_HINT
  return ''
}
