export function normalizeNodeSelectorContext({
  direction,
  nodeId,
  sourceHandle = 'source',
  targetHandle = 'target',
  edgeId,
  parentId,
} = {}) {
  if (direction === 'before' && nodeId) {
    return {
      direction: 'before',
      connection: null,
      targetConnection: { target: nodeId, targetHandle },
      edgeId: null,
      parentId: null,
    }
  }
  if (nodeId) {
    return {
      direction: 'after',
      connection: { source: nodeId, sourceHandle },
      targetConnection: null,
      edgeId: null,
      parentId: null,
    }
  }
  if (edgeId) {
    return {
      direction: 'insert',
      connection: null,
      targetConnection: null,
      edgeId,
      parentId: null,
    }
  }
  return {
    direction: 'free',
    connection: null,
    targetConnection: null,
    edgeId: null,
    parentId: parentId || null,
  }
}
