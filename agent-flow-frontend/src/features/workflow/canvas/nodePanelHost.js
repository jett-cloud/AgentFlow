export const NODE_PANEL_MIN_WIDTH = 400
export const NODE_PANEL_MAX_WIDTH = 850
export const NODE_PANEL_CANVAS_RESERVE = 400

/** Use the displayed workflow trace, unless the user explicitly starts a standalone run. */
export function selectNodePanelResult({ nodeId, tracing = [], singleResult = null, preferSingle = false }) {
  if (preferSingle)
    return singleResult
  const record = tracing.findLast(item => item.nodeId === nodeId)
  if (!record)
    return null
  return {
    ...record,
    process_data: record.processData,
    execution_metadata: record.executionMetadata,
  }
}

export function clampNodePanelWidth(requestedWidth, viewportWidth = 0) {
  const availableMaximum = viewportWidth > 0
    ? Math.max(NODE_PANEL_MIN_WIDTH, viewportWidth - NODE_PANEL_CANVAS_RESERVE)
    : NODE_PANEL_MAX_WIDTH
  const maximum = Math.min(NODE_PANEL_MAX_WIDTH, availableMaximum)
  return Math.min(Math.max(Number(requestedWidth) || NODE_PANEL_MIN_WIDTH, NODE_PANEL_MIN_WIDTH), maximum)
}

export function getNodePanelTabs(supportsSingleRun) {
  return supportsSingleRun ? ['settings', 'last-run'] : ['settings']
}

export function openNodePanelState({
  nodeId,
  findNode,
  activeNodeId,
  activeNode,
}) {
  activeNodeId.value = nodeId
  const node = findNode(nodeId)
  activeNode.value = node
    ? {
        id: node.id,
        type: node.data?.type || node.type,
        data: node.data,
        parentNode: node.parentNode,
        parentId: node.parentId,
      }
    : null
}
