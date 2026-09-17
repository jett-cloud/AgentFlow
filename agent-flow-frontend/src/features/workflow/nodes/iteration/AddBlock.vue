<!-- 对齐 Dify iteration/loop AddBlock：打开统一 BlockSelector（container 模式） -->
<template>
  <div class="iteration-add-block nodrag" ref="containerRef">
    <div class="connector-line">
      <div class="target-dot"></div>
    </div>
    <button
      type="button"
      class="add-block-btn"
      :class="{ 'is-disabled': disabled }"
      :disabled="disabled"
      @click.stop="openSelector"
    >
      <svg class="icon-add" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
        <path d="M11 11V5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/>
      </svg>
      <span>添加节点</span>
    </button>
  </div>
</template>

<script setup>
import { inject } from 'vue'

const props = defineProps({
  disabled: { type: Boolean, default: false },
  containerId: { type: String, required: true },
})

const workflowUi = inject('workflowUi', null)

function openSelector(event) {
  if (props.disabled) return
  workflowUi?.openNodeSelector?.({
    parentId: props.containerId,
    clientX: event.clientX,
    clientY: event.clientY,
    placeImmediately: true,
    mode: 'container',
  })
}
</script>

<style scoped>
.iteration-add-block {
  position: absolute;
  top: 28px;
  left: 56px;
  z-index: 10;
  display: flex;
  align-items: center;
  width: max-content;
  height: 32px;
}
.connector-line {
  position: absolute;
  left: 0;
  top: 15px;
  width: 64px;
  height: 2px;
  background: #d0d5dd;
}
.target-dot {
  position: absolute;
  top: -3px;
  right: 0;
  width: 2px;
  height: 8px;
  background: #155eef;
}
.add-block-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  border: 1px dashed #b2ccff;
  border-radius: 8px;
  background: #f5f8ff;
  color: #155eef;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  margin-left: 64px;
}
.add-block-btn:hover:not(:disabled) {
  background: #eff4ff;
}
.add-block-btn.is-disabled,
.add-block-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.icon-add {
  flex-shrink: 0;
}
</style>
