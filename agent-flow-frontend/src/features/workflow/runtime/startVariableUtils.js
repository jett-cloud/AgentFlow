import { getProcessedHumanInputFiles, isHumanInputFileUploaded } from './humanInputFormUtils.js'

export const START_INPUT_TYPE = {
  text: 'text-input',
  paragraph: 'paragraph',
  select: 'select',
  number: 'number',
  checkbox: 'checkbox',
  json: 'json-object',
  file: 'file',
  fileList: 'file-list',
}

export function normalizeStartVariableType(type) {
  const value = String(type || START_INPUT_TYPE.text).toLowerCase()
  if (value === 'single-file') return START_INPUT_TYPE.file
  if (value === 'multi-files') return START_INPUT_TYPE.fileList
  if (value === 'json_object') return START_INPUT_TYPE.json
  return value
}

export function isStartFileVariable(variable) {
  const type = normalizeStartVariableType(variable?.type)
  return type === START_INPUT_TYPE.file || type === START_INPUT_TYPE.fileList
}

export function getStartVariableDefault(variable) {
  const type = normalizeStartVariableType(variable?.type)
  if (type === START_INPUT_TYPE.file)
    return variable?.default ?? variable?.default_value ?? null
  if (type === START_INPUT_TYPE.fileList)
    return variable?.default ?? variable?.default_value ?? []
  return variable?.default ?? variable?.default_value ?? (type === START_INPUT_TYPE.checkbox ? false : '')
}

function isProcessedFile(value) {
  return Boolean(value && typeof value === 'object' && 'transfer_method' in value)
}

function processStartFile(value) {
  if (!value) return undefined
  if (isProcessedFile(value)) {
    return {
      type: value.type,
      transfer_method: value.transfer_method,
      url: value.url || value.remote_url || '',
      upload_file_id: value.upload_file_id || value.related_id || '',
    }
  }
  if (!isHumanInputFileUploaded(value)) return undefined
  return getProcessedHumanInputFiles([value])[0]
}

export function getProcessedStartVariableInputs(variables = [], inputs = {}) {
  const result = { ...(inputs || {}) }
  for (const variable of Array.isArray(variables) ? variables : []) {
    const name = variable?.variable
    if (!name) continue
    const type = normalizeStartVariableType(variable.type)
    const value = result[name]
    if (type === START_INPUT_TYPE.file) {
      result[name] = processStartFile(Array.isArray(value) ? value[0] : value)
    }
    else if (type === START_INPUT_TYPE.fileList) {
      result[name] = (Array.isArray(value) ? value : []).map(processStartFile).filter(Boolean)
    }
    else if (type === START_INPUT_TYPE.checkbox) {
      result[name] = Boolean(value)
    }
    else if (type === START_INPUT_TYPE.json && typeof value === 'string') {
      try {
        const parsed = JSON.parse(value)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) result[name] = parsed
      }
      catch {
        // Keep invalid JSON as entered; backend validation reports the field error.
      }
    }
  }
  return result
}

export function validateStartVariableInputs(variables = [], inputs = {}) {
  const missing = []
  for (const variable of Array.isArray(variables) ? variables : []) {
    if (!variable?.required || !variable.variable) continue
    const value = inputs?.[variable.variable]
    const type = normalizeStartVariableType(variable.type)
    const emptyFile = type === START_INPUT_TYPE.file
      ? !processStartFile(Array.isArray(value) ? value[0] : value)
      : type === START_INPUT_TYPE.fileList
        ? !(Array.isArray(value) && value.map(processStartFile).some(Boolean))
        : false
    if (emptyFile || (!isStartFileVariable(variable) && (value === undefined || value === null || String(value).trim() === ''))) {
      missing.push(variable.label || variable.variable)
    }
  }
  return missing
}
