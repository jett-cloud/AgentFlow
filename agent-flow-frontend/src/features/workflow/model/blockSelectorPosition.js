export function getBlockSelectorMenuStyle({ x = 0, y = 0 } = {}) {
  return {
    left: `clamp(8px, ${x}px, calc(100% - var(--canvas-panel-offset, 14px) - 328px))`,
    top: `clamp(8px, ${y}px, calc(100% - 460px))`,
  }
}
