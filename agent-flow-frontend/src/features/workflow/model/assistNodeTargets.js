export function selectedAssistNodeIds(nodes, clickedNodeId) {
  const selected = (nodes || []).filter(node => node?.selected).map(node => String(node.id))
  if (selected.length)
    return selected
  return clickedNodeId ? [String(clickedNodeId)] : []
}

export function mergeAssistTargetIds(currentIds, addedIds, liveIds) {
  return [...new Set([...(currentIds || []), ...(addedIds || [])].map(String))]
    .filter(id => liveIds.has(id))
}
