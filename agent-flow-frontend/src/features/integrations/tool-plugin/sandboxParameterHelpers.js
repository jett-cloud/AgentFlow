/**
 * Tool sandbox parameter widgets + file payload helpers.
 * Contrasts Dify form schemas: file/files upload, options → select.
 */

export const SANDBOX_WIDGET = {
  file: 'file',
  files: 'files',
  select: 'select',
  number: 'number',
  boolean: 'boolean',
  secret: 'secret',
  textarea: 'textarea',
  text: 'text',
}

/**
 * Build the server contract for publishing without a live tool invocation.
 * Test credentials and parameters must never cross this boundary.
 * @param {{ expectedRevision: number, toolName: string }} input
 */
export function buildDirectPublishPayload({ expectedRevision, toolName }) {
  return {
    expected_revision: expectedRevision,
    tool_name: toolName,
    publish_mode: 'direct',
    parameters: {},
    credentials: {},
  }
}

const FILE_TYPES = new Set(['file'])
const FILES_TYPES = new Set(['files', 'system-files', 'system_files', 'array[file]'])
const NUMBER_TYPES = new Set(['number', 'integer', 'float', 'number-input'])
const BOOLEAN_TYPES = new Set(['boolean', 'bool', 'checkbox'])
const SECRET_TYPES = new Set(['secret-input', 'secret', 'password'])

/**
 * @param {unknown} value
 * @returns {string}
 */
export function localizedParameterText(value) {
  if (!value || typeof value !== 'object')
    return value == null ? '' : String(value)
  return value.zh_Hans || value.en_US || Object.values(value)[0] || ''
}

/**
 * @param {object} parameter
 * @returns {Array<{ value: string, label: string }>}
 */
export function normalizeParameterOptions(parameter) {
  const options = Array.isArray(parameter?.options) ? parameter.options : []
  return options.map((option) => {
    if (option == null)
      return null
    if (typeof option !== 'object') {
      const value = String(option)
      return { value, label: value }
    }
    if (option.value === undefined || option.value === null)
      return null
    const value = String(option.value)
    return {
      value,
      label: localizedParameterText(option.label) || value,
    }
  }).filter(Boolean)
}

/**
 * @param {object} parameter
 * @returns {string}
 */
export function parameterWidgetKind(parameter) {
  const type = String(parameter?.type || 'string').toLowerCase().trim()
  if (FILE_TYPES.has(type))
    return SANDBOX_WIDGET.file
  if (FILES_TYPES.has(type))
    return SANDBOX_WIDGET.files
  if (normalizeParameterOptions(parameter).length)
    return SANDBOX_WIDGET.select
  if (NUMBER_TYPES.has(type))
    return SANDBOX_WIDGET.number
  if (BOOLEAN_TYPES.has(type))
    return SANDBOX_WIDGET.boolean
  if (SECRET_TYPES.has(type))
    return SANDBOX_WIDGET.secret
  if (type === 'text' || type === 'textarea' || type === 'string' || type === 'paragraph')
    return type === 'string' || type === 'text' ? SANDBOX_WIDGET.text : SANDBOX_WIDGET.textarea
  return SANDBOX_WIDGET.textarea
}

/**
 * @param {string} name
 * @param {string} [mime]
 * @returns {'image'|'document'|'audio'|'video'|'custom'}
 */
export function guessSandboxFileType(name = '', mime = '') {
  const lowerMime = String(mime || '').toLowerCase()
  const lowerName = String(name || '').toLowerCase()
  if (lowerMime.startsWith('image/') || /\.(png|jpe?g|gif|webp|bmp|svg)$/.test(lowerName))
    return 'image'
  if (lowerMime.startsWith('audio/') || /\.(mp3|wav|ogg|m4a|flac)$/.test(lowerName))
    return 'audio'
  if (lowerMime.startsWith('video/') || /\.(mp4|webm|mov|avi)$/.test(lowerName))
    return 'video'
  if (lowerMime || lowerName)
    return 'document'
  return 'custom'
}

/**
 * @param {{
 *   uploadFileId: string,
 *   transferMethod?: string,
 *   url?: string,
 *   name?: string,
 *   mimeType?: string,
 *   size?: number,
 * }} input
 */
export function buildSandboxFilePayload(input) {
  const uploadFileId = String(input?.uploadFileId || '').trim()
  if (!uploadFileId)
    return null
  const transferMethod = input.transferMethod === 'remote_url' ? 'remote_url' : 'local_file'
  return {
    type: guessSandboxFileType(input.name, input.mimeType),
    transfer_method: transferMethod,
    url: input.url || '',
    upload_file_id: uploadFileId,
    name: input.name || '',
    size: input.size ?? 0,
    mime_type: input.mimeType || '',
  }
}

/**
 * @param {unknown} value
 * @returns {boolean}
 */
export function isSandboxFilePayloadReady(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    return false
  return Boolean(String(value.upload_file_id || '').trim())
}

/**
 * @param {unknown} value
 * @returns {boolean}
 */
export function isSandboxFilesPayloadReady(value) {
  return Array.isArray(value) && value.length > 0 && value.every(isSandboxFilePayloadReady)
}

/**
 * Strip UI-only fields before sending to test API.
 * @param {object} file
 */
export function toTestFileParameterValue(file) {
  if (!isSandboxFilePayloadReady(file))
    return null
  return {
    type: file.type || 'custom',
    transfer_method: file.transfer_method || 'local_file',
    url: file.url || '',
    upload_file_id: file.upload_file_id,
  }
}

/**
 * @param {object} parameter
 * @param {unknown} rawValue stored tool_parameters[name].value
 */
export function toTestParameterValue(parameter, rawValue) {
  const kind = parameterWidgetKind(parameter)
  if (kind === SANDBOX_WIDGET.file)
    return toTestFileParameterValue(rawValue)
  if (kind === SANDBOX_WIDGET.files) {
    const list = Array.isArray(rawValue) ? rawValue : []
    return list.map(toTestFileParameterValue).filter(Boolean)
  }
  if (kind === SANDBOX_WIDGET.boolean) {
    if (typeof rawValue === 'boolean')
      return rawValue
    if (rawValue === 'true' || rawValue === '1')
      return true
    if (rawValue === 'false' || rawValue === '0')
      return false
    return Boolean(rawValue)
  }
  if (kind === SANDBOX_WIDGET.number) {
    if (rawValue === '' || rawValue == null)
      return rawValue
    const num = Number(rawValue)
    return Number.isFinite(num) ? num : rawValue
  }
  return rawValue ?? ''
}

/**
 * @param {object[]} parametersSchema
 * @param {Record<string, { value?: unknown }>} toolParameters
 * @returns {string[]} missing required parameter names
 */
export function missingRequiredSandboxParameters(parametersSchema, toolParameters) {
  const missing = []
  for (const parameter of parametersSchema || []) {
    if (!parameter?.name || !parameter.required)
      continue
    const kind = parameterWidgetKind(parameter)
    const value = toolParameters?.[parameter.name]?.value
    if (kind === SANDBOX_WIDGET.file) {
      if (!isSandboxFilePayloadReady(value))
        missing.push(parameter.name)
      continue
    }
    if (kind === SANDBOX_WIDGET.files) {
      if (!isSandboxFilesPayloadReady(value))
        missing.push(parameter.name)
      continue
    }
    if (kind === SANDBOX_WIDGET.boolean)
      continue
    if (value == null || String(value).trim() === '')
      missing.push(parameter.name)
  }
  return missing
}

/**
 * Initial value for a schema parameter.
 * @param {object} parameter
 */
export function defaultSandboxParameterValue(parameter) {
  const kind = parameterWidgetKind(parameter)
  if (kind === SANDBOX_WIDGET.file)
    return null
  if (kind === SANDBOX_WIDGET.files)
    return []
  if (kind === SANDBOX_WIDGET.boolean) {
    if (typeof parameter?.default === 'boolean')
      return parameter.default
    if (parameter?.default === 'true' || parameter?.default === true)
      return true
    return false
  }
  if (parameter?.default !== undefined && parameter?.default !== null)
    return parameter.default
  const options = normalizeParameterOptions(parameter)
  if (options.length)
    return options[0].value
  return ''
}

/**
 * Build parameters dict for testToolPlugin.
 * @param {object[]} parametersSchema
 * @param {Record<string, { value?: unknown }>} toolParameters
 */
export function buildSandboxTestParameters(parametersSchema, toolParameters) {
  /** @type {Record<string, unknown>} */
  const out = {}
  for (const parameter of parametersSchema || []) {
    if (!parameter?.name)
      continue
    const raw = toolParameters?.[parameter.name]?.value
    const kind = parameterWidgetKind(parameter)
    if (kind === SANDBOX_WIDGET.file) {
      const file = toTestFileParameterValue(raw)
      if (file)
        out[parameter.name] = file
      continue
    }
    if (kind === SANDBOX_WIDGET.files) {
      const files = toTestParameterValue(parameter, raw)
      if (Array.isArray(files) && files.length)
        out[parameter.name] = files
      continue
    }
    if (raw === '' || raw == null)
      continue
    out[parameter.name] = toTestParameterValue(parameter, raw)
  }
  return out
}
