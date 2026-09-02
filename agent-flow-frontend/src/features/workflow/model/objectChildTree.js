/**
 * Object / file nested field tree helpers (Dify object-child-tree-panel).
 * Kept free of availableVariables imports to avoid circular module init.
 */
import { normalizeVarChildren } from './variableOutputs.js'

export const OBJECT_TREE_MAX_DEPTH = 10

const SPECIAL_PREFIXES = new Set(['sys', 'env', 'conversation', 'rag'])

const SHOW_NAME_MAP = {
  'sys.query': 'query',
  'sys.files': 'files',
}

export function hasNestedChildren(variable) {
  return normalizeVarChildren(variable?.children).length > 0
}

export function getRootSelectorPath(variable) {
  const name = String(variable?.variable || '')
  if (
    variable?.isRagVariable
    || name.startsWith('sys.')
    || name.startsWith('env.')
    || name.startsWith('conversation.')
    || name.startsWith('rag.')
  ) {
    return name.split('.').filter(Boolean)
  }
  return name ? [name] : []
}

export function buildNestedValueSelector(nodeId, rootPath = [], childPath = []) {
  const path = [...(rootPath || []), ...(childPath || [])].map(String).filter(Boolean)
  if (!path.length)
    return []
  if (SPECIAL_PREFIXES.has(path[0]))
    return path
  if (!nodeId)
    return path
  return [nodeId, ...path]
}

export function listTreeFields(children) {
  return normalizeVarChildren(children).map(item => ({
    name: item.variable,
    type: item.type || 'string',
    des: item.des,
    children: item.children,
  }))
}

export function getTreeRootLabel(variable) {
  const name = variable?.variable || ''
  return SHOW_NAME_MAP[name] || name
}

export function normalizeRagPipelineVariables(list) {
  if (!Array.isArray(list))
    return []
  return list
    .filter(item => item && typeof item === 'object' && item.variable)
    .map(item => ({
      ...item,
      variable: String(item.variable),
      type: item.type || 'text-input',
      label: item.label || item.variable,
      belong_to_node_id: item.belong_to_node_id || 'shared',
      required: Boolean(item.required),
    }))
}
