const VARIABLE_INPUT = 'variable'
const OVERWRITE = 'over-write'

function parseSelector(value, defaultNamespace = '') {
  if (Array.isArray(value))
    return value.map(String).filter(Boolean)

  if (typeof value !== 'string')
    return []

  const trimmed = value.trim()
  if (!trimmed)
    return []

  const token = trimmed.match(/^\{\{#(.+?)#\}\}$/)?.[1] || trimmed
  const selector = token.split('.').map(part => part.trim()).filter(Boolean)
  if (defaultNamespace && selector.length === 1)
    return [defaultNamespace, selector[0]]
  return selector
}

export function getAssignmentTargetSelector(item = {}) {
  return parseSelector(
    item.variable_selector || item.assigned_variable_selector || item.target_variable,
    'conversation',
  )
}

export function getAssignmentSourceSelector(item = {}) {
  if (item.input_type && item.input_type !== VARIABLE_INPUT)
    return []
  return parseSelector(item.value || item.input_variable_selector)
}

export function createVariableAssignment(targetSelector, sourceSelector) {
  return {
    variable_selector: parseSelector(targetSelector, 'conversation'),
    input_type: VARIABLE_INPUT,
    operation: OVERWRITE,
    value: parseSelector(sourceSelector),
    write_mode: OVERWRITE,
  }
}

export function normalizeVariableAssignment(item = {}) {
  const inputType = item.input_type || VARIABLE_INPUT
  const normalized = {
    ...item,
    variable_selector: getAssignmentTargetSelector(item),
    input_type: inputType,
    operation: item.operation || item.write_mode || OVERWRITE,
    value: inputType === VARIABLE_INPUT ? getAssignmentSourceSelector(item) : item.value,
    write_mode: item.write_mode || item.operation || OVERWRITE,
  }

  delete normalized.assigned_variable_selector
  delete normalized.input_variable_selector
  delete normalized.target_variable
  return normalized
}
