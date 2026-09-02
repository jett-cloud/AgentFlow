<template>
  <div
    class="candidate-node"
    :style="{
      left: `${x}px`,
      top: `${y}px`,
      transform: `scale(${zoom})`,
    }"
  >
    <div class="candidate-card">
      <div class="candidate-header">
        <BlockIcon :type="type" />
        <span class="candidate-title">{{ title }}</span>
      </div>
      <div class="candidate-body">单击画布放置节点</div>
    </div>
  </div>
</template>

<script setup>
import BlockIcon from '../../nodes/base/BlockIcon.vue'

defineProps({
  type: { type: String, required: true },
  title: { type: String, required: true },
  x: { type: Number, required: true },
  y: { type: Number, required: true },
  zoom: { type: Number, default: 1 },
})
</script>

<style scoped>
.candidate-node {
  position: absolute;
  z-index: 40;
  width: 240px;
  pointer-events: none;
  transform-origin: 0 0;
}

.candidate-card {
  overflow: hidden;
  border: 1px solid var(--state-accent-border, #0033ff);
  border-radius: 16px;
  background: var(--workflow-block-bg, #fcfcfd);
  box-shadow: 0 8px 20px rgba(16, 24, 40, 0.12);
  opacity: 0.82;
}

.candidate-header {
  display: flex;
  min-height: 40px;
  align-items: center;
  gap: 8px;
  padding: 12px 12px 8px;
}

.candidate-title {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary, #101828);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.candidate-body {
  padding: 0 12px 12px;
  color: var(--text-tertiary, #667085);
  font-size: 11px;
}

@media (prefers-reduced-motion: reduce) {
  .candidate-node {
    transition: none;
  }
}
</style>
