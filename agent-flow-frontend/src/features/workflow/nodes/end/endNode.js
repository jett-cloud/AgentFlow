import { parseSelectorInput } from '../../model/availableVariables.js'
import { AppMode } from '../../model/appModes.js'

export const END_DEFAULTS = {
  outputs: [],
}

const LEGACY_END_OUTPUT_TYPE_MAP = Object.freeze({
  arrayString: 'array[string]',
  arrayNumber: 'array[number]',
  arrayObject: 'array[object]',
  arrayBoolean: 'array[boolean]',
  arrayFile: 'array[file]',
  arrayAny: 'array[any]',
})

const DIFY_END_OUTPUT_VALUE_TYPES = new Set([
  'string',
  'number',
  'integer',
  'secret',
  'boolean',
  'object',
  'file',
  'array',
  'array[string]',
  'array[number]',
  'array[object]',
  'array[boolean]',
  'array[file]',
  'any',
  'array[any]',
])

export function normalizeEndOutputValueType(valueType) {
  const normalized = String(valueType || '').trim()
  return LEGACY_END_OUTPUT_TYPE_MAP[normalized] || normalized
}

export function isEndAllowedInMode(mode) {
  return mode === AppMode.WORKFLOW
}

export function isValidEndOutputName(name) {
  return /^[A-Za-z_]\w*$/.test(String(name || '').trim())
}

export function normalizeEndNodeData(data = {}) {
  return {
    ...data,
    type: 'end',
    outputs: Array.isArray(data.outputs)
      ? data.outputs.map((output) => {
          const normalized = {
            ...(output || {}),
            variable: String(output?.variable || '').trim(),
            value_selector: parseSelectorInput(output?.value_selector),
          }
          if (output?.value_type != null)
            normalized.value_type = normalizeEndOutputValueType(output.value_type)
          return normalized
        })
      : [],
  }
}

export function upsertEndOutput(data = {}, index = -1, output = {}) {
  const normalized = normalizeEndNodeData(data)
  const nextOutput = {
    ...output,
    variable: String(output.variable || '').trim(),
    value_selector: parseSelectorInput(output.value_selector),
  }
  if (output.value_type != null)
    nextOutput.value_type = normalizeEndOutputValueType(output.value_type)
  const duplicate = normalized.outputs.some((item, itemIndex) => (
    itemIndex !== index && item.variable === nextOutput.variable
  ))
  if (duplicate)
    return { ok: false, data: normalized }

  const outputs = [...normalized.outputs]
  if (index >= 0 && index < outputs.length)
    outputs[index] = { ...(outputs[index] || {}), ...nextOutput }
  else
    outputs.push(nextOutput)
  return { ok: true, data: { ...normalized, outputs } }
}

export function removeEndOutput(data = {}, index) {
  const normalized = normalizeEndNodeData(data)
  return {
    ...normalized,
    outputs: normalized.outputs.filter((_, itemIndex) => itemIndex !== index),
  }
}

export function getEndValidationErrors(data = {}) {
  const outputs = normalizeEndNodeData(data).outputs
  if (!outputs.length)
    return ['至少添加一个输出变量']

  const errors = []
  const counts = new Map()
  for (const output of outputs) {
    counts.set(output.variable, (counts.get(output.variable) || 0) + 1)
    if (!isValidEndOutputName(output.variable))
      errors.push(`输出变量名“${output.variable}”不合法`)
    if (output.value_selector.length < 2)
      errors.push(`输出变量“${output.variable}”未绑定上游变量`)
    if (!output.value_type)
      errors.push(`输出变量“${output.variable}”缺少类型`)
    else if (!DIFY_END_OUTPUT_VALUE_TYPES.has(output.value_type))
      errors.push(`输出变量“${output.variable}”的类型“${output.value_type}”不是 Dify 支持的类型`)
  }
  for (const [name, count] of counts) {
    if (name && count > 1)
      errors.push(`输出变量名“${name}”重复`)
  }
  return errors
}
