import { defaultSandboxParameterValue } from './sandboxParameterHelpers.js'

function toToolParameter(raw, parameter) {
  if (raw && typeof raw === 'object' && !Array.isArray(raw) && 'type' in raw && 'value' in raw)
    return { type: raw.type, value: raw.value ?? defaultSandboxParameterValue(parameter) }

  if (raw !== undefined && raw !== null && raw !== '')
    return { type: 'mixed', value: raw }

  return { type: 'mixed', value: defaultSandboxParameterValue(parameter) }
}

export function toSandboxNodeData(previewTool = {}) {
  const parametersSchema = Array.isArray(previewTool.parameters_schema)
    ? previewTool.parameters_schema
    : []
  const credentialsSchema = Array.isArray(previewTool.credentials_schema)
    ? previewTool.credentials_schema
    : []
  const sourceParameters = previewTool.tool_parameters || {}
  const sourceCredentials = previewTool.credentials || {}
  const toolParameters = {}
  const credentials = {}

  for (const parameter of parametersSchema) {
    if (parameter?.name)
      toolParameters[parameter.name] = toToolParameter(sourceParameters[parameter.name], parameter)
  }
  for (const field of credentialsSchema) {
    if (field?.name)
      credentials[field.name] = sourceCredentials[field.name] ?? ''
  }

  return {
    ...previewTool,
    type: 'tool',
    title: previewTool.tool_label || previewTool.tool_name || '工具',
    parameters_schema: parametersSchema,
    tool_parameters: toolParameters,
    credentials_schema: credentialsSchema,
    credentials,
    tool_configurations: previewTool.tool_configurations || {},
    tool_node_version: previewTool.tool_node_version || '2',
  }
}
