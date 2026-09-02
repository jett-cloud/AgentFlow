// src/views/copilot/components/workflow/node/loop/useLoopInteractions.js
// 1:1 对齐 Dify React 官方源码 (web/app/components/workflow/nodes/loop/use-interactions.helpers.ts)

export const LOOP_PADDING = {
  top: 60,
  left: 24,
  right: 24,
  bottom: 24
}

export const CUSTOM_LOOP_START_NODE = 'custom-loop-start'

/**
 * 1. 计算包含所有内部子节点的最大外包围盒 (Loop Container Bounds)
 */
export const getLoopContainerBounds = (childrenNodes = []) => {
  return childrenNodes.reduce((acc, node) => {
    const nodeWidth = node.dimensions?.width || node.width || 240
    const nodeHeight = node.dimensions?.height || node.height || 100

    const nextRightNode =
      !acc.rightNode ||
      node.position.x + nodeWidth > acc.rightNode.position.x + (acc.rightNode.dimensions?.width || acc.rightNode.width || 240)
        ? node
        : acc.rightNode

    const nextBottomNode =
      !acc.bottomNode ||
      node.position.y + nodeHeight > acc.bottomNode.position.y + (acc.bottomNode.dimensions?.height || acc.bottomNode.height || 100)
        ? node
        : acc.bottomNode

    return {
      rightNode: nextRightNode,
      bottomNode: nextBottomNode
    }
  }, {})
}

/**
 * 2. 算出现在父循环容器所需要自动调整扩展的 Width 和 Height
 */
export const getLoopContainerResize = (currentNode, bounds) => {
  const currentWidth = parseInt(currentNode.style?.width || currentNode.width || '340')
  const currentHeight = parseInt(currentNode.style?.height || currentNode.height || '220')

  let width = undefined
  let height = undefined

  if (bounds.rightNode) {
    const rightWidth = bounds.rightNode.dimensions?.width || bounds.rightNode.width || 240
    const requiredW = bounds.rightNode.position.x + rightWidth + LOOP_PADDING.right
    if (requiredW > currentWidth) {
      width = requiredW
    }
  }

  if (bounds.bottomNode) {
    const bottomHeight = bounds.bottomNode.dimensions?.height || bounds.bottomNode.height || 100
    const requiredH = bounds.bottomNode.position.y + bottomHeight + LOOP_PADDING.bottom
    if (requiredH > currentHeight) {
      height = requiredH
    }
  }

  return { width, height }
}

/**
 * 3. 拖拽内层子节点时的内边距限制 (Restricted Position)
 */
export const getRestrictedLoopPosition = (node, parentNode) => {
  const restrictPosition = { x: undefined, y: undefined }
  if (!node || !parentNode) return restrictPosition

  const nodeWidth = node.dimensions?.width || node.width || 240
  const nodeHeight = node.dimensions?.height || node.height || 100
  const parentWidth = parseInt(parentNode.style?.width || parentNode.width || '340')
  const parentHeight = parseInt(parentNode.style?.height || parentNode.height || '220')

  // 左上角边缘锁定
  if (node.position.x < LOOP_PADDING.left) restrictPosition.x = LOOP_PADDING.left
  if (node.position.y < LOOP_PADDING.top) restrictPosition.y = LOOP_PADDING.top

  // 右下角边缘锁定
  if (node.position.x + nodeWidth > parentWidth - LOOP_PADDING.right) {
    restrictPosition.x = parentWidth - LOOP_PADDING.right - nodeWidth
  }
  if (node.position.y + nodeHeight > parentHeight - LOOP_PADDING.bottom) {
    restrictPosition.y = parentHeight - LOOP_PADDING.bottom - nodeHeight
  }

  return restrictPosition
}

/**
 * 4. 获得循环容器内部所有排除 start 节点之外的实际业务子节点
 */
export const getLoopChildren = (nodes = [], nodeId) => {
  return nodes.filter(
    (n) => n.parentNode === nodeId && n.type !== CUSTOM_LOOP_START_NODE && n.type !== 'loop-start'
  )
}
