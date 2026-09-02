// 各节点类型的输出变量定义（对齐 Dify constants.ts 中的 *_OUTPUT_STRUCT）
import { BlockEnum } from './constants.js'

/** 变量类型枚举（简化版） */
export const VarType = {
  string: 'string',
  number: 'number',
  boolean: 'boolean',
  object: 'object',
  array: 'array',
  arrayString: 'arrayString',
  file: 'file',
  arrayFile: 'arrayFile',
  arrayObject: 'arrayObject',
  arrayNumber: 'arrayNumber',
  arrayBoolean: 'arrayBoolean',
}

const CODE_OUTPUT_TYPE_MAP = {
  'array[string]': VarType.arrayString,
  'array[number]': VarType.arrayNumber,
  'array[boolean]': VarType.arrayBoolean,
  'array[object]': VarType.arrayObject,
}

/** Contrasts Dify OUTPUT_FILE_SUB_VARIABLES (no transfer_method). */
export const OUTPUT_FILE_SUB_VARIABLES = [
  { variable: 'type', type: VarType.string },
  { variable: 'size', type: VarType.number },
  { variable: 'name', type: VarType.string },
  { variable: 'url', type: VarType.string },
  { variable: 'extension', type: VarType.string },
  { variable: 'mime_type', type: VarType.string },
  { variable: 'related_id', type: VarType.string },
]

export const HUMAN_INPUT_OUTPUT_STRUCT = [
  { variable: '__action_id', type: VarType.string },
  { variable: '__action_value', type: VarType.string },
  { variable: '__rendered_content', type: VarType.string },
]

export const PARAMETER_EXTRACTOR_COMMON_STRUCT = [
  { variable: '__is_success', type: VarType.number },
  { variable: '__reason', type: VarType.string },
  { variable: '__usage', type: VarType.object },
]

/** 静态输出结构：key = BlockEnum */
const STATIC_OUTPUTS = {
  [BlockEnum.LLM]: [
    { variable: 'text', type: VarType.string, des: 'LLM 生成的文本' },
    { variable: 'reasoning_content', type: VarType.string, des: '推理链文本' },
    { variable: 'usage', type: VarType.object, des: 'Token 用量' },
  ],
  [BlockEnum.KnowledgeRetrieval]: [
    { variable: 'result', type: VarType.arrayObject, des: '检索结果' },
  ],
  [BlockEnum.Code]: [],
  [BlockEnum.TemplateTransform]: [
    { variable: 'output', type: VarType.string, des: '模板渲染结果' },
  ],
  [BlockEnum.HttpRequest]: [
    { variable: 'body', type: VarType.string },
    { variable: 'status_code', type: VarType.number },
    { variable: 'headers', type: VarType.object },
    { variable: 'files', type: VarType.arrayFile },
  ],
  [BlockEnum.Tool]: [
    { variable: 'text', type: VarType.string },
    { variable: 'files', type: VarType.arrayFile },
    { variable: 'json', type: VarType.arrayObject },
  ],
  [BlockEnum.QuestionClassifier]: [
    { variable: 'class_name', type: VarType.string },
    { variable: 'class_label', type: VarType.string },
    { variable: 'usage', type: VarType.object },
  ],
  [BlockEnum.ParameterExtractor]: [],
  [BlockEnum.DocExtractor]: [
    { variable: 'text', type: VarType.string, des: '提取的文本' },
  ],
  [BlockEnum.ListFilter]: [
    { variable: 'result', type: VarType.array, des: '过滤后的列表' },
    { variable: 'first_record', type: VarType.object },
    { variable: 'last_record', type: VarType.object },
  ],
  [BlockEnum.Agent]: [
    { variable: 'text', type: VarType.string },
    { variable: 'files', type: VarType.arrayFile },
    { variable: 'json', type: VarType.object },
  ],
  [BlockEnum.HumanInput]: [...HUMAN_INPUT_OUTPUT_STRUCT],
  [BlockEnum.Iteration]: [
    { variable: 'output', type: VarType.array, des: '迭代输出数组' },
  ],
  [BlockEnum.Loop]: [
    { variable: 'output', type: VarType.array, des: '循环输出' },
  ],
  [BlockEnum.VariableAssigner]: [
    { variable: 'output', type: VarType.string },
  ],
  [BlockEnum.DataSource]: [
    { variable: 'datasource_type', type: VarType.string },
  ],
}

/** Start 节点输入变量类型 -> VarType 映射 */
const INPUT_VAR_TYPE_MAP = {
  'text-input': VarType.string,
  paragraph: VarType.string,
  select: VarType.string,
  number: VarType.number,
  checkbox: VarType.boolean,
  file: VarType.file,
  'file-list': VarType.arrayFile,
  'json-object': VarType.object,
}

const RAG_INPUT_TYPE_MAP = {
  text: VarType.string,
  'text-input': VarType.string,
  paragraph: VarType.string,
  select: VarType.string,
  number: VarType.number,
  file: VarType.file,
  'file-list': VarType.arrayFile,
}

/**
 * Convert JSON Schema properties into Var[] children (Dify StructuredOutput shape).
 * @param {{ type?: string, properties?: Record<string, any> }|null} schema
 * @returns {object[]}
 */
export function schemaPropertiesToVars(schema) {
  if (!schema?.properties || typeof schema.properties !== 'object')
    return []
  return Object.entries(schema.properties).map(([key, prop]) => {
    const type = mapJsonSchemaType(prop)
    const child = {
      variable: key,
      type,
      des: prop?.description || prop?.title || undefined,
    }
    if (prop?.type === 'object' && prop.properties)
      child.children = schemaPropertiesToVars(prop)
    else if (prop?.type === 'array' && prop.items?.type === 'object' && prop.items.properties)
      child.children = schemaPropertiesToVars(prop.items)
    return child
  })
}

function mapJsonSchemaType(prop) {
  if (!prop)
    return VarType.string
  if (prop.type === 'array') {
    const item = prop.items?.type
    if (item === 'string')
      return VarType.arrayString
    if (item === 'number')
      return VarType.arrayNumber
    if (item === 'object')
      return VarType.arrayObject
    return VarType.array
  }
  if (prop.type === 'integer')
    return VarType.number
  return prop.type || VarType.string
}

/** Normalize Var.children: Var[] | StructuredOutput → Var[] */
export function normalizeVarChildren(children) {
  if (!children)
    return []
  if (Array.isArray(children))
    return children
  if (children.schema)
    return schemaPropertiesToVars(children.schema)
  return []
}

export function withFileChildren(variable) {
  if (!variable)
    return variable
  if (variable.type !== VarType.file && variable.type !== VarType.arrayFile)
    return variable
  if (normalizeVarChildren(variable.children).length)
    return variable
  return { ...variable, children: OUTPUT_FILE_SUB_VARIABLES.map(v => ({ ...v })) }
}

function attachFileChildren(vars) {
  return vars.map(withFileChildren)
}

function appendErrorStrategyVars(vars, data) {
  if (!data?.error_strategy)
    return vars
  return [
    ...vars,
    { variable: 'error_message', type: VarType.string, isException: true },
    { variable: 'error_type', type: VarType.string, isException: true },
  ]
}

/**
 * Map RAG pipeline variable definitions to picker vars.
 * Shared → rag.shared.name; node-scoped → rag.{nodeId}.name
 */
export function mapRagPipelineVars(ragVariables = [], belongToNodeId = 'shared') {
  return (ragVariables || [])
    .filter(item => (item.belong_to_node_id || 'shared') === belongToNodeId)
    .map(item => ({
      variable: belongToNodeId === 'shared'
        ? `rag.shared.${item.variable}`
        : `rag.${belongToNodeId}.${item.variable}`,
      type: RAG_INPUT_TYPE_MAP[item.type] || VarType.string,
      des: item.label || item.variable,
      isRagVariable: true,
    }))
}

/**
 * 获取单个节点的可引用输出变量列表。
 * Contrasts Dify toNodeOutputVars / formatItem.
 * @param {object} node
 * @param {{ isChatMode?: boolean, ragPipelineVariables?: Array }} [options]
 * @returns {{ variable: string, type: string, des?: string, children?: object[] }[]}
 */
export function getNodeOutputVars(node, { isChatMode = false, ragPipelineVariables = [] } = {}) {
  if (!node?.data)
    return []
  const type = node.data.type
  const data = node.data
  let vars = []

  if (type === BlockEnum.Start) {
    vars = (data.variables || []).map((v) => {
      const mapped = {
        variable: v.variable,
        type: INPUT_VAR_TYPE_MAP[v.type] || VarType.string,
        des: v.label || v.variable,
      }
      if (v.type === 'json-object' && v.json_schema)
        mapped.children = { schema: typeof v.json_schema === 'string' ? safeParseSchema(v.json_schema) : v.json_schema }
      return mapped
    })
    if (isChatMode) {
      vars.push({
        variable: 'sys.query',
        type: VarType.string,
        des: '用户输入的对话内容（userinput.query）',
      })
    }
    vars.push({
      variable: 'sys.files',
      type: VarType.arrayFile,
      des: '用户上传的文件（userinput.files）',
    })
  }
  else if (type === BlockEnum.Code && data.outputs) {
    vars = Object.entries(data.outputs).map(([key, val]) => ({
      variable: key,
      type: CODE_OUTPUT_TYPE_MAP[val?.type] || val?.type || VarType.string,
      children: val?.children ?? null,
    }))
  }
  else if (type === BlockEnum.ParameterExtractor) {
    const params = (data.parameters || []).map(p => ({
      variable: p.name,
      type: CODE_OUTPUT_TYPE_MAP[p.type] || p.type || VarType.string,
      des: p.description,
    }))
    vars = [...params, ...PARAMETER_EXTRACTOR_COMMON_STRUCT]
  }
  else if (type === BlockEnum.HumanInput) {
    const actionVars = (data.user_actions || []).flatMap(a => [
      { variable: `${a.id}_approved`, type: VarType.boolean },
      { variable: `${a.id}_comment`, type: VarType.string },
    ])
    const formVars = (Array.isArray(data.inputs) ? data.inputs : [])
      .filter(item => item?.output_variable_name || item?.variable || item?.name)
      .map(item => ({
        variable: item.output_variable_name || item.variable || item.name,
        type: item.type === 'file-list' ? VarType.arrayFile : (INPUT_VAR_TYPE_MAP[item.type] || VarType.string),
        des: item.label,
      }))
    vars = [...formVars, ...actionVars, ...HUMAN_INPUT_OUTPUT_STRUCT]
  }
  else if (type === BlockEnum.LLM) {
    vars = [...(STATIC_OUTPUTS[BlockEnum.LLM] || [])]
    if (
      data.structured_output_enabled
      && data.structured_output?.schema?.properties
      && Object.keys(data.structured_output.schema.properties).length > 0
    ) {
      vars.push({
        variable: 'structured_output',
        type: VarType.object,
        children: data.structured_output,
      })
    }
  }
  else if (type === BlockEnum.DocExtractor) {
    vars = [{
      variable: 'text',
      type: data.is_array_file ? VarType.arrayString : VarType.string,
      des: '提取的文本',
    }]
  }
  else if (type === BlockEnum.ListFilter) {
    const listType = data.var_type || VarType.array
    const itemType = data.item_var_type || VarType.object
    vars = [
      { variable: 'result', type: listType, des: '过滤后的列表' },
      { variable: 'first_record', type: itemType },
      { variable: 'last_record', type: itemType },
    ]
  }
  else if (type === BlockEnum.Iteration) {
    vars = [{
      variable: 'output',
      type: data.output_type || VarType.array,
      des: '迭代输出数组',
    }]
  }
  else if (type === BlockEnum.Loop) {
    const loopVars = (data.loop_variables || []).map(v => ({
      variable: v.label || v.variable || v.name,
      type: v.value_type || v.type || VarType.string,
      isLoopVariable: true,
    })).filter(v => v.variable)
    vars = loopVars.length
      ? loopVars
      : [...(STATIC_OUTPUTS[BlockEnum.Loop] || [])]
  }
  else if (type === BlockEnum.VariableAssigner) {
    if (data.advanced_settings?.group_enabled && Array.isArray(data.advanced_settings.groups)) {
      vars = data.advanced_settings.groups.map(group => ({
        variable: group.group_name,
        type: VarType.object,
        children: [{ variable: 'output', type: group.output_type || VarType.string }],
      }))
    }
    else {
      vars = [{ variable: 'output', type: data.output_type || VarType.string }]
    }
  }
  else if (type === BlockEnum.DataSource || type === 'datasource') {
    vars = [
      { variable: 'datasource_type', type: VarType.string },
      ...(data.provider_type === 'local_file' || data.datasource_type === 'local_file'
        ? [{ variable: 'file', type: VarType.file }]
        : []),
      ...mapRagPipelineVars(ragPipelineVariables, node.id),
      ...schemaPropertiesToVars(data._datasourceOutputSchema),
    ]
  }
  else if (type === 'agent-v2' || (type === BlockEnum.Agent && data.agent_binding)) {
    const declared = Array.isArray(data.agent_declared_outputs) && data.agent_declared_outputs.length
      ? data.agent_declared_outputs
      : [
          { name: 'text', type: 'string', description: '自由文本回复' },
          { name: 'files', type: 'array', description: 'Agent 产出的文件', array_item: { type: 'file' } },
          { name: 'json', type: 'object', description: '结构化 JSON' },
        ]
    vars = declared.map(item => ({
      variable: item.name,
      type: item.type === 'array' && item.array_item?.type === 'file'
        ? VarType.arrayFile
        : (item.type || VarType.string),
      des: item.description || '',
    })).filter(item => item.variable)
  }
  else if (type === BlockEnum.TriggerWebhook && Array.isArray(data.variables)) {
    vars = data.variables.map(v => ({
      variable: v.variable || v.name,
      type: INPUT_VAR_TYPE_MAP[v.type] || v.value_type || VarType.string,
      des: v.label,
    })).filter(v => v.variable)
  }
  else {
    vars = STATIC_OUTPUTS[type] ? [...STATIC_OUTPUTS[type]] : []
  }

  vars = attachFileChildren(vars)
  return appendErrorStrategyVars(vars, data)
}

function safeParseSchema(raw) {
  try {
    return JSON.parse(raw)
  }
  catch {
    return null
  }
}

/** 迭代/循环容器内子节点额外可用的变量 */
export function getContainerInnerVars(parentNode) {
  if (!parentNode)
    return []
  const type = parentNode.data?.type
  if (type === BlockEnum.Iteration) {
    const itemType = parentNode.data?.output_type === VarType.arrayFile
      ? VarType.file
      : VarType.object
    return attachFileChildren([
      { variable: 'item', type: itemType, des: '当前迭代项' },
      { variable: 'index', type: VarType.number, des: '当前迭代索引' },
    ])
  }
  if (type === BlockEnum.Loop) {
    return [
      { variable: 'item', type: VarType.object, des: '当前循环项' },
      { variable: 'index', type: VarType.number, des: '当前循环索引' },
    ]
  }
  return []
}

/** 格式化 value_selector 为可读文本 */
export function formatValueSelector(selector) {
  if (!selector)
    return ''
  if (typeof selector === 'string')
    return selector
  if (Array.isArray(selector))
    return selector.join('.')
  return String(selector)
}

/** value_selector -> Dify 模板语法 {{#node.var#}} */
export function selectorToTemplate(selector) {
  if (!selector || !Array.isArray(selector) || selector.length < 2)
    return ''
  return `{{#${selector.join('.')}#}}`
}

export { parseSelectorInput } from './availableVariables.js'
