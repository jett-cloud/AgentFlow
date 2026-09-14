// src/views/copilot/components/workflow/node/http-request/useHttpRequestConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import {
  applyHttpRequestField,
  convertHttpBody,
  createHttpBodyItem,
  isHttpFileVariable,
  isKeyedHttpBodyType,
  isTextHttpBodyType,
  normalizeHttpBodyItem,
  normalizeHttpRequestData,
  setHttpErrorStrategy,
  updateHttpDefaultValue,
} from './httpRequest.js'

function bodyToEditorText(body) {
  const data = Array.isArray(body?.data) ? body.data : []
  if (typeof body?.data === 'string')
    return body.data
  return data.filter(item => item?.type !== 'file').map(item => item?.value || '').join('\n')
}

export function useHttpRequestConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)
  const normalized = computed(() => normalizeHttpRequestData(nodeData.value))

  const emitData = data => emit('update:nodeData', data)
  const setField = (field, value) => emitData(applyHttpRequestField(nodeData.value, field, value))

  const method = computed({
    get: () => (nodeData.value?.method || 'get').toLowerCase(),
    set: val => setField('method', String(val || 'get').toLowerCase()),
  })
  const url = computed({
    get: () => nodeData.value?.url || '',
    set: val => setField('url', val),
  })
  const headers = computed({
    get: () => nodeData.value?.headers || '',
    set: val => setField('headers', val),
  })
  const params = computed({ get: () => nodeData.value?.params || '', set: val => setField('params', val) })
  const sslVerify = computed({ get: () => nodeData.value?.ssl_verify !== false, set: val => setField('ssl_verify', !!val) })
  const timeout = computed({
    get: () => ({ ...normalized.value.timeout }),
    set: val => setField('timeout', val),
  })
  const setTimeoutField = (field, value) => { timeout.value = { ...timeout.value, [field]: value } }
  const timeoutConnect = computed({ get: () => timeout.value.connect ?? 0, set: value => setTimeoutField('connect', value) })
  const timeoutRead = computed({ get: () => timeout.value.read ?? 0, set: value => setTimeoutField('read', value) })
  const timeoutWrite = computed({ get: () => timeout.value.write ?? 0, set: value => setTimeoutField('write', value) })
  const retryConfig = computed({ get: () => nodeData.value?.retry_config || { retry_enabled: true, max_retries: 3, retry_interval: 100 }, set: val => setField('retry_config', val) })
  const retryEnabled = computed({
    get: () => retryConfig.value.retry_enabled !== false,
    set: retry_enabled => { retryConfig.value = { ...retryConfig.value, retry_enabled } },
  })
  const authorization = computed({
    get: () => normalized.value.authorization,
    set: val => setField('authorization', val),
  })
  const setAuthorization = patch => {
    authorization.value = {
      ...authorization.value,
      ...patch,
      config: patch.config === null ? null : { ...(authorization.value.config || {}), ...(patch.config || {}) },
    }
  }
  const authorizationType = computed({
    get: () => authorization.value.type,
    set: (type) => setAuthorization(type === 'api-key'
      ? { type, config: { type: 'basic', api_key: '', header: '' } }
      : { type: 'no-auth', config: null }),
  })
  const authorizationConfigType = computed({
    get: () => authorization.value.config?.type || 'basic',
    set: type => setAuthorization({ config: { type } }),
  })
  const authorizationApiKey = computed({
    get: () => authorization.value.config?.api_key || '',
    set: api_key => setAuthorization({ config: { api_key } }),
  })
  const authorizationHeader = computed({
    get: () => authorization.value.config?.header || '',
    set: header => setAuthorization({ config: { header } }),
  })
  const variables = computed(() => Array.isArray(nodeData.value?.variables) ? nodeData.value.variables : [])

  const setBody = body => setField('body', body)

  const bodyType = computed({
    get: () => normalized.value.body.type || 'none',
    set: val => setBody(convertHttpBody(normalized.value.body, val)),
  })

  const body = computed({
    get: () => bodyToEditorText(normalized.value.body),
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
        }
        catch {
          type = 'raw-text'
        }
      }
      const current = normalized.value.body
      setBody({
        ...current,
        type,
        data: type === 'none' ? [] : [normalizeHttpBodyItem({ ...(current.data?.[0] || {}), type: 'text', value: text })],
      })
    },
  })

  const bodyItems = computed({
    get: () => (isKeyedHttpBodyType(bodyType.value) ? normalized.value.body.data : []),
    set: data => setBody({ ...normalized.value.body, data: Array.isArray(data) ? data.map(item => normalizeHttpBodyItem(item)) : [] }),
  })

  const updateBodyItem = (index, patch) => {
    const items = bodyItems.value.map((item, itemIndex) => (
      itemIndex === index ? normalizeHttpBodyItem({ ...item, ...patch }) : item
    ))
    bodyItems.value = items
  }

  const addBodyItem = (itemType = 'text') => {
    bodyItems.value = [...bodyItems.value, createHttpBodyItem(itemType)]
  }

  const removeBodyItem = index => {
    bodyItems.value = bodyItems.value.filter((_, itemIndex) => itemIndex !== index)
  }

  const binaryFile = computed({
    get: () => normalized.value.body.data.find(item => item.type === 'file')?.file || [],
    set: file => setBody({
      ...normalized.value.body,
      type: 'binary',
      data: [normalizeHttpBodyItem({
        ...(normalized.value.body.data.find(item => item.type === 'file') || createHttpBodyItem('file')),
        type: 'file',
        file: Array.isArray(file) ? file : [],
      })],
    }),
  })

  function handleErrorStrategyUpdate(strategy) {
    emitData(setHttpErrorStrategy(nodeData.value, strategy))
  }

  function handleDefaultValueUpdate({ key, value }) {
    emitData(updateHttpDefaultValue(nodeData.value, key, value))
  }

  return {
    readOnly,
    method,
    url,
    headers,
    body,
    bodyType,
    bodyItems,
    binaryFile,
    isKeyedHttpBodyType,
    isTextHttpBodyType,
    isHttpFileVariable,
    params,
    sslVerify,
    timeout,
    timeoutConnect,
    timeoutRead,
    timeoutWrite,
    retryConfig,
    retryEnabled,
    authorization,
    authorizationType,
    authorizationConfigType,
    authorizationApiKey,
    authorizationHeader,
    variables,
    addBodyItem,
    removeBodyItem,
    updateBodyItem,
    handleErrorStrategyUpdate,
    handleDefaultValueUpdate,
  }
}
