export function getNodeHandleAddAction({
  nodeId,
  type,
  handleId,
  label = '',
  readOnly = false,
  connected = false,
} = {}) {
  if (readOnly || !nodeId || !handleId) return null
  if (type === 'target') {
    if (connected) return null
    return {
      ariaLabel: '添加前置节点',
      selector: {
        direction: 'before',
        nodeId,
        targetHandle: handleId,
      },
    }
  }
  if (type !== 'source') return null

  return {
    ariaLabel: label ? `从 ${label} 添加后续节点` : '添加后续节点',
    selector: {
      direction: 'after',
      nodeId,
      sourceHandle: handleId,
    },
  }
}
