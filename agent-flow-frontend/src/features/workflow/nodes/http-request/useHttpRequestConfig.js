// src/views/copilot/components/workflow/node/http-request/useHttpRequestConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { normalizeHttpRequestData } from './httpRequest.js'

function normalizeBody(body) {
  if (body && typeof body === 'object' && !Array.isArray(body) && body.type)
    return body
  if (typeof body === 'string') {
    if (!body.trim())
      return { type: 'none', data: '' }
    try {
      JSON.parse(body)
      return { type: 'json', data: body }
    } catch {
      return { type: 'raw-text', data: body }
    }
  }
  return { type: 'none', data: '' }
}

function bodyToEditorText(body) {
  const normalized = normalizeBody(body)
  if (normalized.type === 'none') return ''
  if (typeof normalized.data === 'string') return normalized.data
  if (Array.isArray(normalized.data)) {
    return normalized.data.map(item => `${item.key || ''}: ${item.value || ''}`).join('\n')
  }
  try {
    return JSON.stringify(normalized.data, null, 2)
  } catch {
    return String(normalized.data ?? '')
  }
}

export function useHttpRequestConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)

  const method = computed({
    get: () => (nodeData.value?.method || 'get').toLowerCase(),
    set: (val) => emit('update:nodeData', { ...nodeData.value, method: String(val || 'get').toLowerCase() }),
  })

  const setField = (field, value) => emit('update:nodeData', { ...normalizeHttpRequestData(nodeData.value), [field]: value })

  const url = computed({
    get: () => nodeData.value?.url || '',
    set: (val) => setField('url', val),
  })

  const headers = computed({
    get: () => nodeData.value?.headers || '',
    set: (val) => setField('headers', val),
  })

  const params = computed({ get: () => nodeData.value?.params || '', set: val => setField('params', val) })
  const sslVerify = computed({ get: () => nodeData.value?.ssl_verify !== false, set: val => setField('ssl_verify', !!val) })
  const timeout = computed({ get: () => nodeData.value?.timeout || { max_connect_timeout: 0, max_read_timeout: 0, max_write_timeout: 0 }, set: val => setField('timeout', val) })
  const retryConfig = computed({ get: () => nodeData.value?.retry_config || { retry_enabled: true, max_retries: 3, retry_interval: 100 }, set: val => setField('retry_config', val) })
  const authorization = computed({ get: () => nodeData.value?.authorization || { type: 'no-auth', config: null }, set: val => setField('authorization', val) })
  const variables = computed(() => Array.isArray(nodeData.value?.variables) ? nodeData.value.variables : [])

  const bodyType = computed({
    get: () => normalizeBody(nodeData.value?.body).type || 'none',
    set: (val) => {
      const current = bodyToEditorText(nodeData.value?.body)
      emit('update:nodeData', {
        ...nodeData.value,
        body: {
          type: val,
          data: val === 'none' ? '' : current,
        },
      })
    },
  })

  const body = computed({
    get: () => bodyToEditorText(nodeData.value?.body),
    set: (val) => {
      const text = String(val ?? '')
      let type = bodyType.value
      if (type === 'none' && text.trim())
        type = 'json'
      if (!text.trim())
        type = 'none'
      else if (type === 'json') {
        try {
          JSON.parse(text)
        } catch {
          type = 'raw-text'
        }
      }
      emit('update:nodeData', {
        ...nodeData.value,
        body: { type, data: type === 'none' ? '' : text },
      })
    },
  })

  return {
    readOnly,
    method,
    url,
    headers,
    body,
    bodyType,
    params,
    sslVerify,
    timeout,
    retryConfig,
    authorization,
    variables,
  }
}
