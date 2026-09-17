<template>
  <nav
    class="canvas-control-rail"
    :class="{ 'is-agent-open': agentOpen }"
    :style="{ '--workflow-assist-panel-width': `${agentPanelWidth}px` }"
    aria-label="画布工具"
  >
    <button type="button" :disabled="readOnly" aria-label="添加节点" title="添加节点" @click="$emit('add-node')">
      <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 3.5v13M3.5 10h13" /></svg>
    </button>
    <button type="button" :disabled="readOnly" aria-label="添加便签" title="添加便签" @click="$emit('add-note')">
      <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 3.5h10v10l-3 3H5v-13ZM12 16.5v-3h3M7.5 7h5M7.5 10h5" /></svg>
    </button>

    <span class="rail-divider" aria-hidden="true"></span>

    <button
      type="button"
      :class="{ active: mode === 'pointer' }"
      aria-label="选择模式"
      title="选择模式 (V)"
      @click="$emit('update:mode', 'pointer')"
    >
      <svg class="filled" viewBox="0 0 20 20" aria-hidden="true"><path d="m5 3.3 9.6 8.8-4.1.5 2.1 4-2.3 1.1-2-4L5 16.3v-13Z" /></svg>
    </button>
    <button
      type="button"
      :class="{ active: mode === 'hand' }"
      aria-label="抓手模式"
      title="抓手模式 (H)"
      @click="$emit('update:mode', 'hand')"
    >
      <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7.2 9.5V5.8a1 1 0 0 1 2 0v3.7-5a1 1 0 0 1 2 0v5-4a1 1 0 0 1 2 0v4.4-2.8a1 1 0 0 1 2 0V12c0 3.1-2.1 5-5.2 5-2.5 0-4-1.5-5-3.8L3.7 10a1.1 1.1 0 0 1 2-.9l1.5 2.1V9.5Z" /></svg>
    </button>

    <span class="rail-divider" aria-hidden="true"></span>

    <button type="button" :disabled="readOnly" aria-label="整理节点" title="整理节点 (Ctrl+O)" @click="$emit('organize')">
      <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3.5 3.5h5v5h-5v-5ZM11.5 3.5h5v5h-5v-5ZM3.5 11.5h5v5h-5v-5ZM14 11v6M11 14h6" /></svg>
    </button>

    <button
      type="button"
      :class="{ active: agentOpen }"
      aria-label="工作流 Agent"
      title="工作流 Agent"
      @click="$emit('agent')"
    >
      <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M6 6.5h8a2.5 2.5 0 0 1 2.5 2.5v4A2.5 2.5 0 0 1 14 15.5H8L4 17v-4A2.5 2.5 0 0 1 3.5 11V9A2.5 2.5 0 0 1 6 6.5ZM7.5 10h.01M10 10h.01M12.5 10h.01M10 6.5v-2M8.5 3.5h3" /></svg>
      <span class="visually-hidden">Agent</span>
    </button>
  </nav>
</template>

<script setup>
defineProps({
  readOnly: { type: Boolean, default: false },
  mode: { type: String, default: 'pointer' },
  agentOpen: { type: Boolean, default: false },
  agentPanelWidth: { type: Number, default: 420 },
})

defineEmits(['add-node', 'add-note', 'update:mode', 'organize', 'agent'])
</script>

<style scoped>
.canvas-control-rail {
  position: absolute;
  top: 50%;
  left: 12px;
  z-index: 40;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 4px;
  transform: translateY(-50%);
  border: 1px solid var(--components-actionbar-border, rgb(16 24 40 / 6%));
  border-radius: 12px;
  background: var(--components-actionbar-bg, rgb(255 255 255 / 95%));
  box-shadow: 0 4px 12px rgb(16 24 40 / 8%);
  backdrop-filter: blur(8px);
  transition: left 180ms ease;
}

.canvas-control-rail.is-agent-open {
  left: clamp(12px, calc(var(--workflow-assist-panel-width, 420px) + 12px), calc(100% - 52px));
}

button {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary, #667085);
  cursor: pointer;
}

button:hover:not(:disabled) {
  background: var(--components-actionbar-item-bg-hover, #f2f4f7);
  color: var(--text-secondary, #344054);
}

button:focus-visible {
  outline: 2px solid var(--border-accent, #528bff);
  outline-offset: 2px;
}

button.active {
  background: var(--components-actionbar-item-bg-active, #eff4ff);
  color: var(--text-accent, #155eef);
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

svg {
  width: 19px;
  height: 19px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.65;
}

svg.filled {
  fill: currentColor;
  stroke: none;
}

.rail-divider {
  width: 24px;
  height: 1px;
  margin: 3px 0;
  background: var(--components-actionbar-border, #e4e7ec);
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

@media (max-width: 959px) {
  .canvas-control-rail.is-agent-open {
    left: clamp(12px, calc(min(92vw, 432px) + 12px), calc(100% - 52px));
  }
}

</style>
