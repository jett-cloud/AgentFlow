/**
 * Dify Tool node tool_parameters / tool_configurations value shape.
 * Contrasts web VarKindType: variable | constant | mixed.
 */

export const ToolVarKind = {
  variable: 'variable',
  constant: 'constant',
  mixed: 'mixed',
}

/**
 * Normalize a stored tool parameter into `{ type, value }`.
 * Plain strings from older drafts become mixed text.
 */
export function toToolParamInput(raw, { prefer = ToolVarKind.mixed } = {}) {
  if (raw && typeof raw === 'object' && !Array.isArray(raw) && 'type' in raw) {
    const type = [ToolVarKind.variable, ToolVarKind.constant, ToolVarKind.mixed].includes(raw.type)
      ? raw.type
      : prefer
    return {
      type,
      value: raw.value === undefined || raw.value === null ? '' : raw.value,
    }
  }
  if (raw === undefined || raw === null || raw === '')
    return { type: prefer, value: '' }
  return { type: prefer, value: raw }
}

/** Display string for editors (mixed/constant text, or joined variable selector). */
export function toolParamDisplayValue(raw) {
  const normalized = toToolParamInput(raw)
  if (normalized.type === ToolVarKind.variable) {
    if (Array.isArray(normalized.value))
      return normalized.value.filter(Boolean).join('.')
    return normalized.value == null ? '' : String(normalized.value)
  }
  return normalized.value == null ? '' : String(normalized.value)
}

export function setToolParamValue(params, name, text) {
  const next = { ...(params || {}) }
  const previous = toToolParamInput(next[name])
  // Keep variable type only when value is still a selector array; otherwise mixed text.
  const type = previous.type === ToolVarKind.variable && Array.isArray(previous.value)
    ? ToolVarKind.mixed
    : (previous.type === ToolVarKind.constant ? ToolVarKind.constant : ToolVarKind.mixed)
  next[name] = { type, value: text == null ? '' : text }
  return next
}

export function buildEmptyToolParameters(parameterSchemas = []) {
  const params = {}
  for (const param of parameterSchemas) {
    const name = param?.name
    if (!name)
      continue
    params[name] = { type: ToolVarKind.mixed, value: '' }
  }
  return params
}
