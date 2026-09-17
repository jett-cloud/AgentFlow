export const ITERATION_DEFAULTS = Object.freeze({
  start_node_id: '', iterator_selector: [], iterator_input_type: 'array', output_selector: [],
  output_type: 'array', is_parallel: false, parallel_nums: 10,
  error_handle_mode: 'terminated', flatten_output: true, _children: [],
})

const CANONICAL_ARRAY_TYPES = {
  array: 'array',
  arrayString: 'array[string]',
  arrayNumber: 'array[number]',
  arrayBoolean: 'array[boolean]',
  arrayObject: 'array[object]',
  arrayFile: 'array[file]',
  'array[string]': 'array[string]',
  'array[number]': 'array[number]',
  'array[boolean]': 'array[boolean]',
  'array[object]': 'array[object]',
  'array[file]': 'array[file]',
}

const OFFICIAL_OUTPUT_AGGREGATION = {
  string: 'array[string]',
  number: 'array[number]',
  object: 'array[object]',
  file: 'array[file]',
  array: 'array',
  'array[file]': 'array[file]',
  'array[string]': 'array[string]',
  'array[number]': 'array[number]',
  'array[object]': 'array[object]',
}

export function normalizeIterationArrayType(type) {
  return CANONICAL_ARRAY_TYPES[type] || 'array'
}

export function deriveIterationOutputType(type) {
  const normalized = CANONICAL_ARRAY_TYPES[type] || type
  return OFFICIAL_OUTPUT_AGGREGATION[normalized] || 'array[string]'
}

export const ITERATION_ERROR_HANDLE_MODES = Object.freeze([
  'terminated',
  'continue-on-error',
  'remove-abnormal-output',
])

export function isOfficialIterationArrayType(type) {
  return Object.hasOwn(CANONICAL_ARRAY_TYPES, type)
}

export function normalizeIterationErrorHandleMode(value) {
  return ITERATION_ERROR_HANDLE_MODES.includes(value) ? value : 'terminated'
}

export function isIterationArrayVariable(variable = {}) {
  return isOfficialIterationArrayType(variable.type)
}

export function buildIterationInputPatch(selector, variable) {
  return {
    iterator_selector: Array.isArray(selector) ? selector.map(String) : [],
    iterator_input_type: normalizeIterationArrayType(variable?.type),
  }
}

export function buildIterationOutputPatch(selector, variable) {
  return {
    output_selector: Array.isArray(selector) ? selector.map(String) : [],
    output_type: deriveIterationOutputType(variable?.type),
  }
}

export function normalizeIterationData(data = {}) {
  const rawParallel = Number(data.parallel_nums ?? 10)
  const parallelNums = Number.isFinite(rawParallel) ? Math.trunc(rawParallel) : 10
  const outputType = data.output_type
  return {
    ...data,
    start_node_id: String(data.start_node_id || ''),
    iterator_selector: Array.isArray(data.iterator_selector) ? data.iterator_selector.map(String) : [],
    iterator_input_type: normalizeIterationArrayType(data.iterator_input_type),
    output_selector: Array.isArray(data.output_selector) ? data.output_selector.map(String) : [],
    output_type: isOfficialIterationArrayType(outputType)
      ? normalizeIterationArrayType(outputType)
      : (outputType ? deriveIterationOutputType(outputType) : 'array'),
    is_parallel: data.is_parallel === true,
    parallel_nums: Math.max(1, Math.min(10, parallelNums)),
    error_handle_mode: normalizeIterationErrorHandleMode(data.error_handle_mode || data.error_strategy),
    flatten_output: data.flatten_output !== false,
    _children: Array.isArray(data._children) ? data._children.map(child => ({ ...child })) : [],
  }
}
