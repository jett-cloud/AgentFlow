export const InputVarType = Object.freeze({
  textInput: 'text-input',
  paragraph: 'paragraph',
  select: 'select',
  number: 'number',
  checkbox: 'checkbox',
  jsonObject: 'json_object',
  singleFile: 'file',
  multiFiles: 'file-list',
})

const LEGACY_TYPE_MAP = Object.freeze({
  'json-object': InputVarType.jsonObject,
  'single-file': InputVarType.singleFile,
  'multi-files': InputVarType.multiFiles,
})

const START_INPUT_TYPES = new Set(Object.values(InputVarType))
const FILE_INPUT_TYPES = new Set([InputVarType.singleFile, InputVarType.multiFiles])
const FILE_TYPES = new Set(['document', 'image', 'audio', 'video', 'custom'])
const FILE_UPLOAD_METHODS = new Set(['local_file', 'remote_url'])
const RESERVED_VARIABLE_NAMES = new Set(['sys.query', 'sys.files'])

export function normalizeStartVariable(variable = {}) {
  return {
    ...variable,
    type: LEGACY_TYPE_MAP[variable.type] || variable.type,
  }
}

export function normalizeStartNodeData(data = {}) {
  return {
    ...data,
    type: 'start',
    variables: Array.isArray(data.variables)
      ? data.variables.map(normalizeStartVariable)
      : [],
  }
}

export function createStartVariable(variableName = '', type = InputVarType.textInput) {
  const normalizedType = LEGACY_TYPE_MAP[type] || type
  const name = String(variableName || '').trim()
  const base = {
    variable: name,
    label: name,
    type: normalizedType,
    required: true,
    hide: false,
  }

  switch (normalizedType) {
    case InputVarType.textInput:
      return { ...base, max_length: 256, default: '' }
    case InputVarType.paragraph:
      return { ...base, max_length: 500, default: '' }
    case InputVarType.number:
      return { ...base, default: undefined }
    case InputVarType.checkbox:
      return { ...base, default: false }
    case InputVarType.select:
      return { ...base, options: ['选项1', '选项2'], default: undefined }
    case InputVarType.singleFile:
      return {
        ...base,
        allowed_file_types: ['document', 'image'],
        allowed_file_upload_methods: ['local_file', 'remote_url'],
        max_length: 1,
      }
    case InputVarType.multiFiles:
      return {
        ...base,
        allowed_file_types: ['document', 'image'],
        allowed_file_upload_methods: ['local_file', 'remote_url'],
        max_length: 5,
      }
    case InputVarType.jsonObject:
      return {
        ...base,
        json_schema: '{\n  "type": "object",\n  "properties": {}\n}',
      }
    default:
      return base
  }
}

function hasValidObjectSchema(schema) {
  let value = schema
  if (typeof value === 'string') {
    try {
      value = JSON.parse(value)
    }
    catch {
      return false
    }
  }
  return Boolean(value && typeof value === 'object' && !Array.isArray(value) && value.type === 'object')
}

export function getStartNodeValidationErrors(data = {}) {
  const errors = []
  const variables = Array.isArray(data.variables) ? data.variables : []
  const names = new Set()

  for (const variable of variables) {
    const name = String(variable?.variable || '').trim()
    const type = variable?.type
    if (!name)
      errors.push('输入变量 Key 不能为空')
    else if (RESERVED_VARIABLE_NAMES.has(name))
      errors.push(`系统变量 ${name} 不能写入 Start variables`)
    else if (names.has(name))
      errors.push(`输入变量 ${name} 重复`)
    else
      names.add(name)

    if (!String(variable?.label || '').trim())
      errors.push(`输入变量 ${name || '(未命名)'} 缺少显示名称`)
    if (!START_INPUT_TYPES.has(type))
      errors.push(`输入变量 ${name || '(未命名)'} 使用了不支持的类型 ${String(type || '')}`)
    if (type === InputVarType.select && (!Array.isArray(variable.options) || variable.options.length === 0))
      errors.push(`下拉输入 ${name || '(未命名)'} 至少需要一个选项`)
    if (FILE_INPUT_TYPES.has(type)) {
      const fileTypes = Array.isArray(variable.allowed_file_types) ? variable.allowed_file_types : []
      const uploadMethods = Array.isArray(variable.allowed_file_upload_methods)
        ? variable.allowed_file_upload_methods
        : []
      if (fileTypes.length === 0 || fileTypes.some(item => !FILE_TYPES.has(item)))
        errors.push(`文件输入 ${name || '(未命名)'} 必须配置合法的文件类型`)
      if (uploadMethods.length === 0 || uploadMethods.some(item => !FILE_UPLOAD_METHODS.has(item)))
        errors.push(`文件输入 ${name || '(未命名)'} 必须配置合法的上传方式`)
      if (fileTypes.includes('custom')
        && (!Array.isArray(variable.allowed_file_extensions) || variable.allowed_file_extensions.length === 0))
        errors.push(`自定义文件输入 ${name || '(未命名)'} 必须配置扩展名`)
    }
    if (type === InputVarType.jsonObject && !hasValidObjectSchema(variable.json_schema))
      errors.push(`JSON 输入 ${name || '(未命名)'} 必须配置对象类型的合法 JSON Schema`)
  }

  return errors
}
