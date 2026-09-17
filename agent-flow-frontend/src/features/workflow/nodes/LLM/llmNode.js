const EMPTY_SCHEMA = {
  type: 'object',
  properties: {},
  required: [],
  additionalProperties: false,
}

export const LLM_DEFAULTS = {
  model: {
    provider: '',
    name: '',
    mode: 'chat',
    completion_params: { temperature: 0.7 },
  },
  prompt_template: [{ role: 'system', text: '' }],
  context: { enabled: false, variable_selector: [] },
  vision: { enabled: false },
}

function normalizePromptTemplate(data) {
  if (Array.isArray(data.prompt_template)) {
    return data.prompt_template.map(item => typeof item === 'string'
      ? { role: 'user', text: item }
      : { ...item })
  }
  if (data.prompt_template && typeof data.prompt_template === 'object')
    return { ...data.prompt_template }
  if (typeof data.prompt_template === 'string')
    return [{ role: 'user', text: data.prompt_template }]
  if (typeof data.prompt === 'string' && data.prompt)
    return [{ role: 'user', text: data.prompt }]
  return LLM_DEFAULTS.prompt_template.map(item => ({ ...item }))
}

function normalizeStructuredOutput(value) {
  if (!value || typeof value !== 'object')
    return value
  let schema = value.schema
  if (typeof schema === 'string') {
    try {
      schema = JSON.parse(schema)
    }
    catch {
      schema = { ...EMPTY_SCHEMA }
    }
  }
  return {
    ...value,
    schema: schema && typeof schema === 'object' ? schema : { ...EMPTY_SCHEMA },
  }
}

/** Normalize legacy LLM drafts to Dify's wire fields without dropping unknown fields. */
export function normalizeLLMNodeData(data = {}) {
  const normalized = {
    ...data,
    model: {
      ...LLM_DEFAULTS.model,
      ...(data.model || {}),
      completion_params: {
        ...LLM_DEFAULTS.model.completion_params,
        ...(data.model?.completion_params || {}),
      },
    },
    prompt_template: normalizePromptTemplate(data),
    context: {
      ...LLM_DEFAULTS.context,
      ...(data.context || {}),
      variable_selector: Array.isArray(data.context?.variable_selector)
        ? [...data.context.variable_selector]
        : [],
    },
    vision: {
      ...LLM_DEFAULTS.vision,
      ...(data.vision || {}),
    },
  }

  if (normalized.vision.configs && typeof normalized.vision.configs === 'object') {
    const configs = normalized.vision.configs
    const detail = ['low', 'high', 'auto'].includes(configs.detail) ? configs.detail : 'high'
    normalized.vision.configs = {
      ...configs,
      detail,
      variable_selector: Array.isArray(configs.variable_selector) ? [...configs.variable_selector] : [],
    }
  }

  if (data.structured_output !== undefined)
    normalized.structured_output = normalizeStructuredOutput(data.structured_output)
  delete normalized.prompt
  return normalized
}

export function isLLMPromptEmpty(data = {}) {
  const prompts = Array.isArray(data.prompt_template)
    ? data.prompt_template
    : [data.prompt_template]
  return !prompts.some((item) => {
    if (!item)
      return false
    if (typeof item === 'string')
      return Boolean(item.trim())
    const content = item.edition_type === 'jinja2' ? item.jinja2_text : item.text
    return Boolean(String(content || '').trim())
  })
}

export function isLLMVisionFileVariable(variable = {}) {
  const type = variable.type || variable.value_type
  if (type === 'file' || type === 'arrayFile' || type === 'array[file]')
    return true
  const selector = variable.selector || []
  return selector[0] === 'sys' && selector[1] === 'files'
}

export function hasInvalidLLMJinjaMapping(data = {}) {
  const prompts = Array.isArray(data.prompt_template)
    ? data.prompt_template
    : [data.prompt_template]
  const usesJinja = prompts.some(item => item?.edition_type === 'jinja2')
  if (!usesJinja)
    return false
  return (data.prompt_config?.jinja2_variables || []).some(item => (
    !String(item?.variable || '').trim()
    || !Array.isArray(item?.value_selector)
    || item.value_selector.length < 2
  ))
}

