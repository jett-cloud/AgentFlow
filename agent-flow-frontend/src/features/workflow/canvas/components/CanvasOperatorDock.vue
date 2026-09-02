<template>
  <div class="canvas-operator-dock" aria-label="画布操作">
    <div class="dock-group history-group">
      <button type="button" :disabled="readOnly || !canUndo" aria-label="撤销" title="撤销" @click="$emit('undo')">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7 6-4 4 4 4M3 10h8a5 5 0 0 1 5 5" /></svg>
      </button>
      <button type="button" :disabled="readOnly || !canRedo" aria-label="重做" title="重做" @click="$emit('redo')">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m13 6 4 4-4 4M17 10H9a5 5 0 0 0-5 5" /></svg>
      </button>
    </div>

    <div class="dock-group inspect-group">
      <button type="button" :class="{ active: inspectOpen }" aria-label="变量检查" @click="$emit('inspect')">
        变量检查
      </button>
    </div>

    <div class="dock-group zoom-group">
      <button type="button" aria-label="缩小画布" title="缩小" @click="$emit('zoom-out')">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h12" /></svg>
      </button>
      <button type="button" class="zoom-value" aria-label="适应画布" title="适应画布" @click="$emit('fit-view')">
        {{ zoomPercent }}%
      </button>
      <button type="button" aria-label="放大画布" title="放大" @click="$emit('zoom-in')">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h12M10 4v12" /></svg>
      </button>
      <span class="dock-divider" aria-hidden="true"></span>
      <button type="button" aria-label="适应画布" title="适应画布" @click="$emit('fit-view')">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3.5 7V3.5H7M13 3.5h3.5V7M16.5 13v3.5H13M7 16.5H3.5V13" /></svg>
      </button>
      <button
        type="button"
        :class="{ active: minimapOpen }"
        aria-label="切换小地图"
        title="切换小地图"
        @click="$emit('toggle-minimap')"
      >
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3.5 4.5h13v11h-13v-11ZM6 12.5l2.5-2 2 1.5 3-3 2.5 2.5" /></svg>
      </button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  canUndo: { type: Boolean, default: false },
  canRedo: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
  inspectOpen: { type: Boolean, default: false },
  zoomPercent: { type: Number, default: 100 },
  minimapOpen: { type: Boolean, default: true },
})

defineEmits(['undo', 'redo', 'inspect', 'zoom-out', 'zoom-in', 'fit-view', 'toggle-minimap'])
</script>

<style scoped>
.canvas-operator-dock {
  position: absolute;
  inset: auto 0 12px;
  z-index: 40;
  pointer-events: none;
}

.dock-group {
  position: absolute;
  bottom: 0;
  display: flex;
  min-height: 40px;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--components-actionbar-border, rgb(16 24 40 / 6%));
  border-radius: 12px;
  background: var(--components-actionbar-bg, rgb(255 255 255 / 95%));
  box-shadow: 0 4px 12px rgb(16 24 40 / 8%);
  backdrop-filter: blur(8px);
  pointer-events: auto;
}

.history-group {
  left: 14px;
}

.inspect-group {
  left: 50%;
  transform: translateX(-50%);
}

.zoom-group {
  right: clamp(14px, var(--canvas-panel-offset, 14px), calc(100% - 300px));
  transition: right 180ms ease;
}

button {
  display: grid;
  min-width: 34px;
  height: 34px;
  place-items: center;
  padding: 0 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary, #667085);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

button:hover:not(:disabled),
button.active {
  background: var(--components-actionbar-item-bg-active, #eff4ff);
  color: var(--text-accent, #155eef);
}

button:focus-visible {
  outline: 2px solid var(--border-accent, #528bff);
  outline-offset: 2px;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.38;
}

svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.7;
}

.zoom-value {
  min-width: 48px;
  padding-inline: 4px;
}

.dock-divider {
  width: 1px;
  height: 20px;
  margin: 0 2px;
  background: var(--components-actionbar-border, #e4e7ec);
}

@media (max-width: 960px) {
  .inspect-group {
    display: none;
  }
}
</style>
