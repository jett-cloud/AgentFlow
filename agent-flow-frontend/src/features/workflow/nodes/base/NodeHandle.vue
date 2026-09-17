<template>
  <div
    class="node-handle-wrap"
    :class="[
      type === 'source' ? 'node-handle-source' : 'node-handle-target',
      { 'is-connected': isConnected, 'is-branch': branch, 'is-centered': centered },
    ]"
  >
    <Handle
      :id="handleId"
      :type="type"
      :position="position"
      class="node-handle-core"
      @pointerdown="handlePointerDown"
      @pointerup="handlePointerUp"
    />
    <button
      v-if="addAction"
      type="button"
      class="node-handle-plus"
      :aria-label="addAction.ariaLabel"
      @pointerdown.stop
      @click="handleAddNode"
    >
      <el-icon><Plus /></el-icon>
    </button>
  </div>
</template>

<script setup>
import { computed, inject } from 'vue'
import { Handle } from '@vue-flow/core'
import { Plus } from '@element-plus/icons-vue'
import { useWorkflowStore } from '@/features/workflow/state/useWorkflowStore.js'
import { getNodeHandleAddAction } from '../../model/nodeHandleInteraction.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  data: { type: Object, required: true },
  type: { type: String, required: true },
  position: { type: String, required: true },
  handleId: { type: String, required: true },
  branch: { type: Boolean, default: false },
  centered: { type: Boolean, default: false },
  label: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
})

const store = useWorkflowStore()
const ui = inject('workflowUi', null)
const readOnly = computed(() => store.readOnly || props.readOnly)

const isConnected = computed(() => {
  const key = props.type === 'source'
    ? '_connectedSourceHandleIds'
    : '_connectedTargetHandleIds'
  return props.data?.[key]?.includes(props.handleId)
})
const addAction = computed(() => getNodeHandleAddAction({
  nodeId: props.nodeId,
  type: props.type,
  handleId: props.handleId,
  label: props.label,
  readOnly: readOnly.value,
  connected: isConnected.value,
}))

let pointerStart = null

function handlePointerDown(event) {
  pointerStart = { x: event.clientX, y: event.clientY }
}

function handlePointerUp(event) {
  if (!pointerStart) return
  const moved = Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y)
  pointerStart = null
  if (moved > 3) return
  if (!addAction.value)
    return
  ui?.openNodeSelector?.({
    ...addAction.value.selector,
    clientX: event.clientX,
    clientY: event.clientY,
    placeImmediately: true,
  })
}

function handleAddNode(event) {
  event.stopPropagation()
  if (!addAction.value)
    return
  const rect = event.currentTarget?.getBoundingClientRect?.()
  ui?.openNodeSelector?.({
    ...addAction.value.selector,
    clientX: props.type === 'target' ? (rect?.left || 0) : (rect?.right || 0),
    clientY: rect ? rect.top + rect.height / 2 : 0,
    placeImmediately: true,
  })
}
</script>

<style scoped>
.node-handle-wrap {
  position: absolute;
  top: 16px;
  z-index: 12;
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  transform: translateY(-50%);
}

.node-handle-target {
  left: -10px;
}

.node-handle-source {
  right: -10px;
}

.node-handle-wrap.is-branch {
  top: 50%;
  right: -21px;
}

.node-handle-wrap.is-centered {
  top: 50%;
  right: -10px;
}

.node-handle-core {
  position: static !important;
  width: 10px;
  height: 10px;
  transform: none !important;
  border: 2px solid var(--workflow-link-line-handle, #085afc);
  background: var(--workflow-handle-bg, #fff);
  transition: width 0.15s ease, height 0.15s ease, background 0.15s ease;
}

.node-handle-wrap:hover .node-handle-core,
.node-handle-wrap.is-connected .node-handle-core {
  border-color: var(--workflow-link-line-active, #085afc);
  background: var(--workflow-link-line-active, #085afc);
}

.node-handle-plus {
  position: absolute;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  z-index: 2;
  background: var(--workflow-link-line-active, #085afc);
  color: #fff;
  font-size: 11px;
  opacity: 0;
  cursor: pointer;
  pointer-events: none;
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.node-handle-plus::before {
  position: absolute;
  inset: -7px;
  content: '';
}

.node-handle-wrap:hover .node-handle-plus,
:global(.base-node:hover .node-handle-plus),
:global(.base-node:focus-within .node-handle-plus),
:global(.base-node.is-selected .node-handle-plus) {
  opacity: 1;
}

.node-handle-plus:focus-visible {
  opacity: 1;
  outline: 2px solid var(--state-accent-border, #155eef);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .node-handle-core {
    transition: none;
  }
}
</style>
