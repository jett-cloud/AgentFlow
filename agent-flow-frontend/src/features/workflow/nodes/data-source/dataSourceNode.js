import { ToolVarKind, toToolParamInput } from '../../model/toolParamInputs.js'

export const DATA_SOURCE_DEFAULTS = {
  datasource_parameters: {},
  datasource_configurations: {},
}

export const DEFAULT_LOCAL_FILE_EXTENSIONS = [
  'txt', 'markdown', 'mdx', 'pdf', 'html', 'xlsx', 'xls', 'vtt', 'properties',
  'doc', 'docx', 'csv', 'eml', 'msg', 'pptx', 'xml', 'epub', 'ppt', 'md',
]

const VARIABLE_TYPES_BY_PARAMETER = {
  string: new Set(['string']),
  secret_input: new Set(['string']),
  select: new Set(['string']),
  number: new Set(['number']),
  boolean: new Set(['boolean']),
  file: new Set(['file']),
  files: new Set(['arrayFile']),
  system_files: new Set(['arrayFile']),
}

function unwrapList(payload) {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.data)) return payload.data
  if (Array.isArray(payload?.result)) return payload.result
  return []
}

export function localizeDataSourceLabel(label, fallback = '') {
  if (typeof label === 'string') return label
  return label?.zh_Hans || label?.en_US || label?.ja_JP || fallback
}

export function flattenDataSourceCatalog(payload) {
  return unwrapList(payload).flatMap((provider) => {
    const declaration = provider?.declaration || {}
    const providerName = provider?.provider || declaration.identity?.name || ''
    const providerLabel = localizeDataSourceLabel(declaration.identity?.label, providerName)
    return (declaration.datasources || []).map((datasource) => {
      const datasourceName = datasource?.identity?.name || ''
      const datasourceLabel = localizeDataSourceLabel(datasource?.identity?.label, datasourceName)
      return {
        key: `${provider.plugin_id || ''}::${providerName}::${datasourceName}`,
        plugin_id: provider.plugin_id || '',
        plugin_unique_identifier: provider.plugin_unique_identifier || '',
        provider_type: declaration.provider_type || '',
        provider_name: providerName,
        provider_label: providerLabel,
        datasource_name: datasourceName,
        datasource_label: datasourceLabel,
        parameters: Array.isArray(datasource.parameters) ? datasource.parameters : [],
        output_schema: datasource.output_schema || null,
        is_authorized: declaration.provider_type === 'local_file' || provider.is_authorized === true,
      }
    })
  }).filter(option => option.plugin_id && option.provider_name && option.datasource_name)
}

export function normalizeDataSourceData(data = {}) {
  const rawParameters = data.datasource_parameters || {}
  const datasourceParameters = Object.fromEntries(
    Object.entries(rawParameters).map(([name, value]) => [name, toToolParamInput(value)]),
  )
  const normalized = {
    ...data,
    datasource_name: data.datasource_name || data.source_name || '',
    datasource_parameters: datasourceParameters,
    datasource_configurations: data.datasource_configurations || data.config || {},
  }
  delete normalized.source_name
  delete normalized.config
  delete normalized.output_variable
  return normalized
}

export function applyDataSourceSelection(data = {}, option) {
  if (!option) return normalizeDataSourceData(data)
  const datasourceParameters = Object.fromEntries(
    (option.parameters || [])
      .filter(parameter => parameter?.name)
      .map(parameter => [parameter.name, { type: ToolVarKind.mixed, value: '' }]),
  )
  return normalizeDataSourceData({
    ...data,
    plugin_id: option.plugin_id,
    plugin_unique_identifier: option.plugin_unique_identifier,
    provider_type: option.provider_type,
    provider_name: option.provider_name,
    datasource_name: option.datasource_name,
    datasource_label: option.datasource_label,
    datasource_parameters: datasourceParameters,
    datasource_configurations: {},
    ...(option.provider_type === 'local_file' && !Array.isArray(data.fileExtensions)
      ? { fileExtensions: [...DEFAULT_LOCAL_FILE_EXTENSIONS] }
      : {}),
    _datasourceAuthorized: option.is_authorized,
    _datasourceParameterSchemas: option.parameters || [],
    _datasourceOutputSchema: option.output_schema,
  })
}

function isEmptyParameterValue(input) {
  if (!input) return true
  const value = input.value
  if (Array.isArray(value)) return value.length === 0
  return value === undefined || value === null || value === ''
}

export function getDataSourceValidationErrors(data = {}) {
  const errors = []
  if (!data.plugin_id || !data.provider_type || !data.provider_name || !data.datasource_name)
    errors.push('未从数据源目录选择完整的数据源')
  if (data.provider_type !== 'local_file' && data._datasourceAuthorized === false)
    errors.push('数据源尚未授权')
  const schemas = Array.isArray(data._datasourceParameterSchemas)
    ? data._datasourceParameterSchemas
    : []
  for (const schema of schemas) {
    if (!schema?.required || !schema.name) continue
    if (isEmptyParameterValue(data.datasource_parameters?.[schema.name])) {
      const label = localizeDataSourceLabel(schema.label, schema.name)
      errors.push(`必填参数“${label}”未填写`)
    }
  }
  return errors
}

export function isDataSourceConfigured(data = {}) {
  return getDataSourceValidationErrors(data).length === 0
}

export function isDataSourceParameterVariable(variable, parameterType) {
  const allowed = VARIABLE_TYPES_BY_PARAMETER[parameterType]
  return !allowed || allowed.has(variable?.type)
}
