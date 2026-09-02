export const TEMPLATE_TRANSFORM_DEFAULTS = Object.freeze({
  template: '',
  variables: [],
})

export const TEMPLATE_TRANSFORM_INPUT_TYPES = new Set([
  'string',
  'number',
  'integer',
  'boolean',
  'object',
  'array',
  'arrayString',
  'arrayNumber',
  'arrayBoolean',
  'arrayObject',
  'array[string]',
  'array[number]',
  'array[boolean]',
  'array[object]',
])

export function isValidTemplateVariableName(name) {
  return /^[A-Za-z_]\w*$/.test(String(name || '')) && String(name).length <= 30
}

function normalizeVariable(variable = {}) {
  return {
    ...variable,
    variable: String(variable.variable || ''),
    value_selector: Array.isArray(variable.value_selector)
      ? variable.value_selector.map(String)
      : [],
  }
}

export function normalizeTemplateTransformData(data = {}) {
  return {
    ...data,
    template: typeof data.template === 'string' ? data.template : '',
    variables: Array.isArray(data.variables)
      ? data.variables.map(normalizeVariable)
      : [],
  }
}

export function addTemplateVariable(data = {}) {
  const normalized = normalizeTemplateTransformData(data)
  return {
    ...normalized,
    variables: [
      ...normalized.variables,
      { variable: '', value_selector: [] },
    ],
  }
}

function uniqueVariableName(variables, preferred, index) {
  const used = new Set(variables
    .filter((_, variableIndex) => variableIndex !== index)
    .map(variable => variable.variable)
    .filter(Boolean))
  const base = String(preferred || 'variable').replace(/\W/g, '_').replace(/^\d/, '_$&') || 'variable'
  let candidate = base
  let suffix = 1
  while (used.has(candidate)) {
    candidate = `${base}_${suffix}`
    suffix += 1
  }
  return candidate
}

export function updateTemplateVariable(data = {}, index, patch = {}) {
  const normalized = normalizeTemplateTransformData(data)
  if (!normalized.variables[index])
    return normalized

  const next = normalizeVariable({ ...normalized.variables[index], ...patch })
  if (!next.variable && next.value_selector.length) {
    next.variable = uniqueVariableName(
      normalized.variables,
      next.value_selector.at(-1),
      index,
    )
  }
  return {
    ...normalized,
    variables: normalized.variables.map((variable, variableIndex) => (
      variableIndex === index ? next : variable
    )),
  }
}

function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function renameTemplateVariable(data = {}, index, newName) {
  const normalized = normalizeTemplateTransformData(data)
  const current = normalized.variables[index]
  if (!current)
    return normalized
  const name = String(newName || '').replaceAll(' ', '_')
  const oldName = current.variable
  const template = oldName
    ? normalized.template.replace(
        new RegExp(`\\{\\{\\s*${escapeRegex(oldName)}\\s*\\}\\}`, 'g'),
        `{{ ${name} }}`,
      )
    : normalized.template
  return updateTemplateVariable({ ...normalized, template }, index, { variable: name })
}

export function removeTemplateVariable(data = {}, index) {
  const normalized = normalizeTemplateTransformData(data)
  return {
    ...normalized,
    variables: normalized.variables.filter((_, variableIndex) => variableIndex !== index),
  }
}

export function buildTemplateRunInputs(data = {}, inputs = {}) {
  const names = new Set(normalizeTemplateTransformData(data).variables
    .map(variable => variable.variable)
    .filter(Boolean))
  return Object.fromEntries(Object.entries(inputs || {}).filter(([key]) => names.has(key)))
}
