const LIST_ITEM_TYPE = {
  array: 'object',
  arrayString: 'string',
  arrayNumber: 'number',
  arrayBoolean: 'boolean',
  arrayObject: 'object',
  arrayFile: 'file',
}

const STRING_FILTER_OPERATORS = [
  'contains',
  'not contains',
  'start with',
  'end with',
  'is',
  'is not',
  'empty',
  'not empty',
]
const NUMBER_FILTER_OPERATORS = ['=', '≠', '>', '<', '≥', '≤', 'empty', 'not empty']
const BOOLEAN_FILTER_OPERATORS = ['=', '≠', 'empty', 'not empty']
const VALUELESS_FILTER_OPERATORS = new Set(['empty', 'not empty', 'is null', 'is not null'])

export const LIST_OPERATOR_DEFAULTS = {
  variable: [],
  filter_by: { enabled: false, conditions: [] },
  extract_by: { enabled: false, serial: '1' },
  order_by: { enabled: false, key: '', value: 'asc' },
  limit: { enabled: false, size: 10 },
}

export function isListVariableType(type) {
  return Object.hasOwn(LIST_ITEM_TYPE, type)
}

export function getListItemType(type) {
  return LIST_ITEM_TYPE[type] || 'string'
}

export function getListFilterOperators(itemType) {
  if (itemType === 'number')
    return [...NUMBER_FILTER_OPERATORS]
  if (itemType === 'boolean')
    return [...BOOLEAN_FILTER_OPERATORS]
  return [...STRING_FILTER_OPERATORS]
}

export function listOperatorRequiresConditionValue(operator) {
  return !VALUELESS_FILTER_OPERATORS.has(operator)
}

export function createListFilterCondition(varType) {
  const isFileArray = varType === 'arrayFile'
  return {
    key: isFileArray ? 'name' : '',
    comparison_operator: '=',
    value: getListItemType(varType) === 'boolean' ? false : '',
  }
}

export function normalizeListOperatorData(data = {}) {
  const {
    variable_selector: legacyVariableSelector,
    ...rest
  } = data

  return {
    ...rest,
    variable: Array.isArray(rest.variable)
      ? [...rest.variable]
      : (Array.isArray(legacyVariableSelector) ? [...legacyVariableSelector] : []),
    filter_by: {
      ...LIST_OPERATOR_DEFAULTS.filter_by,
      ...(rest.filter_by || {}),
      conditions: Array.isArray(rest.filter_by?.conditions)
        ? rest.filter_by.conditions.map(condition => ({ ...condition }))
        : [],
    },
    extract_by: {
      ...LIST_OPERATOR_DEFAULTS.extract_by,
      ...(rest.extract_by || {}),
    },
    order_by: {
      ...LIST_OPERATOR_DEFAULTS.order_by,
      ...(rest.order_by || {}),
    },
    limit: {
      ...LIST_OPERATOR_DEFAULTS.limit,
      ...(rest.limit || {}),
    },
  }
}

export function setListOperatorVariable(data, variable, varType) {
  const normalized = normalizeListOperatorData(data)
  return {
    ...normalized,
    variable: Array.isArray(variable) ? [...variable] : [],
    var_type: varType,
    item_var_type: getListItemType(varType),
    filter_by: {
      ...normalized.filter_by,
      conditions: [createListFilterCondition(varType)],
    },
  }
}

export function updateListOperatorSection(data, section, value) {
  const normalized = normalizeListOperatorData(data)
  const next = {
    ...normalized,
    [section]: {
      ...(normalized[section] || {}),
      ...(value || {}),
    },
  }
  if (section === 'filter_by')
    delete next.filter_condition
  return next
}
