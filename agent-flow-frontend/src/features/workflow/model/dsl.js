// src/views/copilot/components/workflow/core/dsl.js
//
// 画布 <-> 后端 graph_dict 的双向转换 + 节点工厂。
//
// 后端（Dify graph_dict / workflow.graph_dict）格式：
//   nodes: [{ id, type: 'custom', data: { type: <BlockEnum>, title, ... }, position, width?, height?, parentId? }]
//   edges: [{ id, source, target, sourceHandle, targetHandle, data?: {...} }]
//
// 画布（vue-flow）格式：node.type 用“业务类型”以命中 registry 的 NODE_COMPONENT_MAP；
// 迭代/循环内部起始节点用 'iteration-start' / 'loop-start'。
// 导出时统一把 node.type 还原为 'custom'（起始节点为 custom-iteration-start / custom-loop-start）。

import {
  BlockEnum,
  CUSTOM_NODE,
  CUSTOM_SIMPLE_NODE,
  CUSTOM_EDGE,
  CUSTOM_ITERATION_START_NODE,
  CUSTOM_LOOP_START_NODE,
  CUSTOM_NOTE_NODE,
  NODE_Z_INDEX,
  ITERATION_NODE_Z_INDEX,
  NESTED_ELEMENT_Z_INDEX,
  DEFAULT_SOURCE_HANDLE,
  DEFAULT_TARGET_HANDLE,
  START_NODE_TYPES,
  LEGACY_VARIABLE_AGGREGATOR_TYPE,
} from './constants.js'
import { getDefaultNodeData, isContainerNode } from './nodeMeta.js'
import { preprocessFlowGraph, stripRuntimeNodeData } from './workflowInit.js'
import { normalizeListOperatorData } from '../nodes/list-operator/listOperator.js'
import { normalizeCodeNodeData } from '../nodes/code/codeNode.js'
import { normalizeTemplateTransformData } from '../nodes/template-transform/templateTransform.js'
import { normalizeDocumentExtractorData } from '../nodes/document-extractor/documentExtractor.js'
import { normalizeHttpRequestData } from '../nodes/http-request/httpRequest.js'
import { normalizeToolNodeData } from '../nodes/tool/toolNode.js'
import { normalizeIterationData } from '../nodes/iteration/iterationNode.js'
import { normalizeLoopData } from '../nodes/loop/loopNode.js'
import { normalizeIfElseData } from '../nodes/if-else/ifElseNode.js'
import { normalizeQuestionClassifierData } from '../nodes/question-classifier/questionClassifierNode.js'
import { normalizeHumanInputData } from '../nodes/human-input/humanInputNode.js'
import { normalizeLLMNodeData } from '../nodes/llm/llmNode.js'
import { normalizeParameterExtractorData } from '../nodes/parameter-extractor/parameterExtractorNode.js'
import { normalizeKnowledgeRetrievalData } from '../nodes/knowledge-retrieval/knowledgeRetrievalNode.js'
import { normalizeKnowledgeBaseData } from '../nodes/knowledge-base/knowledgeBaseNode.js'
import { normalizeDataSourceData } from '../nodes/data-source/dataSourceNode.js'
import { normalizeEndNodeData } from '../nodes/end/endNode.js'
import { normalizeAnswerNodeData } from '../nodes/er/answerNode.js'
import { normalizeLoopEndNodeData } from '../nodes/loop-end/loopEndNode.js'
import { normalizeNoteData } from '../nodes/note/noteNode.js'
import { normalizeStartPlaceholderData } from '../nodes/start-placeholder/startPlaceholderNode.js'
import { normalizeIterationStartData } from '../nodes/iteration-start/iterationStartNode.js'
import { normalizeLoopStartData } from '../nodes/loop-start/loopStartNode.js'
import { normalizeStartNodeData } from '../nodes/t/startNode.js'

/** 对齐 Dify START_INITIAL_POSITION */
export const START_INITIAL_POSITION = { x: 80, y: 282 }

let _seq = 0
/** 生成唯一 id（时间戳 + 自增，避免同一毫秒内碰撞） */
export function uid() {
  _seq += 1
  return `${Date.now()}${_seq.toString().padStart(3, '0')}`
}

/** 将旧 AgentFlow 变量节点数据迁移为当前 Dify 官方类型。 */
export function normalizeVariableNodeData(data = {}) {
  if (data.type === LEGACY_VARIABLE_AGGREGATOR_TYPE)
    return { ...data, type: BlockEnum.VariableAssigner }

  if (data.type === BlockEnum.VariableAssigner && Array.isArray(data.items))
    return { ...data, type: BlockEnum.Assigner }

  return { ...data }
}

/** Normalize known legacy node data while preserving unrecognized Dify fields. */
export function normalizeNodeData(data = {}) {
  const normalized = normalizeVariableNodeData(data)
  if (normalized.type === BlockEnum.Start)
    return normalizeStartNodeData(normalized)
  if (normalized.type === BlockEnum.ListFilter)
    return normalizeListOperatorData(normalized)
  if (normalized.type === BlockEnum.Code)
    return normalizeCodeNodeData(normalized)
  if (normalized.type === BlockEnum.TemplateTransform)
    return normalizeTemplateTransformData(normalized)
  if (normalized.type === BlockEnum.DocExtractor)
    return normalizeDocumentExtractorData(normalized)
  if (normalized.type === BlockEnum.HttpRequest)
    return normalizeHttpRequestData(normalized)
  if (normalized.type === BlockEnum.Tool)
    return normalizeToolNodeData(normalized)
  if (normalized.type === BlockEnum.Iteration)
    return normalizeIterationData(normalized)
  if (normalized.type === BlockEnum.Loop)
    return normalizeLoopData(normalized)
  if (normalized.type === BlockEnum.IfElse)
    return normalizeIfElseData(normalized)
  if (normalized.type === BlockEnum.QuestionClassifier)
    return normalizeQuestionClassifierData(normalized)
  if (normalized.type === BlockEnum.HumanInput)
    return normalizeHumanInputData(normalized)
  if (normalized.type === BlockEnum.LLM)
    return normalizeLLMNodeData(normalized)
  if (normalized.type === BlockEnum.ParameterExtractor)
    return normalizeParameterExtractorData(normalized)
  if (normalized.type === BlockEnum.KnowledgeRetrieval)
    return normalizeKnowledgeRetrievalData(normalized)
  if (normalized.type === BlockEnum.KnowledgeBase)
    return normalizeKnowledgeBaseData(normalized)
  if (normalized.type === BlockEnum.DataSource)
    return normalizeDataSourceData(normalized)
  if (normalized.type === BlockEnum.End)
    return normalizeEndNodeData(normalized)
  if (normalized.type === BlockEnum.Answer)
    return normalizeAnswerNodeData(normalized)
  if (normalized.type === BlockEnum.LoopEnd)
    return normalizeLoopEndNodeData(normalized)
  if (normalized.type === BlockEnum.Note)
    return normalizeNoteData(normalized)
  if (normalized.type === BlockEnum.StartPlaceholder)
    return normalizeStartPlaceholderData(normalized)
  if (normalized.type === BlockEnum.IterationStart)
    return normalizeIterationStartData(normalized)
  if (normalized.type === BlockEnum.LoopStart)
    return normalizeLoopStartData(normalized)
  return normalized
}

/** 迭代容器内部虚拟起始节点 */
export function makeIterationStartNode(iterationId) {
  return {
    id: `${iterationId}start`,
    type: 'iteration-start',
    position: { x: 24, y: 68 },
    zIndex: NESTED_ELEMENT_Z_INDEX,
    parentNode: iterationId,
    extent: 'parent',
    selectable: false,
    draggable: false,
    data: { ...getDefaultNodeData(BlockEnum.IterationStart) },
  }
}

/** 循环容器内部虚拟起始节点 */
export function makeLoopStartNode(loopId) {
  return {
    id: `${loopId}start`,
    type: 'loop-start',
    position: { x: 24, y: 68 },
    zIndex: NESTED_ELEMENT_Z_INDEX,
    parentNode: loopId,
    extent: 'parent',
    selectable: false,
    draggable: false,
    data: { ...getDefaultNodeData(BlockEnum.LoopStart) },
  }
}

/**
 * 节点工厂：按业务类型生成一个新的 vue-flow 节点。
 * 对齐 Dify utils/node.ts generateNewNode：迭代/循环会附带一个内部起始节点。
 *
 * @returns {{ newNode: object, extraNodes: object[] }}
 */
export function generateNewNode({ type, position, id, data = {} }) {
  const nodeId = id || uid()
  const isContainer = isContainerNode(type)

  const newNode = {
    id: nodeId,
    type,
    position: position || { x: 0, y: 0 },
    data: { ...getDefaultNodeData(type), ...data },
    zIndex: isContainer ? ITERATION_NODE_Z_INDEX : NODE_Z_INDEX,
  }

  if (type === BlockEnum.Iteration || type === BlockEnum.Loop) {
    newNode.style = {
      width: `${newNode.data.width || 640}px`,
      height: `${newNode.data.height || 340}px`,
    }
    delete newNode.data.width
    delete newNode.data.height

    const startNode =
      type === BlockEnum.Iteration ? makeIterationStartNode(nodeId) : makeLoopStartNode(nodeId)
    newNode.data.start_node_id = startNode.id
    newNode.data._children = [{ nodeId: startNode.id, nodeType: startNode.data.type }]
    return { newNode, extraNodes: [startNode] }
  }

  return { newNode, extraNodes: [] }
}

/** 把后端节点的 vue-flow type（'custom' 等）映射成画布用的业务类型 */
function toCanvasNodeType(backendNode) {
  if (backendNode.type === CUSTOM_NOTE_NODE) return BlockEnum.Note
  const dataType = backendNode.data?.type
  if (dataType === BlockEnum.IterationStart) return 'iteration-start'
  if (dataType === BlockEnum.LoopStart) return 'loop-start'
  return dataType || 'default'
}

/** 把画布节点的业务 type 还原成后端 vue-flow type */
function toBackendNodeType(canvasNode) {
  if (canvasNode.type === BlockEnum.Note || canvasNode.data?.type === BlockEnum.Note)
    return CUSTOM_NOTE_NODE
  const dataType = canvasNode.data?.type
  if (dataType === BlockEnum.LoopEnd) return CUSTOM_SIMPLE_NODE
  if (dataType === BlockEnum.IterationStart) return CUSTOM_ITERATION_START_NODE
  if (dataType === BlockEnum.LoopStart) return CUSTOM_LOOP_START_NODE
  return CUSTOM_NODE
}

/**
 * 后端 graph_dict -> vue-flow { nodes, edges }
 */
export function graphToFlow(graph) {
  const rawNodes = graph?.nodes || []
  const rawEdges = graph?.edges || []

  const nodes = rawNodes.map((n) => {
    let data = normalizeNodeData(n.data || {})
    const canvasType = toCanvasNodeType({ ...n, data })
    if (canvasType === BlockEnum.Note)
      data = normalizeNoteData(data)
    const node = {
      id: n.id,
      type: canvasType,
      position: n.position || { x: 0, y: 0 },
      data,
    }
    // 容器尺寸
    const keepsExplicitSize = isContainerNode(canvasType) || canvasType === BlockEnum.Note
    if (keepsExplicitSize && (n.width || n.height || n.style)) {
      node.style = {
        ...(n.style || {}),
        ...(n.width ? { width: `${n.width}px` } : {}),
        ...(n.height ? { height: `${n.height}px` } : {}),
      }
    }
    else if (n.width || n.height) {
      node._persistedSize = {
        ...(n.width ? { width: n.width } : {}),
        ...(n.height ? { height: n.height } : {}),
      }
    }
    // 父子（迭代/循环子节点）
    const parentId = n.parentId || n.parentNode
    if (parentId) {
      node.parentNode = parentId
      node.extent = 'parent'
      node.zIndex = NESTED_ELEMENT_Z_INDEX
    }
    if (node.data.type === BlockEnum.IterationStart || node.data.type === BlockEnum.LoopStart) {
      node.selectable = false
      node.draggable = false
    }
    return node
  })

  const edges = rawEdges.map((e) => ({
    id: e.id || `${e.source}-${e.sourceHandle || DEFAULT_SOURCE_HANDLE}-${e.target}-${e.targetHandle || DEFAULT_TARGET_HANDLE}`,
    type: CUSTOM_EDGE,
    source: e.source,
    target: e.target,
    sourceHandle: e.sourceHandle || DEFAULT_SOURCE_HANDLE,
    targetHandle: e.targetHandle || DEFAULT_TARGET_HANDLE,
    data: { ...(e.data || {}) },
  }))

  return {
    ...ensureStartPlaceholderOnFlow(preprocessFlowGraph(nodes, edges)),
    viewport: graph?.viewport,
  }
}

/**
 * 空图或无入口节点时注入 start-placeholder（客户端 UI 节点，导出时剥离）
 */
export function ensureStartPlaceholderOnFlow({ nodes = [], edges = [] } = {}) {
  const hasEntry = nodes.some((node) => {
    const type = node.data?.type || node.type
    return START_NODE_TYPES.includes(type) || type === BlockEnum.StartPlaceholder
  })
  if (hasEntry)
    return { nodes, edges }

  // Only seed placeholder for brand-new empty canvases (Dify new-workflow path).
  if (nodes.length > 0)
    return { nodes, edges }

  const { newNode } = generateNewNode({
    type: BlockEnum.StartPlaceholder,
    position: { ...START_INITIAL_POSITION },
  })
  newNode.selected = true
  return { nodes: [newNode], edges }
}

export function isStartPlaceholderNode(node) {
  const type = node?.data?.type || node?.type
  return type === BlockEnum.StartPlaceholder
}

/** 从 style 里解析出像素数值（'640px' -> 640） */
function parsePx(val) {
  if (typeof val === 'number') return val
  if (typeof val === 'string') {
    const n = Number.parseInt(val, 10)
    return Number.isNaN(n) ? undefined : n
  }
  return undefined
}

/**
 * vue-flow { nodes, edges } -> 后端 graph_dict
 * （node.type 还原为 'custom'；容器宽高从 style 提取到 width/height）
 */
export function flowToGraph(nodes, edges, viewport) {
  const flowNodes = nodes || []
  const placeholderIds = new Set(
    flowNodes.filter(isStartPlaceholderNode).map(node => node.id),
  )
  const outNodes = flowNodes
    .filter(node => !isStartPlaceholderNode(node))
    .map((n) => {
    const node = {
      id: n.id,
      type: toBackendNodeType(n),
      data: stripRuntimeNodeData(normalizeNodeData(n.data || {})),
      position: n.position || { x: 0, y: 0 },
    }
    const parentId = n.parentNode || n.parentId
    if (parentId) node.parentId = parentId

    const nodeType = n.data?.type || n.type
    const keepsExplicitSize = isContainerNode(nodeType) || nodeType === BlockEnum.Note
    const w = parsePx(keepsExplicitSize
      ? (n.style?.width ?? n.width ?? n._persistedSize?.width)
      : (n.dimensions?.width ?? n.width ?? n._persistedSize?.width))
    const h = parsePx(keepsExplicitSize
      ? (n.style?.height ?? n.height ?? n._persistedSize?.height)
      : (n.dimensions?.height ?? n.height ?? n._persistedSize?.height))
    if (w) node.width = w
    if (h) node.height = h
    return node
  })

  const outEdges = (edges || [])
    .filter(edge => !placeholderIds.has(edge.source) && !placeholderIds.has(edge.target))
    .map((e) => ({
      id: e.id,
      type: e.type || CUSTOM_EDGE,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle || DEFAULT_SOURCE_HANDLE,
      targetHandle: e.targetHandle || DEFAULT_TARGET_HANDLE,
      data: stripRuntimeNodeData(e.data || {}),
    }))

  return {
    nodes: outNodes,
    edges: outEdges,
    ...(viewport ? {
      viewport: {
        x: viewport.x || 0,
        y: viewport.y || 0,
        zoom: viewport.zoom || 1,
      },
    } : {}),
  }
}
