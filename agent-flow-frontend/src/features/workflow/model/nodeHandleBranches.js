import { getHumanInputBranches } from '../nodes/human-input/humanInputNode.js'

const TERMINAL_TYPES = new Set(['end', 'loop-end', 'note', 'start-placeholder'])

function branch(id, name = '', kind = 'normal') {
  return { id: String(id), name, kind }
}

function normalizeBranches(items = [], fallbackName) {
  return items
    .filter(item => item?.id != null && item.id !== '')
    .map((item, index) => branch(item.id, item.name || fallbackName(index, item)))
}

function resolveClassifierBranches(data) {
  const runtimeBranches = data._targetBranches
  if (Array.isArray(runtimeBranches) && runtimeBranches.length) {
    return normalizeBranches(runtimeBranches, index => `Class ${index + 1}`)
  }
  return normalizeBranches(data.classes, index => `Class ${index + 1}`)
}

function resolveIfElseBranches(data) {
  const caseItems = Array.isArray(data.cases) ? data.cases : []
  if (caseItems.length) {
    const cases = caseItems
      .filter(item => item?.case_id != null && item.case_id !== '')
      .map((item, index) => branch(
        item.case_id,
        caseItems.length === 1 ? 'IF' : `CASE ${index + 1}`,
      ))
    return [...cases, branch('false', 'ELSE')]
  }

  const runtimeBranches = data._targetBranches
  if (Array.isArray(runtimeBranches) && runtimeBranches.length)
    return normalizeBranches(runtimeBranches, (index, item) => item.id === 'false' ? 'ELSE' : index === 0 ? 'IF' : `CASE ${index + 1}`)
  return [branch('true', 'IF'), branch('false', 'ELSE')]
}

function resolveHumanInputBranches(data) {
  return getHumanInputBranches(data).map(item => ({
    id: item.id,
    name: item.name,
    kind: 'normal',
  }))
}

function hasFailureBranch(data) {
  const strategy = data.error_handle_mode
    || data.error_strategy
    || data.errorStrategy
  return strategy === 'fail-branch' || strategy === 'failBranch'
}

export function getNodeOutputBranches(data = {}) {
  if (TERMINAL_TYPES.has(data.type)) return []
  if (data.type === 'question-classifier') return resolveClassifierBranches(data)
  if (data.type === 'if-else') return resolveIfElseBranches(data)
  if (data.type === 'human-input') return resolveHumanInputBranches(data)

  const branches = [branch('source')]
  if (hasFailureBranch(data))
    branches.push(branch('fail-branch', '失败', 'failure'))
  return branches
}

export function getRemovedOutputHandleIds(previousData = {}, nextData = {}) {
  const nextIds = new Set(getNodeOutputBranches(nextData).map(item => item.id))
  return getNodeOutputBranches(previousData)
    .map(item => item.id)
    .filter(id => !nextIds.has(id))
}

export function getRenamedOutputHandles(previousData = {}, nextData = {}) {
  const previousIds = getNodeOutputBranches(previousData).map(item => item.id)
  const nextIds = getNodeOutputBranches(nextData).map(item => item.id)
  const removed = previousIds.filter(id => !nextIds.includes(id) && id !== '__timeout')
  const added = nextIds.filter(id => !previousIds.includes(id) && id !== '__timeout')
  if (removed.length === 1 && added.length === 1)
    return [{ from: removed[0], to: added[0] }]
  return []
}

export function getEdgesAfterNodeDataUpdate({
  nodeId,
  previousData,
  nextData,
  edges = [],
}) {
  const renamedHandles = getRenamedOutputHandles(previousData, nextData)
  const renameMap = new Map(renamedHandles.map(item => [item.from, item.to]))
  const remappedEdges = []
  const edgesAfterRename = edges.map((edge) => {
    if (edge.source !== nodeId)
      return edge
    const nextHandle = renameMap.get(edge.sourceHandle || 'source')
    if (!nextHandle)
      return edge
    const nextEdge = { ...edge, sourceHandle: nextHandle }
    remappedEdges.push({ id: edge.id, sourceHandle: nextHandle })
    return nextEdge
  })

  const removedHandles = new Set(getRemovedOutputHandleIds(previousData, nextData).filter(id => !renameMap.has(id)))
  const removedEdgeIds = edgesAfterRename
    .filter(edge => edge.source === nodeId && removedHandles.has(edge.sourceHandle || 'source'))
    .map(edge => edge.id)
  const removedEdgeIdSet = new Set(removedEdgeIds)
  const affectedTargetIds = [...new Set(
    edges
      .filter(edge => removedEdgeIdSet.has(edge.id))
      .map(edge => edge.target),
  )]
  const remainingEdges = edgesAfterRename.filter(edge => !removedEdgeIdSet.has(edge.id))
  const connectedSourceHandleIds = [...new Set(
    remainingEdges
      .filter(edge => edge.source === nodeId)
      .map(edge => edge.sourceHandle || 'source'),
  )]

  return {
    edges: remainingEdges,
    removedEdgeIds,
    remappedEdges,
    affectedTargetIds,
    connectedSourceHandleIds,
  }
}
