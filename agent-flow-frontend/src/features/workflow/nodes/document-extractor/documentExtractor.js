export const DOCUMENT_EXTRACTOR_DEFAULTS = Object.freeze({
  variable_selector: [],
  is_array_file: false,
})

export function isDocumentExtractorInput(variable = {}) {
  return ['file', 'arrayFile', 'array[file]'].includes(variable.type)
}

export function normalizeDocumentExtractorData(data = {}) {
  return {
    ...data,
    variable_selector: Array.isArray(data.variable_selector)
      ? data.variable_selector.map(String)
      : [],
    is_array_file: data.is_array_file === true,
  }
}

export function setDocumentExtractorVariable(data = {}, selector = [], variableType = '') {
  return {
    ...normalizeDocumentExtractorData(data),
    variable_selector: Array.isArray(selector) ? selector.map(String) : [],
    is_array_file: variableType === 'arrayFile' || variableType === 'array[file]',
  }
}

export function buildDocumentExtractorRunInputs(inputs = {}) {
  return { files: Array.isArray(inputs?.files) ? inputs.files : [] }
}
