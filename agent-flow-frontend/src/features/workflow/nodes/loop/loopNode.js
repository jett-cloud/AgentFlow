export const LOOP_DEFAULTS = Object.freeze({
  start_node_id: '', loop_count: 10, loop_variables: [], break_conditions: [], logical_operator: 'and', _children: [],
})

export const LOOP_VARIABLE_TYPES = Object.freeze([
  'string', 'number', 'boolean', 'object',
  'array[string]', 'array[number]', 'array[boolean]', 'array[object]',
])

export const LOOP_VARIABLE_NAME_RE = /^[A-Za-z_]\w*$/

const CANONICAL_LOOP_VAR_TYPES = {
  string: 'string',
  number: 'number',
  integer: 'number',
  boolean: 'boolean',
  object: 'object',
  arrayString: 'array[string]',
  arrayNumber: 'array[number]',
  arrayBoolean: 'array[boolean]',
  arrayObject: 'array[object]',
  'array[string]': 'array[string]',
  'array[number]': 'array[number]',
  'array[boolean]': 'array[boolean]',
  'array[object]': 'array[object]',
  array: 'array',
  file: 'file',
}

export const LOOP_COMPARISON_OPERATORS = Object.freeze([
  'contains', 'not contains', 'start with', 'end with',
  'is', 'is not', 'empty', 'not empty', '=', '≠', '>', '<', '≥', '≤',
  'is null', 'is not null', 'in', 'not in', 'all of', 'exists', 'not exists',
])

const VALUELESS_OPERATORS = new Set([
  'empty', 'not empty', 'is null', 'is not null', 'null', 'not null', 'exists', 'not exists',
])

const FILE_ATTRIBUTE_OPERATORS = {
  name: ['contains', 'not contains', 'start with', 'end with', 'is', 'is not', 'empty', 'not empty'],
  type: ['in', 'not in'],
  size: ['>', '≥', '<', '≤'],
  extension: ['is', 'is not', 'contains', 'not contains'],
  mime_type: ['contains', 'not contains', 'start with', 'end with', 'is', 'is not', 'empty', 'not empty'],
  transfer_method: ['in', 'not in'],
  url: ['contains', 'not contains', 'start with', 'end with', 'is', 'is not', 'empty', 'not empty'],
}

let loopEntitySeq = 0

export function createLoopEntityId() {
  if (globalThis.crypto?.randomUUID)
    return globalThis.crypto.randomUUID()
  loopEntitySeq += 1
  return `10000000-0000-4000-8000-${String(loopEntitySeq).padStart(12, '0')}`
}

export function canonicalizeLoopVarType(type) {
  return CANONICAL_LOOP_VAR_TYPES[type] || ''
}

export function isLoopVariableType(type) {
  return LOOP_VARIABLE_TYPES.includes(canonicalizeLoopVarType(type))
}

export function isLoopValueType(type) {
  return type === 'constant' || type === 'variable'
}

export function isLoopConstantValueValid(type, value) {
  const canonical = canonicalizeLoopVarType(type)
  if (!LOOP_VARIABLE_TYPES.includes(canonical))
    return false
  if (canonical === 'string')
    return typeof value === 'string'
  if (canonical === 'number')
    return typeof value === 'number' && Number.isFinite(value)
  if (canonical === 'boolean')
    return typeof value === 'boolean'
  if (canonical === 'object')
    return value !== null && typeof value === 'object' && !Array.isArray(value)
  if (!Array.isArray(value))
    return false
  if (canonical === 'array[string]')
    return value.every(item => typeof item === 'string')
  if (canonical === 'array[number]')
    return value.every(item => typeof item === 'number' && Number.isFinite(item))
  if (canonical === 'array[boolean]')
    return value.every(item => typeof item === 'boolean')
  if (canonical === 'array[object]')
    return value.every(item => item !== null && typeof item === 'object' && !Array.isArray(item))
  return false
}

export function isValidLoopVariableLabel(label) {
  return LOOP_VARIABLE_NAME_RE.test(String(label || ''))
}

export function defaultLoopConstant(type) {
  const canonical = canonicalizeLoopVarType(type) || type
  if (canonical === 'number')
    return 0
  if (canonical === 'boolean')
    return false
  if (canonical === 'object')
    return {}
  if (String(canonical).startsWith('array'))
    return []
  return ''
}

export function coerceLoopConstant(type, value) {
  if (value === undefined)
    return defaultLoopConstant(type)
  return value
}

export function isValuelessLoopOperator(operator) {
  return VALUELESS_OPERATORS.has(operator)
}

export function getLoopOperators(type, fileKey) {
  if (fileKey && FILE_ATTRIBUTE_OPERATORS[fileKey])
    return FILE_ATTRIBUTE_OPERATORS[fileKey]
  const canonical = canonicalizeLoopVarType(type) || type
  if (canonical === 'string')
    return ['contains', 'not contains', 'start with', 'end with', 'is', 'is not', 'empty', 'not empty']
  if (canonical === 'number')
    return ['=', '≠', '>', '<', '≥', '≤', 'empty', 'not empty']
  if (canonical === 'boolean')
    return ['is', 'is not', 'empty', 'not empty']
  if (canonical === 'object' || canonical === 'array' || canonical === 'array[object]')
    return ['empty', 'not empty']
  if (canonical === 'array[string]' || canonical === 'array[number]')
    return ['contains', 'not contains', 'empty', 'not empty']
  if (canonical === 'file')
    return ['exists', 'not exists']
  return []
}

export function isLoopVariableSource(variable = {}, varType) {
  return canonicalizeLoopVarType(variable.type) === canonicalizeLoopVarType(varType)
}

export function buildBreakConditionPatch(selector, variable = {}) {
  const varType = canonicalizeLoopVarType(variable.type) || 'string'
  const comparison_operator = getLoopOperators(varType)[0]
  return {
    variable_selector: Array.isArray(selector) ? selector.map(String) : [],
    varType,
    comparison_operator,
    value: isValuelessLoopOperator(comparison_operator) ? undefined : defaultLoopConstant(varType),
  }
}

function defaultLoopVariableValue(variable) {
  if (variable.value_type === 'variable')
    return []
  return defaultLoopConstant(variable.var_type)
}

export function normalizeLoopData(data = {}) {
  const hasCount = data.loop_count != null || data.max_iterations != null
  const rawCount = Number(data.loop_count ?? data.max_iterations)
  return {
    ...data,
    max_iterations: undefined,
    start_node_id: String(data.start_node_id || ''),
    loop_count: hasCount && Number.isFinite(rawCount) ? Math.trunc(rawCount) : (hasCount ? data.loop_count : 10),
    loop_variables: Array.isArray(data.loop_variables)
      ? data.loop_variables.map((item) => {
          const canonicalType = canonicalizeLoopVarType(item.var_type)
          const varType = isLoopVariableType(item.var_type) ? canonicalType : item.var_type
          const valueType = item.value_type === 'variable' || item.value_type === 'constant'
            ? item.value_type
            : (item.value_type == null || item.value_type === '' ? 'constant' : item.value_type)
          const value = item.value === undefined
            ? defaultLoopVariableValue({ ...item, var_type: varType || 'string', value_type: valueType })
            : item.value
          return {
            ...item,
            var_type: varType,
            value_type: valueType,
            value: valueType === 'variable'
              ? (Array.isArray(value) ? value.map(String) : value)
              : value,
          }
        })
      : data.loop_variables,
    break_conditions: Array.isArray(data.break_conditions)
      ? data.break_conditions.map(item => ({
          ...item,
          varType: canonicalizeLoopVarType(item.varType) || item.varType,
        }))
      : data.break_conditions,
    logical_operator: data.logical_operator === 'or' ? 'or' : 'and',
    _children: Array.isArray(data._children) ? data._children.map(child => ({ ...child })) : [],
  }
}

export function isLoopConditionComplete(condition = {}) {
  if (!Array.isArray(condition.variable_selector)
    || condition.variable_selector.length < 2
    || condition.variable_selector.some(part => typeof part !== 'string' || !part.trim())
    || !LOOP_COMPARISON_OPERATORS.includes(condition.comparison_operator))
    return false
  const varType = canonicalizeLoopVarType(condition.varType)
  if (!varType || !getLoopOperators(varType).includes(condition.comparison_operator))
    return false
  if (isValuelessLoopOperator(condition.comparison_operator))
    return true
  if (condition.value === undefined)
    return false
  return condition.value !== null && condition.value !== ''
}
