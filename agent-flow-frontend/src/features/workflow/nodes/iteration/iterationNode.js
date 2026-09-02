export const ITERATION_DEFAULTS = Object.freeze({
  start_node_id: '', iterator_selector: [], iterator_input_type: 'array', output_selector: [],
  output_type: 'array', is_parallel: false, parallel_nums: 10,
  error_handle_mode: 'terminated', flatten_output: false, _children: [],
})

export function normalizeIterationData(data = {}) {
  return {
    ...data,
    start_node_id: String(data.start_node_id || ''),
    iterator_selector: Array.isArray(data.iterator_selector) ? data.iterator_selector.map(String) : [],
    iterator_input_type: data.iterator_input_type || 'array',
    output_selector: Array.isArray(data.output_selector) ? data.output_selector.map(String) : [],
    output_type: data.output_type || 'array',
    is_parallel: data.is_parallel === true,
    parallel_nums: Math.max(1, Math.min(10, Number(data.parallel_nums) || 10)),
    error_handle_mode: data.error_handle_mode || data.error_strategy || 'terminated',
    flatten_output: data.flatten_output === true,
    _children: Array.isArray(data._children) ? data._children.map(child => ({ ...child })) : [],
  }
}

export function isIterationArrayVariable(variable = {}) {
  return ['array', 'arrayString', 'arrayNumber', 'arrayBoolean', 'arrayObject', 'arrayFile', 'array[file]'].includes(variable.type)
}
