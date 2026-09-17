export const HTTP_REQUEST_DEFAULTS = Object.freeze({
  variables: [], method: 'get', url: '',
  authorization: { type: 'no-auth', config: null }, headers: '', params: '',
  body: { type: 'none', data: [] }, ssl_verify: true,
  timeout: { max_connect_timeout: 0, max_read_timeout: 0, max_write_timeout: 0 },
  retry_config: { retry_enabled: true, max_retries: 3, retry_interval: 100 },
})

const METHODS = new Set(['get', 'post', 'head', 'patch', 'put', 'delete', 'options'])
const BODY_TYPES = new Set(['none', 'form-data', 'x-www-form-urlencoded', 'raw-text', 'json', 'binary'])
const AUTH_CONFIG_TYPES = new Set(['basic', 'bearer', 'custom'])
const KEYED_BODY_TYPES = new Set(['form-data', 'x-www-form-urlencoded'])
const TEXT_BODY_TYPES = new Set(['json', 'raw-text'])
const HTTP_DEFAULT_OUTPUTS = [
  { key: 'body', type: 'string', value: '' },
  { key: 'status_code', type: 'number', value: 0 },
  { key: 'headers', type: 'object', value: '{}' },
  { key: 'files', type: 'array[file]', value: '[]' },
]

export function isKeyedHttpBodyType(type) {
  return KEYED_BODY_TYPES.has(type)
}

export function isTextHttpBodyType(type) {
  return TEXT_BODY_TYPES.has(type)
}

export function isHttpFileVariable(variable = {}) {
  return ['file', 'arrayFile', 'array[file]'].includes(variable.type)
}

export function createHttpBodyItem(itemType = 'text') {
  if (itemType === 'file')
    return { type: 'file', key: '', file: [] }
  return { type: 'text', key: '', value: '' }
}

export function normalizeHttpBodyItem(item) {
  if (!item || typeof item !== 'object' || Array.isArray(item))
    return createHttpBodyItem('text')
  if (item.type === 'file') {
    return {
      ...item,
      type: 'file',
      key: String(item.key || ''),
      file: Array.isArray(item.file) ? item.file.map(String) : [],
    }
  }
  return {
    ...item,
    type: 'text',
    key: String(item.key ?? ''),
    value: String(item.value ?? ''),
  }
}

function normalizeBodyData(data) {
  if (Array.isArray(data))
    return data.map(item => normalizeHttpBodyItem(item))
  if (typeof data === 'string' && data)
    return [normalizeHttpBodyItem({ type: 'text', value: data })]
  return []
}

function normalizeBody(body) {
  if (body && typeof body === 'object' && !Array.isArray(body)) {
    return {
      ...body,
      type: BODY_TYPES.has(body.type) ? body.type : 'none',
      data: normalizeBodyData(body.data),
    }
  }
  if (typeof body === 'string') {
    if (!body.trim())
      return { type: 'none', data: [] }
    try {
      JSON.parse(body)
      return { type: 'json', data: [normalizeHttpBodyItem({ type: 'text', value: body })] }
    }
    catch {
      return { type: 'raw-text', data: [normalizeHttpBodyItem({ type: 'text', value: body })] }
    }
  }
  return { type: 'none', data: [] }
}

function normalizeAuthorization(authorization) {
  if (!authorization || typeof authorization !== 'object' || Array.isArray(authorization) || authorization.type !== 'api-key') {
    return {
      ...(authorization && typeof authorization === 'object' && !Array.isArray(authorization) ? authorization : {}),
      type: 'no-auth',
      config: null,
    }
  }

  const config = authorization.config && typeof authorization.config === 'object' && !Array.isArray(authorization.config)
    ? authorization.config
    : {}
  return {
    ...authorization,
    type: 'api-key',
    config: {
      ...config,
      type: AUTH_CONFIG_TYPES.has(config.type) ? config.type : 'basic',
      api_key: String(config.api_key || ''),
      header: String(config.header || ''),
    },
  }
}

export function convertHttpBody(body, nextType) {
  const current = normalizeBody(body)
  const type = BODY_TYPES.has(nextType) ? nextType : 'none'
  if (type === 'none')
    return { ...current, type, data: [] }
  if (type === 'binary') {
    const existing = current.data.find(item => item.type === 'file') || createHttpBodyItem('file')
    return { ...current, type, data: [normalizeHttpBodyItem({ ...existing, type: 'file' })] }
  }
  if (isKeyedHttpBodyType(type)) {
    const data = current.data.length ? current.data.map(item => normalizeHttpBodyItem(item)) : [createHttpBodyItem('text')]
    return { ...current, type, data }
  }
  const value = current.data
    .filter(item => item.type !== 'file')
    .map(item => item.value || '')
    .join('\n')
  return { ...current, type, data: [normalizeHttpBodyItem({ type: 'text', key: '', value })] }
}

export function normalizeHttpRequestData(data = {}) {
  const method = String(data.method || 'get').toLowerCase()
  return {
    ...data, variables: Array.isArray(data.variables) ? data.variables.map(v => ({ ...v })) : [],
    method: METHODS.has(method) ? method : 'get',
    url: String(data.url || ''), headers: data.headers ?? '', params: data.params ?? '',
    authorization: normalizeAuthorization(data.authorization),
    body: normalizeBody(data.body),
    ssl_verify: data.ssl_verify !== false,
    timeout: { ...HTTP_REQUEST_DEFAULTS.timeout, ...(data.timeout || {}) },
    retry_config: { ...HTTP_REQUEST_DEFAULTS.retry_config, ...(data.retry_config || {}) },
  }
}

export function applyHttpRequestField(data, field, value) {
  return { ...normalizeHttpRequestData(data), [field]: value }
}

export function setHttpErrorStrategy(data, strategy) {
  const normalized = normalizeHttpRequestData(data)
  if (!strategy || strategy === 'none') {
    const { error_strategy: _strategy, default_value: _defaultValue, ...rest } = normalized
    return rest
  }
  const next = { ...normalized, error_strategy: strategy }
  if (strategy === 'default-value') {
    const current = Array.isArray(normalized.default_value) ? normalized.default_value : []
    const byKey = new Map(current.map(item => [item?.key, item]))
    next.default_value = HTTP_DEFAULT_OUTPUTS.map(item => ({
      ...item,
      ...(byKey.get(item.key) || {}),
      key: item.key,
      type: item.type,
    }))
  }
  else {
    delete next.default_value
  }
  return next
}

export function updateHttpDefaultValue(data, key, value) {
  const normalized = setHttpErrorStrategy(data, 'default-value')
  return {
    ...normalized,
    default_value: (normalized.default_value || []).map(item => (
      item.key === key ? { ...item, value } : item
    )),
  }
}

export function buildHttpRequestRunInputs(inputs = {}, variableNames = []) {
  const allowed = new Set(variableNames)
  return Object.fromEntries(Object.entries(inputs || {}).filter(([key]) => allowed.has(key)))
}
