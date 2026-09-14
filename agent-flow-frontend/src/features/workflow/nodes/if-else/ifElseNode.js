export const IF_ELSE_DEFAULTS = Object.freeze({
  _targetBranches: [{ id: 'true', name: 'IF' }, { id: 'false', name: 'ELSE' }],
  cases: [{ case_id: 'true', logical_operator: 'and', conditions: [] }],
})

const OPERATOR_VALUES = Object.freeze({
  string: ['contains', 'not contains', 'start with', 'end with', 'is', 'is not', 'empty', 'not empty'],
  number: ['=', '≠', '>', '<', '≥', '≤', 'empty', 'not empty'],
  integer: ['=', '≠', '>', '<', '≥', '≤', 'empty', 'not empty'],
  boolean: ['is', 'is not'],
  file: ['exists', 'not exists'],
  arrayString: ['contains', 'not contains', 'empty', 'not empty'],
  arrayNumber: ['contains', 'not contains', 'empty', 'not empty'],
  arrayBoolean: ['contains', 'not contains', 'empty', 'not empty'],
  array: ['empty', 'not empty'],
  arrayObject: ['empty', 'not empty'],
  arrayFile: ['contains', 'not contains', 'all of', 'empty', 'not empty'],
  default: ['is', 'is not', 'empty', 'not empty'],
})

const FILE_ATTRIBUTE_OPERATORS = Object.freeze({
  name: OPERATOR_VALUES.string,
  type: ['in', 'not in'],
  size: ['>', '≥', '<', '≤'],
  extension: ['is', 'is not', 'contains', 'not contains'],
  mime_type: OPERATOR_VALUES.string,
  transfer_method: ['in', 'not in'],
  url: OPERATOR_VALUES.string,
  related_id: ['is', 'is not', 'contains', 'not contains', 'start with', 'end with', 'empty', 'not empty'],
})

const FILE_ATTRIBUTE_TYPES = Object.freeze({
  name: 'string',
  type: 'string',
  size: 'number',
  extension: 'string',
  mime_type: 'string',
  transfer_method: 'string',
  url: 'string',
  related_id: 'string',
})

const LABELS = Object.freeze({
  contains: '包含',
  'not contains': '不包含',
  'start with': '开头是',
  'end with': '结尾是',
  is: '等于',
  'is not': '不等于',
  empty: '为空',
  'not empty': '不为空',
  '=': '等于',
  '≠': '不等于',
  '>': '大于',
  '<': '小于',
  '≥': '大于等于',
  '≤': '小于等于',
  'is null': '为空值',
  'is not null': '不为空值',
  in: '属于',
  'not in': '不属于',
  'all of': '全部满足',
  exists: '存在',
  'not exists': '不存在',
})

const NO_VALUE_OPERATORS = new Set(['empty', 'not empty', 'is null', 'is not null', 'exists', 'not exists'])
const OFFICIAL_OPERATORS = new Set([
  ...Object.values(OPERATOR_VALUES).flat(),
  ...Object.values(FILE_ATTRIBUTE_OPERATORS).flat(),
  'is null',
  'is not null',
])

export function createIfElseId() {
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

export function isIfElseOperatorValueRequired(operator) {
  return Boolean(operator) && !NO_VALUE_OPERATORS.has(operator)
}

export function getIfElseOperators(varType, file) {
  const values = file
    ? (FILE_ATTRIBUTE_OPERATORS[file.key] || [])
    : (OPERATOR_VALUES[varType] || OPERATOR_VALUES.default)
  return values.map(value => ({
    value,
    name: `${LABELS[value] || value} (${value})`,
    needValue: isIfElseOperatorValueRequired(value),
  }))
}

export function createIfElseCondition({ variableSelector = [], varType = 'string', file } = {}) {
  const selector = Array.isArray(variableSelector) ? variableSelector.map(String).filter(Boolean) : []
  const condition = {
    id: createIfElseId(),
    varType,
    variable_selector: selector,
    comparison_operator: selector.length >= 2 ? (getIfElseOperators(varType, file)[0]?.value || '') : '',
    value: varType === 'boolean' || varType === 'arrayBoolean' ? false : '',
  }
  if (file?.key)
    condition.key = String(file.key)
  return condition
}

export function createIfElseSubCondition(key = '') {
  const normalizedKey = String(key || '')
  const varType = FILE_ATTRIBUTE_TYPES[normalizedKey] || 'string'
  return {
    id: createIfElseId(),
    key: normalizedKey,
    varType,
    comparison_operator: normalizedKey ? (getIfElseOperators(varType, { key: normalizedKey })[0]?.value || '') : '',
    value: '',
  }
}

export function deriveIfElseBranches(cases = []) {
  const caseBranches = (Array.isArray(cases) ? cases : []).map((item, index, all) => ({
    id: String(item?.case_id ?? ''),
    name: all.length === 1 ? 'IF' : `CASE ${index + 1}`,
  }))
  return [...caseBranches, { id: 'false', name: 'ELSE' }]
}

function normalizeCondition(condition = {}) {
  return {
    ...condition,
    id: String(condition.id || createIfElseId()),
    varType: String(condition.varType || 'string'),
    variable_selector: Array.isArray(condition.variable_selector)
      ? condition.variable_selector.map(String).filter(Boolean)
      : [],
  }
}

function normalizeCase(item = {}) {
  return {
    ...item,
    case_id: String(item.case_id ?? ''),
    logical_operator: item.logical_operator === 'or' ? 'or' : 'and',
    conditions: Array.isArray(item.conditions) ? item.conditions.map(normalizeCondition) : [],
  }
}

export function normalizeIfElseData(data = {}) {
  let rawCases
  if (Array.isArray(data.cases) && data.cases.length) {
    rawCases = data.cases
  }
  else if (Array.isArray(data.conditions) && data.logical_operator) {
    rawCases = [{
      case_id: 'true',
      logical_operator: data.logical_operator,
      conditions: data.conditions,
    }]
  }
  else {
    rawCases = IF_ELSE_DEFAULTS.cases
  }

  const cases = rawCases.map(normalizeCase)
  const normalized = {
    ...data,
    cases,
    _targetBranches: deriveIfElseBranches(cases),
  }
  delete normalized.conditions
  delete normalized.logical_operator
  return normalized
}

export function addIfElseCase(data = {}) {
  const normalized = normalizeIfElseData(data)
  return normalizeIfElseData({
    ...normalized,
    cases: [
      ...normalized.cases,
      { case_id: createIfElseId(), logical_operator: 'and', conditions: [] },
    ],
  })
}

export function removeIfElseCase(data = {}, caseId) {
  const normalized = normalizeIfElseData(data)
  const index = normalized.cases.findIndex(item => item.case_id === caseId)
  if (index <= 0)
    return normalized
  return normalizeIfElseData({
    ...normalized,
    cases: normalized.cases.filter(item => item.case_id !== caseId),
  })
}

function normalizeChildren(children) {
  if (Array.isArray(children))
    return children
  if (Array.isArray(children?.schema))
    return children.schema
  return []
}

function findNestedVariable(vars, path) {
  if (!path.length)
    return undefined
  const dotted = path.join('.')
  let variable = (vars || []).find(item => item?.variable === dotted)
  if (variable)
    return variable
  variable = (vars || []).find(item => item?.variable === path[0])
  if (!variable)
    return undefined
  if (path.length === 1)
    return variable
  if (variable.type === 'file' || variable.type === 'arrayFile') {
    const key = path[1]
    const type = FILE_ATTRIBUTE_TYPES[key]
    return type ? { variable: key, type, file: { key } } : undefined
  }
  return findNestedVariable(normalizeChildren(variable.children), path.slice(1))
}

export function resolveIfElseVariable(groups = [], selector = []) {
  const path = Array.isArray(selector) ? selector.map(String).filter(Boolean) : []
  if (path.length < 2)
    return undefined

  if (['sys', 'env', 'conversation', 'rag'].includes(path[0])) {
    for (const group of groups) {
      const direct = findNestedVariable(group.vars, path)
        || findNestedVariable(group.vars, [`${path[0]}.${path[1]}`, ...path.slice(2)])
      if (direct)
        return direct
    }
    return undefined
  }

  const group = groups.find(item => item.nodeId === path[0])
  return group ? findNestedVariable(group.vars, path.slice(1)) : undefined
}

export function isIfElseConditionComplete(condition = {}) {
  const selector = condition.variable_selector
  if (!String(condition.id || '').trim()
    || !String(condition.varType || '').trim()
    || !Array.isArray(selector)
    || selector.length < 2
    || selector.some(part => !String(part || '').trim())
    || !OFFICIAL_OPERATORS.has(condition.comparison_operator))
    return false
  if (!isIfElseOperatorValueRequired(condition.comparison_operator))
    return true
  if (condition.varType === 'boolean' || condition.varType === 'arrayBoolean')
    return condition.value !== undefined
  return Boolean(condition.value)
}

export function formatIfElseConditionValue(condition = {}) {
  if (!isIfElseOperatorValueRequired(condition.comparison_operator))
    return condition.comparison_operator ? '' : '未设置'
  if (condition.varType === 'boolean' || condition.varType === 'arrayBoolean') {
    if (condition.value === true) return 'True'
    if (condition.value === false) return 'False'
  }
  if (Array.isArray(condition.value))
    return condition.value.length ? condition.value.join(', ') : '未设置'
  return condition.value === undefined || condition.value === null || condition.value === ''
    ? '未设置'
    : String(condition.value)
}
