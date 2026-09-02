export const LOOP_DEFAULTS = Object.freeze({
  start_node_id: '', loop_count: 10, loop_variables: [], break_conditions: [], logical_operator: 'and', _children: [],
})

export function normalizeLoopData(data = {}) {
  const count = Number(data.loop_count ?? data.max_iterations ?? 10)
  return {
    ...data,
    max_iterations: undefined,
    start_node_id: String(data.start_node_id || ''),
    loop_count: Number.isFinite(count) ? count : 10,
    loop_variables: Array.isArray(data.loop_variables) ? data.loop_variables.map(item => ({ ...item })) : [],
    break_conditions: Array.isArray(data.break_conditions) ? data.break_conditions.map(item => ({ ...item })) : [],
    logical_operator: data.logical_operator === 'or' ? 'or' : 'and',
    _children: Array.isArray(data._children) ? data._children.map(item => ({ ...item })) : [],
  }
}

export function isLoopConditionComplete(condition = {}) {
  if (!Array.isArray(condition.variable_selector) || !condition.variable_selector.length || !condition.comparison_operator)
    return false
  return ['empty', 'not empty', 'is null', 'is not null'].includes(condition.comparison_operator)
    || condition.value === false
    || Boolean(condition.value)
}
