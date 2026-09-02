// src/views/copilot/components/workflow/core/workflowInit.js
//
// 对齐 Dify web/app/components/workflow/utils/workflow-init.ts
// 在 graph -> vue-flow 转换后做节点/边预处理。

import {
  BlockEnum,
  CUSTOM_ITERATION_START_NODE,
  CUSTOM_LOOP_START_NODE,
  DEFAULT_SOURCE_HANDLE,
  DEFAULT_TARGET_HANDLE,
  NESTED_ELEMENT_Z_INDEX,
} from './constants.js'
import { makeIterationStartNode, makeLoopStartNode } from './dsl.js'

const WHITE = 'WHITE'
const GRAY = 'GRAY'
const BLACK = 'BLACK'

function branchNameCorrect(branches) {
  if (!branches?.length) return branches
  if (branches.length === 2) {
    return branches.map((branch) => ({
      ...branch,
      name: branch.id === 'false' ? 'ELSE' : 'IF',
    }))
  }
  return branches.map((branch, index) => ({
    ...branch,
    name: branch.id === 'false' ? 'ELSE' : index === 0 ? 'IF' : `ELIF ${index}`,
  }))
}

function isCyclicUtil(nodeId, color, adjList, stack) {
  color[nodeId] = GRAY
  stack.push(nodeId)

  for (const childId of adjList[nodeId] || []) {
    if (color[childId] === GRAY) {
      stack.push(childId)
      return true
    }
    if (color[childId] === WHITE && isCyclicUtil(childId, color, adjList, stack)) return true
  }

  color[nodeId] = BLACK
  if (stack.length > 0 && stack[stack.length - 1] === nodeId) stack.pop()
  return false
}

function getCycleEdgeIds(nodes, edges) {
  const adjList = {}
  const color = {}
  const stack = []

  for (const node of nodes) {
    color[node.id] = WHITE
    adjList[node.id] = []
  }
  for (const edge of edges) {
    adjList[edge.source]?.push(edge.target)
  }

  for (const node of nodes) {
    if (color[node.id] === WHITE) isCyclicUtil(node.id, color, adjList, stack)
  }

  if (stack.length === 0) return new Set()

  const cycleNodes = new Set(stack)
  return new Set(
    edges
      .filter((e) => cycleNodes.has(e.source) && cycleNodes.has(e.target))
      .map((e) => e.id),
  )
}

function getConnectedHandleIds(nodeId, edges) {
  const sourceHandles = edges
    .filter((e) => e.source === nodeId)
    .map((e) => e.sourceHandle || DEFAULT_SOURCE_HANDLE)
  const targetHandles = edges
    .filter((e) => e.target === nodeId)
    .map((e) => e.targetHandle || DEFAULT_TARGET_HANDLE)
  return { sourceHandles, targetHandles }
}

function nextAvailableNodeId(baseId, nodesMap) {
  if (!nodesMap[baseId]) return baseId
  let suffix = 1
  while (nodesMap[`${baseId}${suffix}`]) suffix += 1
  return `${baseId}${suffix}`
}

function ensureContainerStartNodes(nodes, edges) {
  const nodesMap = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const extraNodes = []
  const extraEdges = []

  for (const node of nodes) {
    const dataType = node.data?.type
    if (dataType === BlockEnum.Iteration) {
      const configuredStartId = node.data.start_node_id
      const existing = configuredStartId ? nodesMap[configuredStartId] : null
      const validType =
        existing?.type === 'iteration-start' ||
        existing?.type === CUSTOM_ITERATION_START_NODE
      if (!validType) {
        const startNode = makeIterationStartNode(node.id)
        startNode.id = existing
          ? nextAvailableNodeId(`${node.id}start`, nodesMap)
          : (configuredStartId || nextAvailableNodeId(`${node.id}start`, nodesMap))
        extraNodes.push(startNode)
        nodesMap[startNode.id] = startNode
        node.data.start_node_id = startNode.id

        const existingParentId = existing?.parentNode || existing?.parentId
        const alreadyConnected = edges.some(edge => (
          edge.source === startNode.id
          && edge.target === existing?.id
        ))
        if (existing && existingParentId === node.id && !alreadyConnected) {
          extraEdges.push({
            id: `${startNode.id}-${DEFAULT_SOURCE_HANDLE}-${existing.id}-${DEFAULT_TARGET_HANDLE}`,
            type: 'custom',
            source: startNode.id,
            sourceHandle: DEFAULT_SOURCE_HANDLE,
            target: existing.id,
            targetHandle: DEFAULT_TARGET_HANDLE,
            data: {
              sourceType: BlockEnum.IterationStart,
              targetType: existing.data?.type,
              isInIteration: true,
              iteration_id: node.id,
            },
            zIndex: NESTED_ELEMENT_Z_INDEX,
          })
        }
      } else {
        existing.parentNode = node.id
        existing.extent = 'parent'
        node.data.start_node_id = existing.id
      }
    }

    if (dataType === BlockEnum.Loop) {
      const configuredStartId = node.data.start_node_id
      const existing = configuredStartId ? nodesMap[configuredStartId] : null
      const validType =
        existing?.type === 'loop-start' || existing?.type === CUSTOM_LOOP_START_NODE
      if (!validType) {
        const startNode = makeLoopStartNode(node.id)
        startNode.id = existing
          ? nextAvailableNodeId(`${node.id}start`, nodesMap)
          : (configuredStartId || nextAvailableNodeId(`${node.id}start`, nodesMap))
        extraNodes.push(startNode)
        nodesMap[startNode.id] = startNode
        node.data.start_node_id = startNode.id

        const existingParentId = existing?.parentNode || existing?.parentId
        const alreadyConnected = edges.some(edge => (
          edge.source === startNode.id
          && edge.target === existing?.id
        ))
        if (existing && existingParentId === node.id && !alreadyConnected) {
          extraEdges.push({
            id: `${startNode.id}-${DEFAULT_SOURCE_HANDLE}-${existing.id}-${DEFAULT_TARGET_HANDLE}`,
            type: 'custom',
            source: startNode.id,
            sourceHandle: DEFAULT_SOURCE_HANDLE,
            target: existing.id,
            targetHandle: DEFAULT_TARGET_HANDLE,
            data: {
              sourceType: BlockEnum.LoopStart,
              targetType: existing.data?.type,
              isInLoop: true,
              loop_id: node.id,
            },
            zIndex: NESTED_ELEMENT_Z_INDEX,
          })
        }
      } else {
        existing.parentNode = node.id
        existing.extent = 'parent'
        node.data.start_node_id = existing.id
      }
    }
  }

  return { nodes: extraNodes, edges: extraEdges }
}

function buildChildrenMap(nodes) {
  const map = {}
  for (const node of nodes) {
    const parentId = node.parentNode || node.parentId
    if (!parentId) continue
    if (!map[parentId]) map[parentId] = []
    map[parentId].push({
      nodeId: node.id,
      nodeType: node.data?.type || node.type,
    })
  }
  return map
}

/**
 * 预处理 vue-flow 图（加载草稿 / 粘贴 / 初始化后调用）
 * @param {object[]} nodes
 * @param {object[]} edges
 * @returns {{ nodes: object[], edges: object[] }}
 */
export function preprocessFlowGraph(nodes = [], edges = []) {
  let nextNodes = [...nodes]
  let nextEdges = [...edges]

  const cycleEdgeIds = getCycleEdgeIds(nextNodes, nextEdges)
  if (cycleEdgeIds.size > 0) {
    nextEdges = nextEdges.filter((e) => !cycleEdgeIds.has(e.id))
  }

  const extraStart = ensureContainerStartNodes(nextNodes, nextEdges)
  if (extraStart.nodes.length) nextNodes = [...nextNodes, ...extraStart.nodes]
  if (extraStart.edges.length) nextEdges = [...nextEdges, ...extraStart.edges]

  const childrenMap = buildChildrenMap(nextNodes)

  nextNodes = nextNodes.map((node) => {
    const data = { ...(node.data || {}) }
    const parentId = node.parentNode || node.parentId

    if (parentId) {
      node = {
        ...node,
        parentNode: parentId,
        extent: 'parent',
        zIndex: NESTED_ELEMENT_Z_INDEX,
      }
      if (data.type === BlockEnum.IterationStart) data.isInIteration = true
      if (data.type === BlockEnum.LoopStart) data.isInLoop = true
    }

    const { sourceHandles, targetHandles } = getConnectedHandleIds(node.id, nextEdges)
    data._connectedSourceHandleIds = sourceHandles
    data._connectedTargetHandleIds = targetHandles

    if (data.type === BlockEnum.IfElse) {
      if (!data.cases?.length) {
        data.cases = [
          {
            case_id: 'true',
            logical_operator: 'and',
            conditions: [],
          },
        ]
      }
      data._targetBranches = branchNameCorrect([
        ...data.cases.map((item) => ({ id: item.case_id, name: '' })),
        { id: 'false', name: '' },
      ])
    }

    if (data.type === BlockEnum.QuestionClassifier) {
      const classes = data.classes || []
      data._targetBranches = classes.map((topic) => ({
        id: topic.id,
        name: topic.name,
      }))
    }

    if (data.type === BlockEnum.Iteration) {
      data._children = childrenMap[node.id] || data._children || []
      data.is_parallel = data.is_parallel ?? false
      data.parallel_nums = data.parallel_nums ?? 10
      data.error_handle_mode = data.error_handle_mode ?? 'terminated'
    }

    if (data.type === BlockEnum.Loop) {
      data._children = childrenMap[node.id] || data._children || []
      data.loop_count = data.loop_count ?? data.max_iterations ?? 10
      data.error_handle_mode = data.error_handle_mode ?? 'terminated'
    }

    if (data.type === BlockEnum.IterationStart || data.type === BlockEnum.LoopStart) {
      node = { ...node, selectable: false, draggable: false }
    }

    return { ...node, data }
  })

  return { nodes: nextNodes, edges: nextEdges }
}

/** 导出 graph 时剥离 UI 运行时字段（对齐 Dify producedNodes） */
export function stripRuntimeNodeData(data) {
  if (!data || typeof data !== 'object') return data
  const out = {}
  for (const [key, value] of Object.entries(data)) {
    if (key.startsWith('_')) continue
    out[key] = value
  }
  return out
}

/** 检测新增连线是否会产生环 */
export function wouldCreateCycle(nodes, edges, connection) {
  const adjList = {}
  for (const node of nodes) adjList[node.id] = []
  for (const edge of edges) adjList[edge.source]?.push(edge.target)

  const { source, target } = connection
  if (!source || !target) return false

  const visited = new Set()
  const stack = [target]
  while (stack.length) {
    const current = stack.pop()
    if (current === source) return true
    if (visited.has(current)) continue
    visited.add(current)
    for (const next of adjList[current] || []) stack.push(next)
  }
  return false
}
