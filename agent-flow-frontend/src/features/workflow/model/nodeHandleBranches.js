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
  const runtimeBranches = data._targetBranches
  if (Array.isArray(runtimeBranches) && runtimeBranches.length) {
    return normalizeBranches(runtimeBranches, (index, item) => {
      if (item.id === 'false') return 'ELSE'
      return index === 0 ? 'IF' : `ELIF ${index}`
    })
  }
  const cases = (data.cases || []).map((item, index) => branch(
    item.case_id,
    index === 0 ? 'IF' : `ELIF ${index}`,
  ))
  return [...cases, branch('false', 'ELSE')]
}

function resolveHumanInputBranches(data) {
  const runtimeBranches = data._targetBranches
  if (Array.isArray(runtimeBranches) && runtimeBranches.length) {
    return normalizeBranches(runtimeBranches, (_index, item) => item.id)
  }
  const actions = (data.user_actions || []).map(item => branch(
    item.id,
    item.title || item.name || item.id,
  ))
  if (data.timeout != null)
    actions.push(branch('__timeout', 'Timeout (超时)'))
  return actions
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

export function getEdgesAfterNodeDataUpdate({
  nodeId,
  previousData,
  nextData,
  edges = [],
}) {
  const removedHandles = new Set(getRemovedOutputHandleIds(previousData, nextData))
  const removedEdgeIds = edges
    .filter(edge => edge.source === nodeId && removedHandles.has(edge.sourceHandle || 'source'))
    .map(edge => edge.id)
  const removedEdgeIdSet = new Set(removedEdgeIds)
  const affectedTargetIds = [...new Set(
    edges
      .filter(edge => removedEdgeIdSet.has(edge.id))
      .map(edge => edge.target),
  )]
  const remainingEdges = edges.filter(edge => !removedEdgeIdSet.has(edge.id))
  const connectedSourceHandleIds = [...new Set(
    remainingEdges
      .filter(edge => edge.source === nodeId)
      .map(edge => edge.sourceHandle || 'source'),
  )]

  return {
    edges: remainingEdges,
    removedEdgeIds,
    affectedTargetIds,
    connectedSourceHandleIds,
  }
}
