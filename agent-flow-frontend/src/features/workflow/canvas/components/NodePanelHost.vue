<template>
  <aside class="node-panel-host" :style="{ width: `${width}px` }" aria-label="节点配置画板">
    <button
      type="button"
      class="panel-resize-handle"
      aria-label="调整节点配置画板宽度"
      @pointerdown="startResize"
      @keydown="handleResizeKeydown"
    >
      <span />
    </button>

    <PanelHeader
      :block-type="nodeType"
      :title="node.data?.title"
      :description="node.data?.desc"
      :legacy-description="node.data?.description"
      :read-only="readOnly"
      :can-run="supportsSingleRun"
      :running="running"
      @update:title="updateTitle"
      @update:description="updateDescription"
      @run="$emit('run', { nodeId: node.id, inputs: {} })"
      @stop="$emit('stop')"
      @close="$emit('close')"
    />

    <div class="node-panel-tabs" role="tablist" aria-label="节点画板页签">
      <button
        v-for="tab in tabs"
        :key="tab"
        type="button"
        role="tab"
        :aria-selected="activeTab === tab"
        :class="{ active: activeTab === tab }"
        @click="$emit('update:activeTab', tab)"
      >
        {{ tab === 'settings' ? '设置' : '上次运行' }}
      </button>
    </div>

    <div v-show="activeTab === 'settings'" class="node-panel-content">
      <component
        :is="panelComponent"
        :node-id="node.id"
        :node-data="node.data"
        :app-id="appId"
        :read-only="readOnly"
        @update:node-data="$emit('update:nodeData', $event)"
        @close="$emit('close')"
        @select-node="$emit('selectNode', $event)"
      />
    </div>

    <LastRunPanel
      v-if="supportsSingleRun && activeTab === 'last-run'"
      :app-id="appId"
      :node-id="node.id"
      :node-data="node.data"
      :live-result="liveResult"
      :running="running"
      :read-only="readOnly"
      @run="$emit('run', $event)"
      @refresh="$emit('refresh')"
    />
  </aside>
</template>

<script setup>
import { computed, onUnmounted } from 'vue'
import LastRunPanel from '../../nodes/shared/LastRunPanel.vue'
import PanelHeader from '../../nodes/shared/PanelHeader.vue'
import { clampNodePanelWidth, getNodePanelTabs } from '../nodePanelHost.js'

const props = defineProps({
  panelComponent: { type: [Object, Function], required: true },
  node: { type: Object, required: true },
  appId: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
  width: { type: Number, default: 420 },
  activeTab: { type: String, default: 'settings' },
  supportsSingleRun: { type: Boolean, default: false },
  liveResult: { type: Object, default: null },
  running: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:width',
  'update:activeTab',
  'update:nodeData',
  'close',
  'selectNode',
  'run',
  'refresh',
  'stop',
])

const tabs = computed(() => getNodePanelTabs(props.supportsSingleRun))
const nodeType = computed(() => props.node.data?.type || props.node.type || 'default')
let resizeState = null

function emitNodeData(patch) {
  emit('update:nodeData', { ...props.node.data, ...patch })
}

function updateTitle(title) {
  emitNodeData({ title })
}

function updateDescription(description) {
  const { description: _legacyDescription, ...data } = props.node.data || {}
  emit('update:nodeData', { ...data, desc: description })
}

function startResize(event) {
  resizeState = { x: event.clientX, width: props.width }
  event.currentTarget?.setPointerCapture?.(event.pointerId)
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'col-resize'
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', stopResize, { once: true })
}

function handlePointerMove(event) {
  if (!resizeState)
    return
  emit('update:width', clampNodePanelWidth(
    resizeState.width + resizeState.x - event.clientX,
    window.innerWidth,
  ))
}

function handleResizeKeydown(event) {
  const delta = event.key === 'ArrowLeft' ? 16 : event.key === 'ArrowRight' ? -16 : 0
  if (!delta)
    return
  event.preventDefault()
  emit('update:width', clampNodePanelWidth(props.width + delta, window.innerWidth))
}

function stopResize() {
  resizeState = null
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
  window.removeEventListener('pointermove', handlePointerMove)
}

onUnmounted(stopResize)
</script>

<style scoped>
.node-panel-host {
  position: relative;
  display: flex;
  height: 100%;
  min-width: 400px;
  flex-shrink: 0;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid var(--components-panel-border, #e4e7ec);
  background: var(--components-panel-bg, #fff);
  box-shadow: -8px 0 24px rgb(16 24 40 / 6%);
}

.panel-resize-handle {
  position: absolute;
  top: 0;
  left: -4px;
  z-index: 100;
  display: flex;
  width: 8px;
  height: 100%;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: col-resize;
}

.panel-resize-handle span {
  width: 2px;
  height: 36px;
  border-radius: 2px;
  background: #d0d5dd;
  transition: height 0.15s ease, background 0.15s ease;
}

.panel-resize-handle:hover span,
.panel-resize-handle:focus-visible span {
  height: 100%;
  background: var(--state-accent-border, #155eef);
}

.panel-resize-handle:focus-visible {
  outline: 2px solid var(--state-accent-border, #155eef);
  outline-offset: -2px;
}

.node-panel-tabs {
  display: flex;
  flex-shrink: 0;
  gap: 4px;
  padding: 0 16px;
  border-bottom: 1px solid var(--components-panel-border, #eaecf0);
  background: var(--components-panel-bg, #fff);
}

.node-panel-tabs button {
  min-height: 40px;
  padding: 8px 4px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-tertiary, #667085);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.node-panel-tabs button + button {
  margin-left: 16px;
}

.node-panel-tabs button.active {
  border-bottom-color: var(--state-accent-border, #155eef);
  color: var(--text-accent, #155eef);
}

.node-panel-tabs button:focus-visible {
  border-radius: 4px;
  outline: 2px solid var(--state-accent-border, #155eef);
  outline-offset: -2px;
}

.node-panel-content {
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

.node-panel-content :deep(> *),
.node-panel-content :deep(.node-panel-shell) {
  height: 100%;
  border-left: 0;
}

.node-panel-content :deep(.panel-header) {
  display: none;
}
</style>

<!--
  Node panels are implemented by many independent components. Keep the form
  control skin at the host boundary so every panel gets the same Dify-like
  interaction states without duplicating CSS in each node implementation.
-->
<style>
.node-panel-host .node-panel-content {
  --node-form-border: #d0d5dd;
  --node-form-border-hover: #98a2b3;
  --node-form-border-focus: #528bff;
  --node-form-focus-ring: rgb(21 94 239 / 10%);
  --node-form-placeholder: #98a2b3;
}

.node-panel-host .node-panel-content .panel-body,
.node-panel-host .node-panel-content .node-panel-body {
  scrollbar-color: #d0d5dd transparent;
  scrollbar-width: thin;
}

.node-panel-host .node-panel-content .form-section {
  gap: 10px;
}

.node-panel-host .node-panel-content .section-label,
.node-panel-host .node-panel-content .el-form-item__label {
  color: #344054;
  font-size: 12px;
  font-weight: 600;
  line-height: 18px;
}

.node-panel-host .node-panel-content .el-form-item {
  margin-bottom: 16px;
}

.node-panel-host .node-panel-content .el-input__wrapper,
.node-panel-host .node-panel-content .el-select__wrapper,
.node-panel-host .node-panel-content .el-input-number .el-input__wrapper {
  min-height: 36px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 0 0 1px var(--node-form-border) inset, 0 1px 2px rgb(16 24 40 / 4%);
  transition: box-shadow 150ms ease, background 150ms ease;
}

.node-panel-host .node-panel-content .el-input__wrapper:hover,
.node-panel-host .node-panel-content .el-select__wrapper:hover,
.node-panel-host .node-panel-content .el-input-number .el-input__wrapper:hover {
  box-shadow: 0 0 0 1px var(--node-form-border-hover) inset, 0 1px 2px rgb(16 24 40 / 4%);
}

.node-panel-host .node-panel-content .el-input__wrapper.is-focus,
.node-panel-host .node-panel-content .el-select__wrapper.is-focused,
.node-panel-host .node-panel-content .el-select__wrapper.is-focus,
.node-panel-host .node-panel-content .el-input-number .el-input__wrapper.is-focus {
  box-shadow: 0 0 0 1px var(--node-form-border-focus) inset, 0 0 0 3px var(--node-form-focus-ring);
}

.node-panel-host .node-panel-content .el-input__inner,
.node-panel-host .node-panel-content .el-select__placeholder,
.node-panel-host .node-panel-content .el-select__selected-item {
  color: #101828;
  font-size: 12px;
}

.node-panel-host .node-panel-content .el-input__inner::placeholder,
.node-panel-host .node-panel-content .el-textarea__inner::placeholder {
  color: var(--node-form-placeholder);
}

.node-panel-host .node-panel-content .el-textarea__inner {
  min-height: 80px;
  padding: 9px 10px;
  border: 0;
  border-radius: 8px;
  outline: none;
  background: #fff;
  color: #101828;
  font-family: inherit;
  font-size: 12px;
  line-height: 18px;
  resize: none;
  box-shadow: 0 0 0 1px var(--node-form-border) inset, 0 1px 2px rgb(16 24 40 / 4%);
  transition: box-shadow 150ms ease;
}

.node-panel-host .node-panel-content .el-textarea__inner:hover {
  box-shadow: 0 0 0 1px var(--node-form-border-hover) inset, 0 1px 2px rgb(16 24 40 / 4%);
}

.node-panel-host .node-panel-content .el-textarea__inner:focus {
  box-shadow: 0 0 0 1px var(--node-form-border-focus) inset, 0 0 0 3px var(--node-form-focus-ring);
}

.node-panel-host .node-panel-content .el-input.is-disabled .el-input__wrapper,
.node-panel-host .node-panel-content .el-select.is-disabled .el-select__wrapper,
.node-panel-host .node-panel-content .el-textarea.is-disabled .el-textarea__inner {
  background: #f9fafb;
  box-shadow: 0 0 0 1px #e4e7ec inset;
}

.node-panel-host .node-panel-content input:not([type='checkbox']):not([type='radio']):not([type='range']):not([type='file']):not(.el-input__inner),
.node-panel-host .node-panel-content textarea:not(.el-textarea__inner),
.node-panel-host .node-panel-content select {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--node-form-border);
  border-radius: 8px;
  outline: none;
  background: #fff;
  color: #101828;
  font: inherit;
  font-size: 12px;
  line-height: 18px;
  box-shadow: 0 1px 2px rgb(16 24 40 / 4%);
  transition: border-color 150ms ease, box-shadow 150ms ease;
}

.node-panel-host .node-panel-content input:not([type='checkbox']):not([type='radio']):not([type='range']):not([type='file']):not(.el-input__inner),
.node-panel-host .node-panel-content select {
  min-height: 36px;
  padding: 0 10px;
}

.node-panel-host .node-panel-content textarea:not(.el-textarea__inner) {
  min-height: 80px;
  padding: 9px 10px;
  resize: none;
}

.node-panel-host .node-panel-content input:not([type='checkbox']):not([type='radio']):not([type='range']):not([type='file']):not(.el-input__inner):hover:not(:disabled),
.node-panel-host .node-panel-content textarea:not(.el-textarea__inner):hover:not(:disabled),
.node-panel-host .node-panel-content select:hover:not(:disabled) {
  border-color: var(--node-form-border-hover);
}

.node-panel-host .node-panel-content input:not([type='checkbox']):not([type='radio']):not([type='range']):not([type='file']):not(.el-input__inner):focus,
.node-panel-host .node-panel-content textarea:not(.el-textarea__inner):focus,
.node-panel-host .node-panel-content select:focus {
  border-color: var(--node-form-border-focus);
  box-shadow: 0 0 0 3px var(--node-form-focus-ring), 0 1px 2px rgb(16 24 40 / 4%);
}

.node-panel-host .node-panel-content input::placeholder,
.node-panel-host .node-panel-content textarea::placeholder {
  color: var(--node-form-placeholder);
}

.node-panel-host .node-panel-content .el-button {
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
}

.node-panel-host .node-panel-content .el-button--primary:not(.is-link):not(.is-plain) {
  border-color: #155eef;
  background: #155eef;
  box-shadow: 0 1px 2px rgb(16 24 40 / 8%);
}

.node-panel-host .node-panel-content .el-switch.is-checked .el-switch__core {
  border-color: #155eef;
  background: #155eef;
}
</style>
