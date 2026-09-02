/**
 * Agent-v2 declared outputs helpers.
 * Contrasts Dify nodes/agent-v2/output-variables.ts
 */

export const DEFAULT_AGENT_DECLARED_OUTPUTS = [
  {
    name: 'text',
    type: 'string',
    required: false,
    description: '自由文本回复',
  },
  {
    name: 'files',
    type: 'array',
    required: false,
    description: 'Agent 产出的文件',
    array_item: { type: 'file' },
  },
  {
    name: 'json',
    type: 'object',
    required: false,
    description: '结构化 JSON',
  },
]

/**
 * @param {object} [nodeData]
 * @returns {Array<{ name: string, type: string, description?: string, required?: boolean, array_item?: object }>}
 */
export function getAgentDeclaredOutputs(nodeData = {}) {
  const list = nodeData.agent_declared_outputs
  if (Array.isArray(list) && list.length)
    return list.map(normalizeDeclaredOutput).filter(Boolean)
  return DEFAULT_AGENT_DECLARED_OUTPUTS.map(item => ({ ...item }))
}

/**
 * @param {unknown} item
 */
const SUPPORTED_OUTPUT_TYPES = new Set(['string', 'number', 'boolean', 'object', 'array', 'file'])

export function normalizeDeclaredOutput(item) {
  if (!item || typeof item !== 'object')
    return null
  const name = String(item.name || '').trim()
  if (!name)
    return null
  const rawType = String(item.type || 'string')
  const type = SUPPORTED_OUTPUT_TYPES.has(rawType) ? rawType : 'string'
  const out = {
    name,
    type,
    required: item.required !== undefined ? Boolean(item.required) : false,
    description: String(item.description || ''),
  }
  if (type === 'array' && item.array_item && typeof item.array_item === 'object')
    out.array_item = { type: String(item.array_item.type || 'object') }
  if (type === 'file')
    out.file = item.file && typeof item.file === 'object' ? item.file : { extensions: [], mime_types: [] }
  return out
}

/**
 * @param {ReturnType<typeof getAgentDeclaredOutputs>} outputs
 * @returns {{ variable: string, type: string, des: string }[]}
 */
export function declaredOutputsToPanelVars(outputs = []) {
  return outputs.map((item) => ({
    variable: item.name,
    type: item.type === 'array' && item.array_item?.type === 'file'
      ? 'arrayFile'
      : item.type,
    des: item.description || '',
  }))
}

/**
 * @param {Array} outputs
 * @param {{ name: string, type?: string, description?: string }} draft
 */
export function addDeclaredOutput(outputs, draft) {
  const next = normalizeDeclaredOutput({
    name: draft?.name,
    type: draft?.type || 'string',
    description: draft?.description || '',
  })
  if (!next)
    return outputs
  if (outputs.some(item => item.name === next.name))
    return outputs
  return [...outputs, next]
}

/**
 * @param {Array} outputs
 * @param {string} name
 */
export function removeDeclaredOutput(outputs, name) {
  const defaults = new Set(DEFAULT_AGENT_DECLARED_OUTPUTS.map(item => item.name))
  if (defaults.has(name))
    return outputs
  return outputs.filter(item => item.name !== name)
}

/**
 * Normalize memory window for chatflow agent nodes.
 * @param {unknown} memory
 */
export function normalizeAgentMemory(memory) {
  const window = memory?.window || {}
  return {
    window: {
      enabled: window.enabled !== false,
      size: Number.isFinite(Number(window.size)) ? Number(window.size) : 50,
    },
  }
}
