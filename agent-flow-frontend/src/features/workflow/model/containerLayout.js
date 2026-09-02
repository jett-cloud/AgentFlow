export const CONTAINER_MIN_WIDTH = 320
export const CONTAINER_MIN_HEIGHT = 200
export const CONTAINER_RIGHT_PADDING = 24
export const CONTAINER_BOTTOM_PADDING = 24

function finiteSize(value, fallback) {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number : fallback
}

export function getMeasuredNodeSize(node) {
  return {
    width: finiteSize(node?.dimensions?.width, finiteSize(node?.width, 240)),
    height: finiteSize(node?.dimensions?.height, finiteSize(node?.height, 100)),
  }
}

export function getContainerFitSize({ currentWidth, currentHeight, children = [] }) {
  let width = Math.max(CONTAINER_MIN_WIDTH, finiteSize(currentWidth, CONTAINER_MIN_WIDTH))
  let height = Math.max(CONTAINER_MIN_HEIGHT, finiteSize(currentHeight, CONTAINER_MIN_HEIGHT))

  for (const child of children) {
    const size = getMeasuredNodeSize(child)
    width = Math.max(width, finiteSize(child?.position?.x, 0) + size.width + CONTAINER_RIGHT_PADDING)
    height = Math.max(height, finiteSize(child?.position?.y, 0) + size.height + CONTAINER_BOTTOM_PADDING)
  }

  return { width: Math.ceil(width), height: Math.ceil(height) }
}
