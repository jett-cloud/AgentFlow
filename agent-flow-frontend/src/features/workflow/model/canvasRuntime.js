/**
 * Canvas draft-run visual mutations.
 * Contrasts Dify:
 *   use-workflow-started / use-workflow-node-started / use-workflow-node-finished
 *   utils/edge.ts getEdgeColor
 */

import { BlockEnum } from './constants.js'

/** Aligns with Dify ErrorHandleTypeEnum.failBranch */
export const FAIL_BRANCH = 'fail-branch'

export const NodeRunningStatus = {
  Running: 'running',
  Succeeded: 'succeeded',
  Failed: 'failed',
  Exception: 'exception',
  Waiting: 'waiting',
  Paused: 'paused',
}

/** Aligns with Dify DEFAULT_ITER_TIMES */
export const DEFAULT_ITER_TIMES = 1


/**
 * @param {string} [nodeRunningStatus]
 * @param {boolean} [isFailBranch]
 */
export function getEdgeColor(nodeRunningStatus, isFailBranch = false) {
  if (nodeRunningStatus === NodeRunningStatus.Succeeded)
    return 'var(--workflow-link-line-success-handle, #17b26a)'
  if (nodeRunningStatus === NodeRunningStatus.Failed)
    return 'var(--workflow-link-line-error-handle, #f04438)'
  if (nodeRunningStatus === NodeRunningStatus.Exception)
    return 'var(--workflow-link-line-failure-handle, #f79009)'
  if (nodeRunningStatus === NodeRunningStatus.Running) {
    if (isFailBranch)
      return 'var(--workflow-link-line-failure-handle, #f79009)'
    return 'var(--workflow-link-line-handle, #085afc)'
  }
  return 'var(--workflow-link-line-normal, #d0d5dc)'
}

/**
 * Resolve branch handle after node_finished (if-else / QC / human-input / fail-branch).
 */
export function resolveRunningBranchId({
  nodeType,
  status,
  outputs,
  executionMetadata,
} = {}) {
  if (status === NodeRunningStatus.Exception
    && executionMetadata?.error_strategy === FAIL_BRANCH) {
    return FAIL_BRANCH
  }
  if (nodeType === BlockEnum.IfElse)
    return outputs?.selected_case_id
  if (nodeType === BlockEnum.QuestionClassifier)
    return outputs?.class_id
  if (nodeType === BlockEnum.HumanInput)
    return outputs?.__action_id
  return undefined
}

/** workflow_started: dim all nodes/edges as waiting. */
export function applyWorkflowStartedToGraph(nodes = [], edges = []) {
  for (const node of nodes) {
    if (!node?.data)
      continue
    node.data._waitingRun = true
    node.data._runningBranchId = undefined
    node.data._iterationIndex = undefined
    node.data._iterationLength = undefined
    node.data._loopIndex = undefined
    node.data._loopLength = undefined
    node.data._retryIndex = undefined
  }
  for (const edge of edges) {
    edge.data = {
      ...(edge.data || {}),
      _sourceRunningStatus: undefined,
      _targetRunningStatus: undefined,
      _waitingRun: true,
    }
  }
}

/**
 * Whether an income edge belongs to the taken branch of its source node.
 * Contrasts use-workflow-node-started income-edge filter.
 */
export function isTakenIncomeEdge(edge, incomeNode) {
  if (!incomeNode?.data)
    return false
  const handle = edge.sourceHandle || 'source'
  const branchId = incomeNode.data._runningBranchId
  if (!branchId)
    return handle === 'source'
  return handle === branchId
}

/** node_started: activate node + taken income edges. */
export function applyNodeStartedToGraph(nodes = [], edges = [], nodeId) {
  if (!nodeId)
    return null
  const node = nodes.find(n => n.id === nodeId) || null
  if (node?.data) {
    node.data._runningStatus = NodeRunningStatus.Running
    node.data._waitingRun = false
  }
  for (const edge of edges) {
    if (edge.target !== nodeId)
      continue
    const incomeNode = nodes.find(n => n.id === edge.source)
    if (!isTakenIncomeEdge(edge, incomeNode))
      continue
    edge.data = {
      ...(edge.data || {}),
      _sourceRunningStatus: incomeNode.data._runningStatus,
      _targetRunningStatus: NodeRunningStatus.Running,
      _waitingRun: false,
    }
  }
  return node
}

/** Activate all income edges (iteration/loop started — no branch filter in Dify). */
export function activateAllIncomeEdges(nodes = [], edges = [], nodeId) {
  for (const edge of edges) {
    if (edge.target !== nodeId)
      continue
    const incomeNode = nodes.find(n => n.id === edge.source)
    edge.data = {
      ...(edge.data || {}),
      _sourceRunningStatus: incomeNode?.data?._runningStatus,
      _targetRunningStatus: NodeRunningStatus.Running,
      _waitingRun: false,
    }
  }
}

/**
 * Shared container-start paint (iteration_started / loop_started).
 * Contrasts use-workflow-node-iteration-started / loop-started.
 */
export function applyContainerStartedToGraph(nodes = [], edges = [], {
  nodeId,
  iterationLength,
  loopLength,
} = {}) {
  if (!nodeId)
    return null
  const node = nodes.find(n => n.id === nodeId) || null
  if (node?.data) {
    node.data._runningStatus = NodeRunningStatus.Running
    node.data._waitingRun = false
    if (iterationLength !== undefined)
      node.data._iterationLength = iterationLength
    if (loopLength !== undefined)
      node.data._loopLength = loopLength
  }
  activateAllIncomeEdges(nodes, edges, nodeId)
  return node
}

/** iteration_next: set _iterationIndex (Dify uses store iterTimes). */
export function applyIterationNextToGraph(nodes = [], nodeId, iterationIndex) {
  if (!nodeId)
    return null
  const node = nodes.find(n => n.id === nodeId) || null
  if (node?.data)
    node.data._iterationIndex = iterationIndex
  return node
}

/** loop_next: set _loopIndex and reset children to waiting. */
export function applyLoopNextToGraph(nodes = [], { nodeId, loopIndex } = {}) {
  if (!nodeId)
    return null
  const node = nodes.find(n => n.id === nodeId) || null
  if (node?.data)
    node.data._loopIndex = loopIndex
  for (const child of nodes) {
    const parent = child.parentNode || child.parentId
    if (parent !== nodeId || !child.data)
      continue
    child.data._waitingRun = true
    child.data._runningStatus = NodeRunningStatus.Waiting
  }
  return node
}

/** Container completed (iteration_completed / loop_completed). */
export function applyContainerFinishedToGraph(nodes = [], edges = [], { nodeId, status } = {}) {
  if (!nodeId)
    return null
  const node = nodes.find(n => n.id === nodeId) || null
  if (node?.data)
    node.data._runningStatus = status
  for (const edge of edges) {
    if (edge.target !== nodeId)
      continue
    edge.data = {
      ...(edge.data || {}),
      _targetRunningStatus: status,
    }
  }
  return node
}

/** node_retry: write _retryIndex. */
export function applyNodeRetryToGraph(nodes = [], { nodeId, retryIndex } = {}) {
  if (!nodeId)
    return null
  const node = nodes.find(n => n.id === nodeId) || null
  if (node?.data)
    node.data._retryIndex = retryIndex
  return node
}

/** human_input_required: paint node as paused. */
export function applyHumanInputRequiredToGraph(nodes = [], nodeId) {
  if (!nodeId)
    return null
  const node = nodes.find(n => n.id === nodeId) || null
  if (node?.data)
    node.data._runningStatus = NodeRunningStatus.Paused
  return node
}


/** node_finished: status + optional branch id; update income edge target status. */
export function applyNodeFinishedToGraph(nodes = [], edges = [], {
  nodeId,
  status,
  nodeType,
  outputs,
  executionMetadata,
} = {}) {
  if (!nodeId)
    return null
  const node = nodes.find(n => n.id === nodeId) || null
  if (node?.data) {
    node.data._runningStatus = status
    const branchId = resolveRunningBranchId({
      nodeType: nodeType || node.data.type,
      status,
      outputs,
      executionMetadata,
    })
    if (branchId !== undefined)
      node.data._runningBranchId = branchId
  }
  for (const edge of edges) {
    if (edge.target !== nodeId)
      continue
    edge.data = {
      ...(edge.data || {}),
      _targetRunningStatus: status,
    }
  }
  return node
}

/** Clear all runtime paint fields (debug panel close / new run). */
export function clearGraphRuntime(nodes = [], edges = []) {
  for (const node of nodes) {
    if (!node?.data)
      continue
    delete node.data._runningStatus
    delete node.data._waitingRun
    delete node.data._runningBranchId
    delete node.data._iterationLength
    delete node.data._iterationIndex
    delete node.data._loopLength
    delete node.data._loopIndex
    delete node.data._retryIndex
  }
  for (const edge of edges) {
    if (!edge?.data)
      continue
    delete edge.data._waitingRun
    delete edge.data._sourceRunningStatus
    delete edge.data._targetRunningStatus
    delete edge.data._runningStatus
  }
}

/**
 * workflow_finished / incomplete stream end:
 * finalize nodes still painted as running/paused. Keep `_waitingRun` on never-run
 * nodes so unused branches stay dim (Dify path visualization).
 */
export function applyWorkflowFinishedToGraph(nodes = [], edges = [], { status } = {}) {
  let terminal = NodeRunningStatus.Succeeded
  if (status === 'failed' || status === 'exception')
    terminal = NodeRunningStatus.Failed
  else if (status === 'stopped' || status === 'cancelled')
    terminal = NodeRunningStatus.Failed

  for (const node of nodes) {
    if (!node?.data)
      continue
    const current = node.data._runningStatus
    if (current !== NodeRunningStatus.Running && current !== NodeRunningStatus.Paused)
      continue
    node.data._runningStatus = terminal
    node.data._waitingRun = false
    for (const edge of edges) {
      if (edge.source !== node.id && edge.target !== node.id)
        continue
      edge.data = {
        ...(edge.data || {}),
        ...(edge.source === node.id ? { _sourceRunningStatus: terminal } : {}),
        ...(edge.target === node.id ? { _targetRunningStatus: terminal } : {}),
        _waitingRun: false,
      }
    }
  }
}

/**
 * Vue Flow NodeWrapper / CustomEdge re-render when `data` object identity changes
 * (see updateNodeData / updateEdgeData). Mutators above patch fields in place —
 * call this after paint so status / edge colors / waiting opacity show up.
 * Avoid setEdges here: isValidConnection can drop re-applied edges as duplicates.
 */
export function refreshGraphRuntimeBindings(nodes = [], edges = []) {
  for (const node of nodes) {
    if (!node?.data)
      continue
    node.data = { ...node.data }
  }
  for (const edge of edges) {
    edge.data = { ...(edge.data || {}) }
  }
}

/**
 * Replay a finished run's node-executions onto the canvas (Dify view-history paint).
 * Does not mutate draft graph topology — only runtime status fields.
 */
export function applyHistoryTracingToGraph(nodes = [], edges = [], tracingItems = []) {
  clearGraphRuntime(nodes, edges)
  applyWorkflowStartedToGraph(nodes, edges)
  const ordered = [...(tracingItems || [])].sort((a, b) => (a.index ?? 0) - (b.index ?? 0))
  for (const item of ordered) {
    const nodeId = item.nodeId
    if (!nodeId)
      continue
    applyNodeStartedToGraph(nodes, edges, nodeId)
    applyNodeFinishedToGraph(nodes, edges, {
      nodeId,
      status: item.status || NodeRunningStatus.Succeeded,
      nodeType: item.nodeType,
      outputs: item.outputs,
      executionMetadata: item.executionMetadata,
    })
  }
}

/**
 * Normalize GET /workflow-runs/:id detail into preview panel fields.
 */
export function buildHistoryRunView(detail = {}) {
  const outputs = detail.outputs ?? detail.data?.outputs ?? null
  let resultText = detail.outputs_text || detail.resultText || ''
  if (!resultText && outputs != null) {
    if (typeof outputs === 'string')
      resultText = outputs
    else if (outputs.text != null)
      resultText = String(outputs.text)
    else if (outputs.answer != null)
      resultText = String(outputs.answer)
    else
      resultText = JSON.stringify(outputs, null, 2)
  }
  return {
    id: detail.id || '',
    status: detail.status || 'succeeded',
    resultText,
    outputs,
    error: detail.error || '',
    elapsed_time: detail.elapsed_time,
    total_tokens: detail.total_tokens,
    created_at: detail.created_at,
    finished_at: detail.finished_at,
  }
}

/**
 * Center viewport on a root node during run.
 * Contrasts use-workflow-node-started setViewport formula (panelOffset ≈ debug panel width).
 */
export function computeFollowViewport({
  position = { x: 0, y: 0 },
  width = 240,
  height = 90,
  zoom = 1,
  clientWidth = 0,
  clientHeight = 0,
  panelOffset = 400,
} = {}) {
  return {
    x: (clientWidth - panelOffset - width * zoom) / 2 - position.x * zoom,
    y: (clientHeight - height * zoom) / 2 - position.y * zoom,
    zoom,
  }
}

/** Resolve stroke for CustomEdge from runtime edge.data fields. */
export function resolveEdgeStroke({
  selected = false,
  hovering = false,
  sourceHandleId = 'source',
  sourceRunningStatus,
  targetRunningStatus,
} = {}) {
  if (selected || hovering)
    return getEdgeColor(NodeRunningStatus.Running, sourceHandleId === FAIL_BRANCH)
  if (sourceRunningStatus && targetRunningStatus) {
    if (targetRunningStatus === NodeRunningStatus.Running)
      return getEdgeColor(NodeRunningStatus.Running, sourceHandleId === FAIL_BRANCH)
    return getEdgeColor(targetRunningStatus, sourceHandleId === FAIL_BRANCH)
  }
  return getEdgeColor()
}
