export const PARAMETER_TYPES = new Set([
  'string',
  'number',
  'boolean',
  'select',
  'array[string]',
  'array[number]',
  'array[object]',
  'array[boolean]',
])

export const PARAMETER_EXTRACTOR_DEFAULTS = {
  query: [],
  model: {
    provider: '',
    name: '',
    mode: 'chat',
    completion_params: { temperature: 0.7 },
  },
  reasoning_mode: 'prompt',
  vision: { enabled: false },
}

export function isParameterExtractorInput(variable) {
  return variable?.type === 'string'
}

export function isParameterNameValid(name) {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(String(name || ''))
}

/** Normalize legacy parameter-extractor drafts while preserving unknown Dify fields. */
export function normalizeParameterExtractorData(data = {}) {
  const query = Array.isArray(data.query)
    ? [...data.query]
    : (Array.isArray(data.query_variable_selector) ? [...data.query_variable_selector] : [])
  const normalized = {
    ...data,
    query,
    model: {
      ...PARAMETER_EXTRACTOR_DEFAULTS.model,
      ...(data.model || {}),
      completion_params: {
        ...PARAMETER_EXTRACTOR_DEFAULTS.model.completion_params,
        ...(data.model?.completion_params || {}),
      },
    },
    reasoning_mode: ['prompt', 'function_call'].includes(data.reasoning_mode)
      ? data.reasoning_mode
      : 'prompt',
    vision: {
      ...PARAMETER_EXTRACTOR_DEFAULTS.vision,
      ...(data.vision || {}),
    },
  }
  if (Array.isArray(data.parameters))
    normalized.parameters = data.parameters.map(item => ({ ...item }))
  delete normalized.query_variable_selector
  return normalized
}

export function hasInvalidParameterDefinitions(parameters) {
  if (!Array.isArray(parameters) || parameters.length === 0)
    return true
  const names = parameters.map(item => String(item?.name || '').trim())
  if (new Set(names).size !== names.length)
    return true
  return parameters.some(item => (
    !isParameterNameValid(item?.name)
    || !PARAMETER_TYPES.has(item?.type)
    || !String(item?.description || '').trim()
    || (item?.type === 'select' && (!Array.isArray(item.options) || item.options.length === 0))
  ))
}

