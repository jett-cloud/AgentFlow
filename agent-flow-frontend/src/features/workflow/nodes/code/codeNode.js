export const CODE_LANGUAGES = ['python3', 'javascript']

export const CODE_OUTPUT_TYPE_OPTIONS = [
  { label: 'String (字符串)', value: 'string' },
  { label: 'Number (数字)', value: 'number' },
  { label: 'Boolean (布尔值)', value: 'boolean' },
  { label: 'Object (对象)', value: 'object' },
  { label: 'Array[String] (字符串数组)', value: 'array[string]' },
  { label: 'Array[Number] (数字数组)', value: 'array[number]' },
  { label: 'Array[Boolean] (布尔数组)', value: 'array[boolean]' },
  { label: 'Array[Object] (对象数组)', value: 'array[object]' },
]

export const CODE_OUTPUT_TYPES = new Set(CODE_OUTPUT_TYPE_OPTIONS.map(item => item.value))

export const CODE_INPUT_TYPES = new Set([
  'string',
  'number',
  'integer',
  'boolean',
  'secret',
  'object',
  'array',
  'arrayString',
  'arrayNumber',
  'arrayBoolean',
  'arrayObject',
  'arrayFile',
  'array[string]',
  'array[number]',
  'array[boolean]',
  'array[object]',
])

export const CODE_NODE_DEFAULTS = {
  code_language: 'python3',
  code: '',
  variables: [],
  outputs: {},
}

const LEGACY_ERROR_STRATEGIES = {
  defaultValue: 'default-value',
  failBranch: 'fail-branch',
}

const PYTHON_TYPE_HINTS = {
  string: 'str',
  number: 'float',
  integer: 'int',
  boolean: 'bool',
  object: 'dict',
  array: 'list',
  arrayString: 'list[str]',
  arrayNumber: 'list[float]',
  arrayBoolean: 'list[bool]',
  arrayObject: 'list[dict]',
  'array[string]': 'list[str]',
  'array[number]': 'list[float]',
  'array[boolean]': 'list[bool]',
  'array[object]': 'list[dict]',
}

export function isValidCodeVariableName(name) {
  return /^[A-Za-z_]\w*$/.test(String(name || ''))
}

export function normalizeCodeNodeData(data = {}) {
  const variables = Array.isArray(data.variables)
    ? data.variables.map(variable => ({
        ...variable,
        variable: String(variable?.variable || ''),
        value_selector: Array.isArray(variable?.value_selector)
          ? variable.value_selector.map(String)
          : [],
      }))
    : []
  const outputs = Object.fromEntries(Object.entries(data.outputs || {}).map(([key, output]) => [
    key,
    {
      ...(output || {}),
      type: output?.type || 'string',
      children: output?.children ?? null,
    },
  ]))
  const errorStrategy = LEGACY_ERROR_STRATEGIES[data.error_strategy] || data.error_strategy

  const normalized = {
    ...data,
    code_language: data.code_language || CODE_NODE_DEFAULTS.code_language,
    code: typeof data.code === 'string' ? data.code : '',
    variables,
    outputs,
  }
  if (!errorStrategy || errorStrategy === 'none') {
    delete normalized.error_strategy
    delete normalized.default_value
  }
  else {
    normalized.error_strategy = errorStrategy
  }
  if (errorStrategy === 'default-value')
    normalized.default_value = normalizeCodeDefaultValues(data.default_value, outputs)
  else if (errorStrategy === 'fail-branch')
    delete normalized.default_value
  return normalized
}

export function upsertCodeInput(data, index, input) {
  const normalized = normalizeCodeNodeData(data)
  const variables = [...normalized.variables]
  variables[index] = {
    ...(variables[index] || {}),
    ...input,
    variable: String(input?.variable || ''),
    value_selector: Array.isArray(input?.value_selector) ? [...input.value_selector] : [],
  }
  return { ...normalized, variables }
}

export function upsertCodeOutput(data, name, type) {
  const normalized = normalizeCodeNodeData(data)
  const outputs = {
    ...normalized.outputs,
    [name]: {
      ...(normalized.outputs[name] || {}),
      type,
      children: null,
    },
  }
  const next = { ...normalized, outputs }
  if (next.error_strategy === 'default-value')
    next.default_value = createCodeDefaultValues(outputs)
  return next
}

export function removeCodeOutput(data, name) {
  const normalized = normalizeCodeNodeData(data)
  const outputs = { ...normalized.outputs }
  delete outputs[name]
  const next = { ...normalized, outputs }
  if (next.error_strategy === 'default-value')
    next.default_value = createCodeDefaultValues(outputs)
  return next
}

export function renameCodeOutput(data, oldName, newName) {
  const normalized = normalizeCodeNodeData(data)
  if (oldName === newName || !normalized.outputs[oldName] || normalized.outputs[newName])
    return normalized
  const outputs = {}
  for (const [name, output] of Object.entries(normalized.outputs))
    outputs[name === oldName ? newName : name] = output
  const next = { ...normalized, outputs }
  if (next.error_strategy === 'default-value')
    next.default_value = createCodeDefaultValues(outputs)
  return next
}

export function syncCodeFunctionSignature(code, language, variables = []) {
  const names = variables.map(item => item.variable).filter(isValidCodeVariableName)
  if (language === 'javascript') {
    return String(code || '').replace(
      /function\s+main\b\s*\([\s\S]*?\)/,
      `function main({${names.join(', ')}})`,
    )
  }
  if (language === 'python3') {
    const params = variables
      .filter(item => isValidCodeVariableName(item.variable))
      .map((item) => {
        const hint = PYTHON_TYPE_HINTS[item.value_type]
        return hint ? `${item.variable}: ${hint}` : item.variable
      })
    return String(code || '').replace(
      /def\s+main\b\s*\([\s\S]*?\)/,
      `def main(${params.join(', ')})`,
    )
  }
  return String(code || '')
}

export function createCodeDefaultValues(outputs = {}) {
  return Object.entries(outputs).map(([key, output]) => ({
    key,
    type: output?.type || 'string',
    value: defaultValueForType(output?.type),
  }))
}

function normalizeCodeDefaultValues(defaultValue, outputs) {
  if (Array.isArray(defaultValue)) {
    const current = new Map(defaultValue.map(item => [item?.key, item]))
    return Object.entries(outputs).map(([key, output]) => ({
      key,
      type: output?.type || 'string',
      value: current.has(key) ? current.get(key)?.value : defaultValueForType(output?.type),
    }))
  }
  if (defaultValue && typeof defaultValue === 'object') {
    return Object.entries(outputs).map(([key, output]) => ({
      key,
      type: output?.type || 'string',
      value: Object.hasOwn(defaultValue, key) ? defaultValue[key] : defaultValueForType(output?.type),
    }))
  }
  return createCodeDefaultValues(outputs)
}

function defaultValueForType(type) {
  if (type === 'number') return 0
  if (type === 'boolean') return false
  if (type === 'object') return '{}'
  if (String(type || '').startsWith('array[')) return '[]'
  return ''
}

export function setCodeErrorStrategy(data, strategy) {
  const normalized = normalizeCodeNodeData(data)
  if (!strategy || strategy === 'none') {
    const { error_strategy: _strategy, default_value: _defaultValue, ...rest } = normalized
    return rest
  }
  const next = { ...normalized, error_strategy: strategy }
  if (strategy === 'default-value')
    next.default_value = createCodeDefaultValues(next.outputs)
  else
    delete next.default_value
  return next
}

export function updateCodeDefaultValue(data, key, value) {
  const normalized = normalizeCodeNodeData(data)
  return {
    ...normalized,
    default_value: normalizeCodeDefaultValues(normalized.default_value, normalized.outputs)
      .map(item => item.key === key ? { ...item, value } : item),
  }
}

export function buildCodeRunInputs(data, inputValues = {}) {
  const declared = new Set(normalizeCodeNodeData(data).variables.map(item => item.variable).filter(Boolean))
  return Object.fromEntries(Object.entries(inputValues || {}).filter(([key]) => declared.has(key)))
}
