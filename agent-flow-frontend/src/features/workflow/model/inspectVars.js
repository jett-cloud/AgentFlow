/**
 * Helpers for Variable Inspect + debug run history.
 * Contrasts Dify variable-inspect + use-get-run-and-trace-url.
 */

/** Scalar / JSON types editable via PATCH (defer file / array[file]). */
export const EDITABLE_INSPECT_VALUE_TYPES = new Set([
  'string',
  'number',
  'boolean',
  'object',
  'array[string]',
  'array[number]',
  'array[object]',
  'array[any]',
  'array[boolean]',
])

/** Group draft inspect vars by selector[0] node id. */
export function groupInspectVarsByNode(vars = []) {
  const groups = new Map()
  for (const item of vars) {
    const selector = item?.selector
    const nodeId = Array.isArray(selector) ? selector[0] : (item?.node_id || 'unknown')
    if (!groups.has(nodeId))
      groups.set(nodeId, [])
    groups.get(nodeId).push(item)
  }
  return groups
}

export function formatInspectVarLabel(item) {
  if (!item)
    return ''
  if (item.name)
    return item.name
  const selector = item.selector
  if (Array.isArray(selector) && selector.length > 1)
    return selector.slice(1).join('.')
  return item.id || 'var'
}

export function formatInspectVarValue(item) {
  if (!item)
    return '—'
  if (Object.prototype.hasOwnProperty.call(item, 'value'))
    return item.value
  if (Object.prototype.hasOwnProperty.call(item, 'value_type'))
    return `(${item.value_type})`
  return '—'
}

export function isEditableInspectValueType(valueType) {
  return EDITABLE_INSPECT_VALUE_TYPES.has(valueType)
}

/**
 * Draft-variable rows with an id can be mutated (not ENV / live tracing / secret / file).
 * Contrasts Dify getValueEditorState text/JSON editors (file deferred).
 */
export function canMutateInspectItem(item) {
  if (!item?.id)
    return false
  if (item.kind === 'env' || item.kind === 'tracing')
    return false
  const valueType = item.valueType || item.value_type || item.type || ''
  if (valueType === 'secret' || valueType === 'file' || valueType === 'array[file]')
    return false
  if (typeof item.rawValue === 'boolean')
    return true
  return isEditableInspectValueType(valueType)
}

export function serializeInspectEditText(value, valueType) {
  if (valueType === 'string')
    return value == null ? '' : String(value)
  if (valueType === 'number')
    return value == null || value === '' ? '' : String(value)
  if (valueType === 'boolean')
    return value ? 'true' : 'false'
  try {
    return JSON.stringify(value ?? null, null, 2)
  }
  catch {
    return String(value)
  }
}

/** Parse editor text into PATCH body value. */
export function parseInspectEditValue(text, valueType) {
  if (valueType === 'string')
    return { ok: true, value: text ?? '' }
  if (valueType === 'number') {
    const raw = String(text ?? '').trim()
    if (!/^-?\d+(\.)?(\d+)?$/.test(raw))
      return { ok: false, error: '无效数字' }
    return { ok: true, value: Number.parseFloat(raw) }
  }
  if (valueType === 'boolean') {
    const raw = String(text ?? '').trim().toLowerCase()
    if (raw === 'true')
      return { ok: true, value: true }
    if (raw === 'false')
      return { ok: true, value: false }
    return { ok: false, error: '请输入 true 或 false' }
  }
  try {
    return { ok: true, value: JSON.parse(text) }
  }
  catch (err) {
    return { ok: false, error: err?.message || '无效 JSON' }
  }
}

/** Normalize API / env / tracing rows for the inspect panel list. */
export function toInspectPanelItem(item, prefix, index = 0) {
  const valueType = item?.value_type || item?.type || ''
  const rawValue = formatInspectVarValue(item)
  const kind = prefix === 'env'
    ? 'env'
    : prefix === 'conversation'
      ? 'conversation'
      : prefix === 'system'
        ? 'system'
        : prefix.startsWith('trace')
          ? 'tracing'
          : 'node'
  const panelItem = {
    key: `${prefix}-${item?.id || formatInspectVarLabel(item) || index}`,
    id: item?.id || '',
    label: formatInspectVarLabel(item),
    type: valueType,
    valueType,
    edited: !!item?.edited,
    rawValue,
    value: rawValue,
    kind,
  }
  panelItem.mutable = canMutateInspectItem(panelItem)
  return panelItem
}

/** Map GET .../node-executions payload into live tracing item shape. */
export function mapNodeExecutionsToTracing(payload) {
  const list = Array.isArray(payload)
    ? payload
    : (payload?.data || payload?.items || [])
  return list.map((item, index) => ({
    nodeId: item.node_id,
    title: item.title || item.node_type || item.node_id,
    nodeType: item.node_type,
    status: item.status,
    inputs: item.inputs,
    processData: item.process_data,
    outputs: item.outputs,
    error: item.error,
    elapsed_time: item.elapsed_time,
    executionMetadata: item.execution_metadata,
    index,
  }))
}

export function normalizeWorkflowRunList(payload) {
  return payload?.data || payload?.items || []
}
