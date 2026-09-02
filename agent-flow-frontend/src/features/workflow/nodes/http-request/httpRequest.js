export const HTTP_REQUEST_DEFAULTS = Object.freeze({
  variables: [], method: 'get', url: '',
  authorization: { type: 'no-auth', config: null }, headers: '', params: '',
  body: { type: 'none', data: [] }, ssl_verify: true,
  timeout: { max_connect_timeout: 0, max_read_timeout: 0, max_write_timeout: 0 },
  retry_config: { retry_enabled: true, max_retries: 3, retry_interval: 100 },
})

const METHODS = new Set(['get', 'post', 'head', 'patch', 'put', 'delete'])
const BODY_TYPES = new Set(['none', 'form-data', 'x-www-form-urlencoded', 'raw-text', 'json', 'binary'])

export function normalizeHttpRequestData(data = {}) {
  const method = String(data.method || 'get').toLowerCase()
  const body = data.body && typeof data.body === 'object' && !Array.isArray(data.body) ? data.body : {}
  return {
    ...data, variables: Array.isArray(data.variables) ? data.variables.map(v => ({ ...v })) : [],
    method: METHODS.has(method) ? method : 'get',
    url: String(data.url || ''), headers: data.headers ?? '', params: data.params ?? '',
    authorization: data.authorization ? { ...data.authorization } : { ...HTTP_REQUEST_DEFAULTS.authorization },
    body: { type: BODY_TYPES.has(body.type) ? body.type : 'none', data: body.data ?? [] },
    ssl_verify: data.ssl_verify !== false,
    timeout: { ...HTTP_REQUEST_DEFAULTS.timeout, ...(data.timeout || {}) },
    retry_config: { ...HTTP_REQUEST_DEFAULTS.retry_config, ...(data.retry_config || {}) },
  }
}

export function buildHttpRequestRunInputs(inputs = {}, variableNames = []) {
  const allowed = new Set(variableNames)
  return Object.fromEntries(Object.entries(inputs || {}).filter(([key]) => allowed.has(key)))
}
