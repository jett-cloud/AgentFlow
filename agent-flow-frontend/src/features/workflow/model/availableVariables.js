/**
 * Pure available-variable helpers (no Vue).
 * Contrasts Dify:
 *   constants.getGlobalVars
 *   variable/utils.toNodeOutputVars + formatItem(Start)
 *   var-reference-vars.helpers.getValueSelector / getVariableDisplayName
 */
import { BlockEnum } from './constants.js'
import {
  getNodeOutputVars,
  getContainerInnerVars,
  mapRagPipelineVars,
  normalizeVarChildren,
  OUTPUT_FILE_SUB_VARIABLES,
} from './variableOutputs.js'

/** Contrasts Dify VAR_SHOW_NAME_MAP — picker shows short names for Start sys vars. */
export const VAR_SHOW_NAME_MAP = {
  'sys.query': 'query',
  'sys.files': 'files',
}

/**
 * Contrasts Dify getGlobalVars.
 * Variable names keep the `sys.` prefix; selecting them yields ['sys', 'user_id'].
 * query/files are NOT here — they hang off Start outputs.
 */
export function getGlobalVars(isChatMode = false) {
  return [
    ...(isChatMode
      ? [
          { variable: 'sys.dialogue_count', type: 'number', des: '当前会话轮次' },
          { variable: 'sys.conversation_id', type: 'string', des: '当前会话 ID' },
        ]
      : []),
    { variable: 'sys.user_id', type: 'string', des: '当前终端用户 ID' },
    { variable: 'sys.app_id', type: 'string', des: '当前应用 ID' },
    { variable: 'sys.workflow_id', type: 'string', des: '当前工作流 ID' },
    { variable: 'sys.workflow_run_id', type: 'string', des: '当前工作流运行 ID' },
    ...(!isChatMode
      ? [{ variable: 'sys.timestamp', type: 'number', des: '工作流触发时间戳' }]
      : []),
  ]
}

export function getVariableDisplayName(variable = '') {
  return VAR_SHOW_NAME_MAP[variable] || variable
}

/** Contrasts Dify isSystemVar */
export function isSystemVar(valueSelector = []) {
  if (!Array.isArray(valueSelector) || !valueSelector.length)
    return false
  return valueSelector[0] === 'sys' || valueSelector[1] === 'sys'
}

/**
 * Contrasts Dify isGlobalVar — system vars excluding query/files.
 */
export function isGlobalVar(valueSelector = []) {
  if (!isSystemVar(valueSelector))
    return false
  const second = valueSelector[1]
  if (second === 'query' || second === 'files')
    return false
  return true
}

/** Contrasts Dify isENV */
export function isENV(valueSelector = []) {
  return Array.isArray(valueSelector) && valueSelector[0] === 'env'
}

/** Contrasts Dify isConversationVar */
export function isConversationVar(valueSelector = []) {
  return Array.isArray(valueSelector) && valueSelector[0] === 'conversation'
}

/** Contrasts Dify isRagVariableVar */
export function isRagVariableVar(valueSelector = []) {
  return Array.isArray(valueSelector) && valueSelector[0] === 'rag'
}

export function isSpecialVarPrefix(prefix) {
  return ['sys', 'env', 'conversation', 'rag'].includes(prefix)
}

/**
 * Contrasts Dify getValueSelector:
 *   sys.* / env.* / conversation.* / rag.* → split on '.'
 *   else → [nodeId, variable]
 * Nested: pass pathSegments after the root variable via toValueSelectorWithPath.
 */
export function toValueSelector(nodeId, variable) {
  const name = String(variable || '')
  if (
    name.startsWith('sys.')
    || name.startsWith('env.')
    || name.startsWith('conversation.')
    || name.startsWith('rag.')
  ) {
    return name.split('.').filter(Boolean)
  }
  if (!nodeId)
    return name ? [name] : []
  return [nodeId, name]
}

/**
 * Build selector from a flattened path (may already include special prefixes).
 * @param {string} nodeId
 * @param {string[]} selectorPath e.g. ['text'] | ['files','name'] | ['sys','files','name']
 */
export function toValueSelectorFromPath(nodeId, selectorPath = []) {
  const path = (selectorPath || []).map(String).filter(Boolean)
  if (!path.length)
    return []
  if (isSpecialVarPrefix(path[0]))
    return path
  if (!nodeId)
    return path
  return [nodeId, ...path]
}

/**
 * Flatten vars (with children) into picker rows.
 * Each row has selectorPath usable with toValueSelectorFromPath(nodeId, path).
 */
export function flattenVarsForPicker(vars = []) {
  const rows = []

  function walk(list, path = [], displayParts = []) {
    for (const v of list || []) {
      const children = normalizeVarChildren(v.children)
      const isSpecialRoot = !path.length && (
        String(v.variable || '').startsWith('sys.')
        || String(v.variable || '').startsWith('env.')
        || String(v.variable || '').startsWith('conversation.')
        || String(v.variable || '').startsWith('rag.')
        || v.isRagVariable
      )
      const nextPath = isSpecialRoot
        ? String(v.variable).split('.').filter(Boolean)
        : [...path, v.variable]
      const nextDisplay = [...displayParts, getVariableDisplayName(v.variable)]
      rows.push({
        variable: v.variable,
        type: v.type,
        des: v.des,
        isRagVariable: v.isRagVariable,
        isException: v.isException,
        selectorPath: nextPath,
        displayPath: nextDisplay.join('.'),
        hasChildren: children.length > 0,
      })
      if (children.length)
        walk(children, nextPath, nextDisplay)
    }
  }

  walk(vars)
  return rows
}

/**
 * Parse UI / stored selector input into value_selector[].
 * Strings are split on '.' (Dify token form: sys.query → ['sys','query']).
 */
export function parseSelectorInput(input) {
  if (Array.isArray(input))
    return input.map(String).filter(Boolean)
  if (typeof input === 'string' && input.trim())
    return input.trim().split('.').filter(Boolean)
  return []
}

const SKIP_SELECTOR_KEYS = new Set([
  'options',
  'required',
  'dataset_ids',
  'allowed_file_types',
  'allowed_file_extensions',
  'allowed_file_upload_methods',
  'classes',
])
const SELECTOR_KEYS = new Set([
  'selector',
  'value_selector',
  'variable_selector',
  'iterator_selector',
  'query_variable_selector',
  'query_attachment_selector',
  'output_selector',
  'variable',
  'file',
])
const ARRAY_NO_DRILL = new Set(['array', 'arrayObject', 'arrayString', 'arrayNumber', 'arrayBoolean'])

function valueMode(parent) {
  if (!parent || typeof parent !== 'object' || Array.isArray(parent))
    return ''
  const raw = parent.value_type || parent.input_type
  if (raw === 'variable' || raw === 'constant' || raw === 'mixed')
    return raw
  if (parent.type === 'variable' || parent.type === 'constant' || parent.type === 'mixed')
    return parent.type
  return ''
}

function fieldScanKind(key, parent) {
  if (SKIP_SELECTOR_KEYS.has(key))
    return 'skip'
  const mode = valueMode(parent)
  if ((key === 'value' || key === 'text') && mode === 'constant')
    return 'literal'
  if (key === 'value' && mode === 'variable')
    return 'selector'
  if (key === 'query')
    return 'query'
  if (key === 'variables')
    return 'selector_list'
  if (SELECTOR_KEYS.has(key) || String(key).endsWith('_selector'))
    return 'selector'
  return 'walk'
}

function isSelectorList(value) {
  return Array.isArray(value) && value.length >= 2 && value.every(item => typeof item === 'string' && item)
}

/**
 * Walk node data and collect value_selector arrays + {{#...#}} tokens.
 * Constant strings are not references even when they contain ``{{#...#}}``.
 * @returns {string[][]}
 */
export function collectUsedSelectors(data) {
  const found = []
  const seen = new Set()

  function push(selector) {
    if (!Array.isArray(selector) || selector.length < 2)
      return
    const key = selector.join('.')
    if (seen.has(key))
      return
    seen.add(key)
    found.push(selector.map(String))
  }

  function walk(val, key = '', parent = null) {
    if (val == null)
      return
    const kind = key ? fieldScanKind(key, parent) : 'walk'
    if (kind === 'literal')
      return
    if (kind === 'skip') {
      if (val && typeof val === 'object' && !Array.isArray(val)) {
        for (const [childKey, childVal] of Object.entries(val))
          walk(childVal, childKey, val)
      }
      return
    }
    if (typeof val === 'string') {
      const re = /\{\{#(.*?)#\}\}/g
      let match = re.exec(val)
      while (match) {
        push(parseSelectorInput(match[1]))
        match = re.exec(val)
      }
      return
    }
    if (kind === 'query') {
      if (Array.isArray(val) && val.length > 1 && val.every(isSelectorList))
        return
      if (Array.isArray(val) && val.length === 1 && isSelectorList(val[0])) {
        push(val[0])
        return
      }
      if (isSelectorList(val)) {
        push(val)
        return
      }
    }
    if (kind === 'selector' && isSelectorList(val)) {
      push(val)
      return
    }
    if (kind === 'selector_list' && Array.isArray(val)) {
      for (const item of val) {
        if (isSelectorList(item))
          push(item)
        else
          walk(item, key, parent)
      }
      return
    }
    if (Array.isArray(val)) {
      for (const item of val)
        walk(item, key, parent)
      return
    }
    if (typeof val === 'object') {
      for (const [childKey, childVal] of Object.entries(val))
        walk(childVal, childKey, val)
    }
  }

  walk(data)
  return found
}

/**
 * Whether a node-output selector is present in available groups.
 * sys/env/conversation/rag must match a declared group entry.
 */
export function isSelectorAvailable(selector, availableGroups = []) {
  if (!Array.isArray(selector) || selector.length < 2)
    return true
  if (isSpecialVarPrefix(selector[0])) {
    for (const group of availableGroups) {
      if (matchVarPath(group.vars || [], selector) || matchVarPath(group.vars || [], selector.slice(1)))
        return true
    }
    return false
  }
  const group = availableGroups.find(item => item.nodeId === selector[0])
  if (!group)
    return false
  return matchVarPath(group.vars || [], selector.slice(1))
}

export function resolveAvailableVariable(selector, availableGroups = []) {
  if (!Array.isArray(selector) || selector.length < 2)
    return null
  if (isSpecialVarPrefix(selector[0])) {
    for (const group of availableGroups) {
      const found = findDeclaredVariable(group.vars || [], selector) || findDeclaredVariable(group.vars || [], selector.slice(1))
      if (found)
        return found
    }
    return null
  }
  const group = availableGroups.find(item => item.nodeId === selector[0])
  if (!group)
    return null
  return findDeclaredVariable(group.vars || [], selector.slice(1))
}

function findDeclaredVariable(vars, path) {
  if (!Array.isArray(path) || !path.length)
    return null
  const dotted = path.join('.')
  for (const v of vars) {
    if (v.variable === dotted)
      return v
    if (v.variable !== path[0])
      continue
    const rest = path.slice(1)
    if (!rest.length)
      return v
    const children = normalizeVarChildren(v.children)
    if (children.length)
      return findDeclaredVariable(children, rest)
    if (ARRAY_NO_DRILL.has(v.type))
      return null
    if (v.type === 'file' || v.type === 'arrayFile')
      return findDeclaredVariable(OUTPUT_FILE_SUB_VARIABLES, rest)
    return null
  }
  return null
}

function matchVarPath(vars, path) {
  if (!path.length)
    return true
  const dotted = path.join('.')
  for (const v of vars) {
    if (v.variable === dotted)
      return true
    if (v.variable !== path[0])
      continue
    const rest = path.slice(1)
    if (!rest.length)
      return true
    if (ARRAY_NO_DRILL.has(v.type))
      return false
    const children = normalizeVarChildren(v.children)
    if (children.length)
      return matchVarPath(children, rest)
    if (v.type === 'file' || v.type === 'arrayFile')
      return matchVarPath(OUTPUT_FILE_SUB_VARIABLES, rest)
    if (v.type === 'object' || !v.type)
      return true
    return false
  }
  return false
}

export function filterVarGroupsByType(groups = [], { hideFileVars = false, filterVar } = {}) {
  const customPredicate = typeof filterVar === 'function' ? filterVar : () => true
  const predicate = v => (
    (!hideFileVars || (v.type !== 'file' && v.type !== 'arrayFile'))
    && customPredicate(v)
  )

  function filterTree(vars) {
    return (vars || [])
      .map((v) => {
        const children = normalizeVarChildren(v.children)
        const nextChildren = children.length ? filterTree(children) : []
        const selfOk = predicate(v)
        if (!selfOk && !nextChildren.length)
          return null
        return {
          ...v,
          children: nextChildren.length ? nextChildren : undefined,
        }
      })
      .filter(Boolean)
  }

  return groups
    .map(group => ({
      ...group,
      vars: filterTree(group.vars),
    }))
    .filter(group => group.vars.length > 0)
}

/**
 * 从 edges 反向 BFS，找出所有能到达 nodeId 的上游节点 id。
 */
export function getBeforeNodeIds(nodeId, edges) {
  const before = new Set()
  const queue = [nodeId]
  const visited = new Set([nodeId])

  while (queue.length) {
    const current = queue.shift()
    for (const e of edges) {
      if (e.target === current && !visited.has(e.source)) {
        visited.add(e.source)
        before.add(e.source)
        queue.push(e.source)
      }
    }
  }
  return before
}

/**
 * Upstream node output groups (Start includes sys.query / sys.files).
 * @returns {{ nodeId: string, title: string, nodeType: string, vars: object[], isStartNode?: boolean }[]}
 */
export function buildAvailableVariables({
  nodeId,
  nodes,
  edges,
  isChatMode = false,
  ragPipelineVariables = [],
}) {
  if (!nodeId || !nodes?.length) return []

  const current = nodes.find(n => n.id === nodeId)
  if (!current) return []

  const parentId = current.parentNode || current.parentId
  const isInContainer = !!parentId

  let candidateNodes
  if (isInContainer) {
    const siblings = nodes.filter(n => (n.parentNode || n.parentId) === parentId && n.id !== nodeId)
    const outerBefore = getBeforeNodeIds(parentId, edges)
    const outerNodes = nodes.filter(n => outerBefore.has(n.id) && !(n.parentNode || n.parentId))
    candidateNodes = [...siblings, ...outerNodes]
    const parentNode = nodes.find(n => n.id === parentId)
    if (parentNode) {
      const innerVars = getContainerInnerVars(parentNode, { nodes })
      if (innerVars.length) {
        candidateNodes = [{
          id: parentId,
          data: { type: parentNode.data?.type, title: '迭代/循环上下文' },
          _innerVars: innerVars,
        }, ...candidateNodes]
      }
    }
  }
  else {
    const beforeIds = getBeforeNodeIds(nodeId, edges)
    candidateNodes = nodes.filter(n => beforeIds.has(n.id) && !(n.parentNode || n.parentId))
  }

  const result = []
  for (const node of candidateNodes) {
    if (node._innerVars) {
      result.push({
        nodeId: node.id,
        title: node.data?.title || '上下文',
        nodeType: node.data?.type,
        vars: node._innerVars,
      })
      continue
    }
    const vars = getNodeOutputVars(node, { isChatMode, ragPipelineVariables })
    if (vars.length === 0) continue
    if ([BlockEnum.IterationStart, BlockEnum.LoopStart].includes(node.data?.type)) continue
    result.push({
      nodeId: node.id,
      title: node.data?.title || node.id,
      nodeType: node.data?.type,
      vars,
      isStartNode: node.data?.type === BlockEnum.Start,
    })
  }
  return result
}

/**
 * Build env / conversation / SYSTEM / RAG groups.
 * Contrasts Dify toNodeOutputVars ENV_NODE / CHAT_VAR_NODE / GLOBAL_VAR_NODE / rag.
 */
export function buildSpecialVarGroups({
  isChatMode = false,
  environmentVariables = [],
  conversationVariables = [],
  ragPipelineVariables = [],
} = {}) {
  const groups = []

  if (environmentVariables.length) {
    groups.push({
      nodeId: 'env',
      title: '环境变量',
      nodeType: 'env',
      vars: environmentVariables.map(variable => ({
        variable: `env.${variable.name}`,
        type: variable.value_type || variable.type || 'string',
        des: variable.description,
      })),
    })
  }

  if (isChatMode && conversationVariables.length) {
    groups.push({
      nodeId: 'conversation',
      title: '会话变量',
      nodeType: 'conversation',
      vars: conversationVariables.map(variable => ({
        variable: `conversation.${variable.name}`,
        type: variable.value_type || variable.type || 'string',
        des: variable.description,
      })),
    })
  }

  const sharedRag = mapRagPipelineVars(ragPipelineVariables, 'shared')
  if (sharedRag.length) {
    groups.push({
      nodeId: 'rag',
      title: 'SHARED INPUTS',
      nodeType: 'rag',
      vars: sharedRag,
    })
  }

  groups.push({
    nodeId: 'global',
    title: '全局变量',
    nodeType: 'global',
    vars: getGlobalVars(isChatMode),
  })

  return groups
}

/**
 * Direct children of an iteration container (for output_selector scope).
 * Nested container internals are not included.
 */
export function buildDirectChildOutputGroups(containerNode, nodes = []) {
  if (!containerNode?.id)
    return []
  const groups = []
  for (const child of nodes) {
    const parent = child.parentNode || child.parentId
    if (parent !== containerNode.id)
      continue
    const vars = getNodeOutputVars(child)
    if (!vars.length)
      continue
    groups.push({
      nodeId: child.id,
      title: child.data?.title || child.id,
      nodeType: child.data?.type,
      vars,
    })
  }
  return groups
}

export function selectAvailableVariableGroups({
  nodeGroups = [],
  directChildGroups = [],
  specialGroups = [],
  includeDirectChildren = false,
} = {}) {
  return includeDirectChildren
    ? directChildGroups
    : [...nodeGroups, ...specialGroups]
}
