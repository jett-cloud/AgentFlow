/**
 * Dify Tool node tool_parameters / tool_configurations value shape.
 * Contrasts web VarKindType: variable | constant | mixed.
 */

export const ToolVarKind = {
  variable: 'variable',
  constant: 'constant',
  mixed: 'mixed',
}

const FILE_PARAM_TYPES = new Set(['file', 'files', 'system-files', 'array[file]', 'arrayfile'])

export function cloneToolValue(value) {
  if (Array.isArray(value))
    return value.map(item => cloneToolValue(item))
  if (value && typeof value === 'object')
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, cloneToolValue(item)]))
  return value
}

export function normalizeToolInputType(type, prefer = ToolVarKind.mixed) {
  return [ToolVarKind.variable, ToolVarKind.constant, ToolVarKind.mixed].includes(type)
    ? type
    : prefer
}

/**
 * Normalize a stored tool parameter into `{ type, value }`.
 * Plain strings from older drafts become mixed text.
 */
export function toToolParamInput(raw, { prefer = ToolVarKind.mixed } = {}) {
  if (raw && typeof raw === 'object' && !Array.isArray(raw) && 'type' in raw) {
    const { type, value, ...rest } = raw
    return {
      ...cloneToolValue(rest),
      type: normalizeToolInputType(type, prefer),
      value: value === undefined || value === null ? '' : cloneToolValue(value),
    }
  }
  if (raw === undefined || raw === null || raw === '')
    return { type: prefer, value: '' }
  return { type: prefer, value: cloneToolValue(raw) }
}

export function normalizeToolParameter(raw, { prefer = ToolVarKind.mixed } = {}) {
  if (raw && typeof raw === 'object' && !Array.isArray(raw) && 'type' in raw) {
    return {
      ...cloneToolValue(raw),
      type: normalizeToolInputType(raw.type, prefer),
      value: cloneToolValue(raw.value),
    }
  }
  return toToolParamInput(raw, { prefer })
}

export function normalizeToolParameters(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw))
    return {}
  return Object.fromEntries(
    Object.entries(raw).map(([name, value]) => [name, normalizeToolParameter(value)]),
  )
}

/** Render selectors using the same reference syntax as the variable picker. */
export function toolParamDisplayValue(raw) {
  const normalized = toToolParamInput(raw)
  if (normalized.type === ToolVarKind.variable) {
    if (Array.isArray(normalized.value))
      return `{{#${normalized.value.join('.')}#}}`
    return normalized.value == null ? '' : String(normalized.value)
  }
  return normalized.value == null ? '' : String(normalized.value)
}

function envelopeExtras(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw))
    return {}
  const { type: _type, value: _value, ...rest } = raw
  return cloneToolValue(rest)
}

export function setToolParamValue(params, name, text) {
  const next = { ...(params || {}) }
  const previous = toToolParamInput(next[name])
  const extras = envelopeExtras(next[name])
  const reference = typeof text === 'string' && text.match(/^\{\{#([^\s.#{}]+(?:\.[^\s.#{}]+)+)#\}\}$/)
  if (reference) {
    next[name] = { ...extras, type: ToolVarKind.variable, value: reference[1].split('.') }
    return next
  }
  const hasReference = typeof text === 'string' && /\{\{#[^\s.#{}]+(?:\.[^\s.#{}]+)+#\}\}/.test(text)
  const type = previous.type === ToolVarKind.constant && !hasReference ? ToolVarKind.constant : ToolVarKind.mixed
  next[name] = { ...extras, type, value: text == null ? '' : text }
  return next
}

export function setToolParamEnvelope(params, name, envelope) {
  return {
    ...(params || {}),
    [name]: normalizeToolParameter(envelope),
  }
}

export function isToolFileParam(param = {}) {
  return FILE_PARAM_TYPES.has(String(param.type || '').toLowerCase())
}

export function isSecretToolParam(param = {}) {
  const type = String(param.type || '').toLowerCase()
  return type === 'secret-input' || type === 'secret' || param.form === 'secret'
}

export function isToolFileVariable(variable = {}) {
  return ['file', 'arrayFile', 'array[file]'].includes(variable.type)
}

export function isToolVariableSelector(value) {
  return Array.isArray(value)
    && value.length >= 2
    && value.every(part => typeof part === 'string' && part.trim() !== '')
}

export function isLlmToolParam(param = {}) {
  return !param.form || param.form === 'llm'
}

export function isGraphonConstantValue(value, { allowNull = false } = {}) {
  if (value === null)
    return allowNull
  const kind = typeof value
  if (kind === 'string' || kind === 'boolean')
    return true
  if (kind === 'number')
    return Number.isFinite(value)
  if (Array.isArray(value))
    return value.every(item => isGraphonConstantValue(item, { allowNull: true }))
  if (value && kind === 'object')
    return Object.values(value).every(item => isGraphonConstantValue(item, { allowNull: true }))
  return false
}

export function isGraphonConfigurationValue(value) {
  if (Array.isArray(value))
    return false
  return isGraphonConstantValue(value)
}

export function isValidToolParameterEnvelope(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || !('type' in raw))
    return false
  const type = normalizeToolInputType(raw.type, '')
  if (!type)
    return false
  if (type === ToolVarKind.variable)
    return isToolVariableSelector(raw.value)
  if (type === ToolVarKind.mixed)
    return typeof raw.value === 'string'
  return isGraphonConstantValue(raw.value)
}

export function isFilledNonFileToolParam(raw) {
  if (!isValidToolParameterEnvelope(raw))
    return false
  if (raw.type === ToolVarKind.mixed)
    return raw.value.trim() !== ''
  if (raw.type === ToolVarKind.variable)
    return true
  return raw.value !== undefined && raw.value !== null
}

function seedFromSchema(param) {
  if (isToolFileParam(param))
    return { type: ToolVarKind.variable, value: [] }
  if (isSecretToolParam(param))
    return { type: ToolVarKind.mixed, value: '' }
  const type = String(param.type || '').toLowerCase()
  if (param.form && param.form !== 'llm') {
    if (type === 'boolean')
      return { type: ToolVarKind.constant, value: param.default === undefined ? false : Boolean(param.default) }
    if (type === 'number' || type === 'integer') {
      const numeric = Number(param.default)
      return { type: ToolVarKind.constant, value: Number.isFinite(numeric) ? numeric : 0 }
    }
    if (param.default !== undefined && param.default !== null)
      return { type: ToolVarKind.constant, value: cloneToolValue(param.default) }
    return { type: ToolVarKind.constant, value: '' }
  }
  if (param.default !== undefined && param.default !== null && !isSecretToolParam(param))
    return { type: ToolVarKind.mixed, value: String(param.default) }
  return { type: ToolVarKind.mixed, value: '' }
}

export function buildEmptyToolParameters(parameterSchemas = []) {
  const params = {}
  for (const param of parameterSchemas) {
    const name = param?.name
    if (!name)
      continue
    params[name] = seedFromSchema(param)
  }
  return params
}

export function buildEmptyToolConfigurations(parameterSchemas = []) {
  const configs = {}
  for (const param of parameterSchemas) {
    const name = param?.name
    if (!name || isLlmToolParam(param) || isSecretToolParam(param))
      continue
    configs[name] = cloneToolValue(seedFromSchema(param).value)
  }
  return configs
}

export function syncToolFormConfiguration(configurations, param, envelope) {
  if (!param?.name || isLlmToolParam(param))
    return { ...(configurations || {}) }
  const next = { ...(configurations || {}) }
  const value = normalizeToolParameter(envelope).value
  if (isSecretToolParam(param) && (value === '' || value == null)) {
    delete next[param.name]
    return next
  }
  next[param.name] = cloneToolValue(value)
  return next
}

export function getToolParamEditorKind(param = {}) {
  const type = String(param.type || '').toLowerCase()
  if (isToolFileParam(param))
    return 'file'
  if (param.form === 'llm')
    return 'llm'
  if (type === 'boolean')
    return 'boolean'
  if (type === 'number' || type === 'integer')
    return 'number'
  if (type === 'select')
    return 'select'
  if (isSecretToolParam(param))
    return 'secret'
  return 'text'
}
