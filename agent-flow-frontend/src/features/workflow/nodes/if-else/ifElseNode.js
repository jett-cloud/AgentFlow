export const IF_ELSE_DEFAULTS = Object.freeze({
  _targetBranches: [{ id: 'true', name: 'IF' }, { id: 'false', name: 'ELSE' }],
  cases: [{ case_id: 'true', logical_operator: 'and', conditions: [] }],
})

const STRING_OPERATORS = ['contains', 'not contains', 'start with', 'end with', 'is', 'is not', 'empty', 'not empty', 'is null', 'is not null']
const NUMBER_OPERATORS = ['=', '≠', '>', '<', '≥', '≤', 'is null', 'is not null']
const BOOLEAN_OPERATORS = ['is', 'is not', 'is null', 'is not null']
const ARRAY_OPERATORS = ['contains', 'not contains', 'empty', 'not empty', 'is null', 'is not null']

const LABELS = {
  contains: '包含', 'not contains': '不包含', 'start with': '开头是', 'end with': '结尾是',
  is: '等于', 'is not': '不等于', empty: '为空', 'not empty': '不为空',
  '=': '等于', '≠': '不等于', '>': '大于', '<': '小于', '≥': '大于等于', '≤': '小于等于',
  'is null': '为空值', 'is not null': '不为空值',
}

export function getIfElseOperators(varType = 'string') {
  const values = varType === 'number' ? NUMBER_OPERATORS : varType === 'boolean' ? BOOLEAN_OPERATORS : String(varType).startsWith('array') ? ARRAY_OPERATORS : STRING_OPERATORS
  return values.map(value => ({ value, name: `${LABELS[value] || value} (${value})`, needValue: !['empty', 'not empty', 'is null', 'is not null'].includes(value) }))
}

export function normalizeIfElseData(data = {}) {
  const cases = Array.isArray(data.cases) && data.cases.length
    ? data.cases.map((item, index) => ({ ...item, case_id: String(item.case_id || (index === 0 ? 'true' : `case_${index}`)), logical_operator: item.logical_operator === 'or' ? 'or' : 'and', conditions: Array.isArray(item.conditions) ? item.conditions.map(condition => ({ ...condition, variable_selector: Array.isArray(condition.variable_selector) ? condition.variable_selector.map(String) : [] })) : [] }))
    : IF_ELSE_DEFAULTS.cases.map(item => ({ ...item, conditions: [] }))
  return {
    ...data,
    cases,
    _targetBranches: [
      ...cases.map((item, index) => ({ id: item.case_id, name: index === 0 ? 'IF' : `ELIF ${index}` })),
      { id: 'false', name: 'ELSE' },
    ],
  }
}

export function isIfElseConditionComplete(condition = {}) {
  if (!Array.isArray(condition.variable_selector) || !condition.variable_selector.length || !condition.comparison_operator)
    return false
  return ['empty', 'not empty', 'is null', 'is not null'].includes(condition.comparison_operator)
    || condition.value === false
    || Boolean(condition.value)
}
