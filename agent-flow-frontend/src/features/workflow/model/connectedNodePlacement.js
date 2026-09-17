const DEFAULT_NODE_WIDTH = 240
const NODE_GAP = 80

function parseSize(value) {
  const size = Number.parseFloat(value)
  return Number.isFinite(size) && size > 0 ? size : undefined
}

export function getConnectedNodePosition(sourceNode, parentNode) {
  const width = parseSize(sourceNode?.style?.width)
    || parseSize(sourceNode?.dimensions?.width)
    || parseSize(sourceNode?.width)
    || DEFAULT_NODE_WIDTH
  return {
    x: (parentNode?.position?.x || 0) + (sourceNode?.position?.x || 0) + width + NODE_GAP,
    y: (parentNode?.position?.y || 0) + (sourceNode?.position?.y || 0),
  }
}

export function getPredecessorNodePosition(targetNode, parentNode) {
  return {
    x: (parentNode?.position?.x || 0)
      + (targetNode?.position?.x || 0)
      - DEFAULT_NODE_WIDTH
      - NODE_GAP,
    y: (parentNode?.position?.y || 0) + (targetNode?.position?.y || 0),
  }
}
