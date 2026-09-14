export const HUMAN_INPUT_DEFAULTS = Object.freeze({
  delivery_methods: [], user_actions: [], form_content: '', inputs: [], timeout: 3, timeout_unit: 'day',
})

const LEGACY_DELIVERY_TYPES = { web_app: 'webapp', webapp: 'webapp', email: 'email' }
const LEGACY_FIELD_TYPES = { text: 'paragraph', files: 'file-list' }
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const FILE_TYPES = new Set(['image', 'document', 'audio', 'video', 'custom'])
const FILE_UPLOAD_METHODS = new Set(['local_file', 'remote_url'])

export const HUMAN_INPUT_FIELD_TYPES = Object.freeze(['paragraph', 'select', 'file', 'file-list'])
export const HUMAN_INPUT_BUTTON_STYLES = Object.freeze(['primary', 'default', 'accent', 'ghost'])
export const HUMAN_INPUT_ACTION_ID_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/
export const HUMAN_INPUT_DEFAULT_EMAIL_BODY = '请处理以下人工输入任务：\n\n{{#url#}}'

export function createDeliveryMethodId() {
  if (typeof globalThis.crypto?.randomUUID === 'function')
    return globalThis.crypto.randomUUID()

  const bytes = new Uint8Array(16)
  if (typeof globalThis.crypto?.getRandomValues === 'function')
    globalThis.crypto.getRandomValues(bytes)
  else
    bytes.forEach((_, index) => { bytes[index] = Math.floor(Math.random() * 256) })
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function normalizeDeliveryMethodId(id) {
  const normalized = String(id || '')
  return UUID_PATTERN.test(normalized) ? normalized : createDeliveryMethodId()
}

function normalizeStringList(value) {
  return Array.isArray(value) ? value.map(item => String(item)) : []
}

function normalizeStringSource(source = {}) {
  return {
    type: source.type === 'variable' ? 'variable' : 'constant',
    selector: normalizeStringList(source.selector),
    value: String(source.value ?? ''),
  }
}

function normalizeStringListSource(source = {}) {
  return {
    type: source.type === 'variable' ? 'variable' : 'constant',
    selector: normalizeStringList(source.selector),
    value: normalizeStringList(source.value),
  }
}

function normalizeAllowedFileTypes(value) {
  const normalized = normalizeStringList(value).filter(item => FILE_TYPES.has(item))
  return normalized.length ? [...new Set(normalized)] : ['image']
}

function normalizeUploadMethods(value) {
  const normalized = normalizeStringList(value).filter(item => FILE_UPLOAD_METHODS.has(item))
  return normalized.length ? [...new Set(normalized)] : ['local_file', 'remote_url']
}

function normalizeNonNegativeInteger(value, fallback) {
  if (value == null || value === '')
    return fallback
  const numeric = Number(value)
  return Number.isFinite(numeric) ? Math.trunc(numeric) : fallback
}

function createFileInput(type, outputVariableName) {
  return {
    type,
    output_variable_name: outputVariableName,
    allowed_file_extensions: [],
    allowed_file_types: ['image'],
    allowed_file_upload_methods: ['local_file', 'remote_url'],
    ...(type === 'file-list' ? { number_limits: 5 } : {}),
  }
}

export function createHumanInputField(type = 'paragraph', outputVariableName = '') {
  const name = String(outputVariableName || '')
  if (type === 'select') {
    return {
      type,
      output_variable_name: name,
      option_source: { type: 'constant', selector: [], value: [] },
    }
  }
  if (type === 'file' || type === 'file-list')
    return createFileInput(type, name)
  return {
    type: 'paragraph',
    output_variable_name: name,
    default: { type: 'constant', selector: [], value: '' },
  }
}

export function normalizeHumanInputField(field = {}) {
  const candidate = LEGACY_FIELD_TYPES[field.type] || field.type
  const type = HUMAN_INPUT_FIELD_TYPES.includes(candidate) ? candidate : 'paragraph'
  const outputVariableName = String(field.output_variable_name || '')
  if (type === 'paragraph') {
    return {
      type,
      output_variable_name: outputVariableName,
      default: normalizeStringSource(field.default),
    }
  }
  if (type === 'select') {
    return {
      type,
      output_variable_name: outputVariableName,
      option_source: normalizeStringListSource(field.option_source),
    }
  }
  return {
    type,
    output_variable_name: outputVariableName,
    allowed_file_extensions: normalizeStringList(field.allowed_file_extensions),
    allowed_file_types: normalizeAllowedFileTypes(field.allowed_file_types),
    allowed_file_upload_methods: normalizeUploadMethods(field.allowed_file_upload_methods),
    ...(type === 'file-list'
      ? { number_limits: normalizeNonNegativeInteger(field.number_limits, 5) }
      : {}),
  }
}

function normalizeEmailRecipients(items) {
  return (Array.isArray(items) ? items : []).flatMap((item) => {
    if (item?.type === 'member') {
      const referenceId = item.reference_id || item.user_id
      if (referenceId)
        return [{ type: 'member', reference_id: String(referenceId) }]
    }
    if (item?.type === 'external' && String(item.email || '').trim())
      return [{ type: 'external', email: String(item.email).trim() }]
    return []
  })
}

export function normalizeHumanInputEmailConfig(config = {}) {
  const recipients = config?.recipients || {}
  return {
    recipients: {
      include_bound_group: recipients.include_bound_group === true || recipients.whole_workspace === true,
      items: normalizeEmailRecipients(recipients.items),
    },
    subject: String(config?.subject || ''),
    body: String(config?.body == null ? HUMAN_INPUT_DEFAULT_EMAIL_BODY : config.body),
    debug_mode: config?.debug_mode === true,
  }
}

export function externalEmailsToRecipients(value) {
  const emails = String(value || '').split(/[\s,;]+/).map(item => item.trim()).filter(Boolean)
  return [...new Set(emails)].map(email => ({ type: 'external', email }))
}

export function isHumanInputActionIdValid(id) {
  const value = String(id || '')
  return value.length >= 1 && value.length <= 20 && HUMAN_INPUT_ACTION_ID_PATTERN.test(value)
}

function isSelectorValid(selector) {
  return Array.isArray(selector)
    && selector.length >= 2
    && selector.every(part => typeof part === 'string' && part.trim())
}

function isStringSourceValid(source) {
  if (!source || !['constant', 'variable'].includes(source.type))
    return false
  if (source.type === 'variable')
    return isSelectorValid(source.selector)
  return typeof source.value === 'string'
}

function isStringListSourceValid(source) {
  if (!source || !['constant', 'variable'].includes(source.type))
    return false
  if (source.type === 'variable')
    return isSelectorValid(source.selector)
  return Array.isArray(source.value) && source.value.every(item => typeof item === 'string')
}

export function isHumanInputFieldValid(field = {}) {
  if (!HUMAN_INPUT_FIELD_TYPES.includes(field.type) || !String(field.output_variable_name || '').trim())
    return false
  if (field.type === 'paragraph')
    return isStringSourceValid(field.default)
  if (field.type === 'select')
    return isStringListSourceValid(field.option_source)

  if (!Array.isArray(field.allowed_file_extensions)
    || !Array.isArray(field.allowed_file_types)
    || !field.allowed_file_types.every(type => FILE_TYPES.has(type))
    || !Array.isArray(field.allowed_file_upload_methods)
    || !field.allowed_file_upload_methods.every(method => FILE_UPLOAD_METHODS.has(method)))
    return false
  if (field.allowed_file_types.includes('custom') && !field.allowed_file_extensions.length)
    return false
  return field.type !== 'file-list'
    || (Number.isInteger(field.number_limits) && field.number_limits >= 0)
}

export function mergeHumanInputPatch(current = {}, pending = null, partial = {}) {
  return normalizeHumanInputData({ ...(pending || current), ...partial })
}

export function applyHumanInputDraftValue(raw, existing = [], stored = '', propose) {
  const proposed = propose(raw, existing)
  if (proposed.error)
    return { value: stored, display: String(raw), error: proposed.error }
  return { value: proposed.value, display: proposed.value, error: '' }
}

export function applyHumanInputActionIdInput(raw, existingIds = [], storedId = '') {
  const result = applyHumanInputDraftValue(raw, existingIds, storedId, proposeHumanInputActionId)
  return { id: result.value, display: result.display, error: result.error }
}

export function applyHumanInputFieldNameInput(raw, existingNames = [], storedName = '') {
  const result = applyHumanInputDraftValue(raw, existingNames, storedName, proposeHumanInputFieldName)
  return { value: result.value, display: result.display, error: result.error }
}

export function humanInputDraftKey(id, index) {
  return String(id || '') || `__index_${index}`
}

export function pruneHumanInputDrafts(drafts = {}, keys = []) {
  const allowed = new Set(keys)
  return Object.fromEntries(Object.entries(drafts).filter(([key]) => allowed.has(key)))
}

export function humanInputActionIdErrorMessage(error) {
  if (error === 'empty action id')
    return '分支 ID 不能为空'
  if (error === 'action id longer than 20')
    return '分支 ID 最长 20 个字符'
  if (error === 'duplicate action id')
    return '分支 ID 不能重复'
  return error ? '仅允许字母、数字、下划线，且不能以数字开头' : ''
}

export function humanInputFieldNameErrorMessage(error) {
  if (error === 'empty output variable name')
    return '输出变量名不能为空'
  if (String(error || '').includes('reserved'))
    return '不能使用保留输出名'
  if (String(error || '').includes('duplicate'))
    return '输出变量名不能重复'
  return error ? '仅允许字母、数字、下划线，且不能以数字开头' : ''
}

export function humanInputPreviewActionClass(style) {
  const value = HUMAN_INPUT_BUTTON_STYLES.includes(style) ? style : 'default'
  return `action-style-${value}`
}

export function proposeHumanInputFieldName(raw, existingNames = []) {
  const value = String(raw ?? '')
  if (!value.trim())
    return { value: '', error: 'empty output variable name' }
  const converted = value.replace(/\s+/g, '_')
  if (HUMAN_INPUT_RESERVED_OUTPUTS.includes(converted))
    return { value: converted, error: `reserved output name: ${converted}` }
  if (!HUMAN_INPUT_ACTION_ID_PATTERN.test(converted))
    return { value, error: 'illegal output variable name' }
  if (existingNames.includes(converted))
    return { value: converted, error: 'duplicate output name' }
  return { value: converted, error: '' }
}

export function normalizeHumanInputData(data = {}) {
  const rawDelivery = Array.isArray(data.delivery_methods) ? data.delivery_methods : []
  const deliveryMethods = rawDelivery.map((item) => {
    if (typeof item === 'string') {
      const type = LEGACY_DELIVERY_TYPES[item] || item
      return { id: createDeliveryMethodId(), type, enabled: true, ...(type === 'email' ? { config: normalizeHumanInputEmailConfig() } : {}) }
    }
    const type = LEGACY_DELIVERY_TYPES[item.type] || item.type
    return {
      ...item,
      id: normalizeDeliveryMethodId(item.id),
      type,
      enabled: item.enabled !== false,
      ...(type === 'email' ? { config: normalizeHumanInputEmailConfig(item.config) } : {}),
    }
  })
  const normalized = {
    ...data,
    delivery_methods: deliveryMethods,
    user_actions: Array.isArray(data.user_actions) ? data.user_actions.map(item => ({
      ...item,
      id: String(item.id || ''),
      title: String(item.title || ''),
      button_style: HUMAN_INPUT_BUTTON_STYLES.includes(item.button_style) ? item.button_style : 'default',
    })) : [],
    form_content: String(data.form_content ?? data.prompt ?? ''),
    inputs: Array.isArray(data.inputs) ? data.inputs.map(normalizeHumanInputField) : [],
    timeout: Number(data.timeout) || 3,
    timeout_unit: data.timeout_unit === 'hour' ? 'hour' : 'day',
  }
  delete normalized.prompt
  delete normalized.form_inputs
  return normalized
}

export const HUMAN_INPUT_RESERVED_OUTPUTS = Object.freeze(['__action_id', '__action_value', '__rendered_content'])

export function formatHumanInputOutputToken(name) {
  return `{{#$output.${name}#}}`
}

export function renameHumanInputOutputToken(content, oldName, newName) {
  const source = String(content || '')
  if (!oldName || oldName === newName)
    return source
  return source.split(formatHumanInputOutputToken(oldName)).join(formatHumanInputOutputToken(newName))
}

export function removeHumanInputOutputToken(content, name) {
  if (!name)
    return String(content || '')
  return String(content || '').split(formatHumanInputOutputToken(name)).join('')
}

export function getHumanInputFieldValidationErrors(inputs = []) {
  const errors = []
  const seen = new Set()
  for (const field of Array.isArray(inputs) ? inputs : []) {
    const name = String(field?.output_variable_name || '').trim()
    if (!name)
      errors.push('empty output variable name')
    else if (HUMAN_INPUT_RESERVED_OUTPUTS.includes(name))
      errors.push(`reserved output name: ${name}`)
    else if (seen.has(name))
      errors.push(`duplicate output name: ${name}`)
    else
      seen.add(name)

    if (name && !isHumanInputFieldValid({ ...field, output_variable_name: name })) {
      if (field?.type === 'paragraph' && field.default?.type === 'variable' && !isSelectorValid(field.default.selector))
        errors.push(`missing variable selector for ${name}`)
      else if (field?.type === 'select' && field.option_source?.type === 'variable' && !isSelectorValid(field.option_source.selector))
        errors.push(`missing variable selector for ${name}`)
      else if (field?.type === 'select' && !isStringListSourceValid(field.option_source))
        errors.push(`invalid select options for ${name}`)
      else if ((field?.type === 'file' || field?.type === 'file-list') && field.allowed_file_types?.includes('custom') && !field.allowed_file_extensions?.length)
        errors.push(`custom file type requires extensions for ${name}`)
      else if (field?.type === 'file-list' && !(Number.isInteger(field.number_limits) && field.number_limits >= 0))
        errors.push(`invalid number_limits for ${name}`)
      else
        errors.push(`invalid field config for ${name}`)
    }
  }
  return errors
}

export function proposeHumanInputActionId(raw, existingIds = []) {
  const value = String(raw ?? '')
  if (!value.trim())
    return { value: '', error: 'empty action id' }
  const converted = value.replace(/\s+/g, '_')
  if (converted.length > 20)
    return { value, error: 'action id longer than 20' }
  if (!HUMAN_INPUT_ACTION_ID_PATTERN.test(converted))
    return { value, error: 'illegal action id' }
  if (existingIds.includes(converted))
    return { value, error: 'duplicate action id' }
  return { value: converted, error: '' }
}

export function getHumanInputBranches(data = {}) {
  const actions = (Array.isArray(data.user_actions) ? data.user_actions : []).map(item => ({
    id: String(item.id || ''),
    name: String(item.title || item.name || item.id || ''),
    style: HUMAN_INPUT_BUTTON_STYLES.includes(item.button_style) ? item.button_style : 'default',
  }))
  return [...actions, { id: '__timeout', name: 'Timeout (超时)', style: 'timeout', isTimeout: true }]
}

export function splitHumanInputFormContent(content = '') {
  const source = String(content || '')
  const tokenPattern = /\{\{#\$output\.([A-Za-z_][A-Za-z0-9_]*)#\}\}/g
  const segments = []
  let cursor = 0
  for (const match of source.matchAll(tokenPattern)) {
    if (match.index > cursor)
      segments.push({ type: 'text', text: source.slice(cursor, match.index) })
    segments.push({ type: 'field', name: match[1] })
    cursor = match.index + match[0].length
  }
  if (cursor < source.length)
    segments.push({ type: 'text', text: source.slice(cursor) })
  return segments
}

export function isHumanInputDeliveryValid(method = {}) {
  if (!method.enabled) return true
  if (method.type !== 'email') return true
  const config = normalizeHumanInputEmailConfig(method.config)
  return Boolean(config.subject.trim()
    && config.body.includes('{{#url#}}')
    && (config.recipients.include_bound_group || config.recipients.items.length))
}
