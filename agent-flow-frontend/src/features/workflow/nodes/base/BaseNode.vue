<!-- src/views/copilot/components/workflow/node/base/BaseNode.vue -->
<template>
  <div
    class="base-node"
    :data-node-type="data.type"
    :class="[
      statusBorderClass,
      {
        'is-selected': selected,
        'is-running': isRunning,
        'is-container': isContainer,
        'is-entry': isEntry,
        'is-bundled': isBundled,
        'is-dimmed': data._dimmed,
        'is-waiting': data._waitingRun,
        'is-plugin-missing': data._pluginMissing,
        'is-candidate': presentation.kind === 'candidate' || data._isCandidate,
      }
    ]"
  >
    <div v-if="presentation.showEntryShell" class="entry-node-label">{{ entryLabel }}</div>

    <div v-if="data._pluginMissing && data._pluginInstallLocked" class="plugin-lock-overlay" aria-hidden="true" />

    <ContainerResizer v-if="isContainer && selected && !effectiveReadOnly" :node-id="id" />

    <!-- 1. 输入 Handle (目标锚点，挂载在头部左侧) -->
    <NodeHandle
      v-if="showTargetHandle"
      :node-id="id"
      :data="data"
      type="target"
      position="left"
      handle-id="target"
      :read-only="effectiveReadOnly"
    />

    <!-- 2. 节点顶部悬浮工具栏 (Hover 时显示) -->
    <NodeControl
      v-if="!effectiveReadOnly"
      :node-id="id"
      :node-data="data"
      :disabled="Boolean(data._pluginInstallLocked)"
      :copyable="data.type !== 'start-placeholder'"
    />

    <!-- 3. 通用 Header (1:1 对齐 React 源码 system-sm-semibold-uppercase 风格) -->
    <button
      type="button"
      class="node-header"
      :aria-label="data.title || data.type"
      @click="$emit('select', id)"
    >
      <BlockIcon :type="data.type" :tool-icon="resolvedToolIcon" />
      <div class="node-title-wrapper">
        <span class="node-title">{{ data.title }}</span>
      </div>
      <span v-if="iterationProgress" class="node-run-meta">{{ iterationProgress }}</span>
      <span v-if="loopProgress" class="node-run-meta">{{ loopProgress }}</span>
      <NodeStatusIcon :status="data._runningStatus" />
    </button>

    <!-- 4. 节点独有 Body (由具体子节点填充内容) -->
    <div class="node-body" :class="{ 'container-body': isContainer }">
      <slot :data="data" :id="id"></slot>
    </div>

    <!-- 5. 节点扩展挂件 (如错误处理/重试提示) -->
    <RetryTag :data="data" />
    <ErrorHandleTag
      :node-id="id"
      :data="data"
      :strategy="errorHandleMode"
      :read-only="effectiveReadOnly"
    />
    <div v-if="description" class="node-description">{{ description }}</div>

    <!-- 6. 输出 Handle (源锚点，挂载在头部右侧) -->
    <NodeHandle
      v-if="showSourceHandle"
      :node-id="id"
      :data="data"
      type="source"
      position="right"
      handle-id="source"
      :read-only="effectiveReadOnly"
    />
  </div>
</template>

<script setup>
import { computed, inject } from 'vue'
import BlockIcon from '../base/BlockIcon.vue'
import NodeControl from './NodeControl.vue'
import NodeStatusIcon from './NodeStatusIcon.vue'
import ErrorHandleTag from './ErrorHandleTag.vue'
import NodeHandle from './NodeHandle.vue'
import RetryTag from './RetryTag.vue'
import ContainerResizer from './ContainerResizer.vue'
import { useToolStore } from '@/features/integrations/state/useToolStore.js'
import { useWorkflowStore } from '@/features/workflow/state/useWorkflowStore.js'
import { getEntryLabel, getNodePresentation } from '../../model/nodePresentation.js'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false }
})

defineEmits(['select'])

const store = useWorkflowStore()
const toolStore = useToolStore()
const resolvedToolIcon = computed(() => {
  if (props.data?.type !== 'tool')
    return null
  if (props.data.provider_icon != null && props.data.provider_icon !== '')
    return props.data.provider_icon
  const matched = toolStore.findTool({
    provider_type: props.data.provider_type,
    provider_id: props.data.provider_id,
    tool_name: props.data.tool_name,
  })
  return matched?.icon ?? matched?.icon_small ?? null
})
const bundledNodeIds = inject('bundledNodeIds', null)
const isBundled = computed(() => {
  const ids = bundledNodeIds?.value
  return Array.isArray(ids) && ids.includes(props.id)
})
const effectiveReadOnly = computed(() => props.readOnly || store.readOnly)

// 锚点显示判定：与 Dify React 节点规则保持一致
const presentation = computed(() => getNodePresentation(props.data?.type))
const entryLabel = computed(() => getEntryLabel(props.data?.type))
const showTargetHandle = computed(() => presentation.value.showTargetHandle && !props.data?._isCandidate)
const showSourceHandle = computed(() => presentation.value.showSourceHandle && !props.data?._isCandidate)
const isRunning = computed(() => props.data?._runningStatus === 'running')
const errorHandleMode = computed(() =>
  props.data?.error_handle_mode || props.data?.error_strategy || props.data?.errorStrategy || '',
)

// 判定是否为容器型节点 (如 iteration 迭代, loop 循环)
const isContainer = computed(() => presentation.value.kind === 'container')
const isEntry = computed(() => presentation.value.showEntryShell)
const description = computed(() => props.data?.desc || props.data?.description || '')

/** Live iteration counter (Dify node-sections _iterationIndex/_iterationLength). */
const iterationProgress = computed(() => {
  if (props.data?.type !== 'iteration' || !props.data?._iterationIndex)
    return ''
  const index = props.data._iterationIndex
  const length = props.data._iterationLength
  if (length && index > length)
    return `${length}/${length}`
  return length ? `${index}/${length}` : String(index)
})

/** Live loop counter (Dify node-sections _loopIndex). */
const loopProgress = computed(() => {
  if (props.data?.type !== 'loop' || !props.data?._loopIndex)
    return ''
  return `第 ${props.data._loopIndex} 轮`
})

// 动态计算节点边框样式
const statusBorderClass = computed(() => {
  const status = props.data?._runningStatus
  if (status === 'running') return 'border-running'
  if (status === 'succeeded') return 'border-success'
  if (status === 'failed') return 'border-failed'
  if (status === 'exception') return 'border-exception'
  if (status === 'paused') return 'border-paused'
  return props.selected ? 'border-selected' : 'border-default'
})
</script>

<style scoped>
.base-node {
  position: relative;
  width: 240px;
  background: var(--workflow-block-bg, #ffffff);
  border-radius: 16px;
  border: 1px solid transparent;
  box-shadow: var(--workflow-block-shadow, 0 1px 2px rgba(16, 24, 40, 0.06));
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  padding: 0 0 4px;
  box-sizing: border-box;
}

.base-node > .node-control-toolbar {
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transform: translateY(4px);
  transition: opacity 0.15s ease, transform 0.15s ease, visibility 0.15s ease;
}

.base-node:hover > .node-control-toolbar,
.base-node:focus-within > .node-control-toolbar,
.base-node.is-selected > .node-control-toolbar {
  opacity: 1;
  visibility: visible;
  pointer-events: auto;
  transform: translateY(0);
}

/* 容器节点 (Iteration/Loop) 适应宽高并透明背景 (1:1 对齐 Dify React 源码) */
.base-node.is-container {
  width: 100%;
  height: 100%;
  min-width: 320px;
  min-height: 200px;
  background: rgba(248, 250, 252, 0.85);
  border-radius: 16px;
  border: 1px solid var(--workflow-block-border, #e4e7ec);
  padding: 0;
  display: flex;
  flex-direction: column;
}

.base-node:hover {
  box-shadow: var(--workflow-block-shadow-hover, 0 8px 20px rgba(16, 24, 40, 0.12));
}

.base-node.is-entry::before {
  position: absolute;
  inset: -22px -3px -3px;
  z-index: -1;
  padding: 3px 10px 0;
  border-radius: 18px;
  background: var(--workflow-block-wrapper-bg, #e9ebf0);
  color: var(--text-tertiary, #667085);
  content: '';
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.06em;
}

.entry-node-label {
  position: absolute;
  top: -20px;
  left: 10px;
  z-index: 1;
  color: var(--text-tertiary, #667085);
  font-size: 9px;
  font-weight: 600;
  line-height: 16px;
  letter-spacing: 0.06em;
  pointer-events: none;
}

.base-node.is-dimmed {
  opacity: 0.5;
}

.base-node.is-waiting {
  opacity: 0.7;
}

.base-node.is-plugin-missing:not(.is-selected) {
  border-color: var(--state-warning-border, #f79009);
}

.base-node.is-candidate {
  border-style: dashed;
  background: var(--workflow-block-bg, #fff);
}

.plugin-lock-overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  border-radius: 15px;
  background: color-mix(in srgb, var(--workflow-block-bg, #fff) 80%, transparent);
  backdrop-filter: blur(2px);
}

.base-node.is-bundled {
  border-color: var(--state-accent-border, #0033ff);
  box-shadow: 0 0 0 1px var(--state-accent-border, #0033ff);
}

.node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 12px 12px 8px;
  cursor: pointer;
  width: 100%;
  border: 0;
  background: transparent;
  text-align: left;
}

.node-header:focus-visible {
  outline: 2px solid var(--state-accent-border, #155eef);
  outline-offset: -2px;
}

.is-container .node-header {
  padding: 12px 12px 8px;
  background: transparent;
  border: 0;
}

.node-title-wrapper {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
}

.node-title {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  line-height: 16px;
  letter-spacing: 0.02em;
  color: var(--text-primary, #101828);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-body {
  padding: 0 12px 8px;
  font-size: 12px;
  line-height: 18px;
  color: var(--text-secondary, #475467);
}

.node-body.container-body {
  flex: 1;
  position: relative;
  padding: 0;
  overflow: hidden;
}

/* 动态状态边框高亮 */
.border-default { border-color: transparent; }
.border-selected { border-color: var(--state-accent-border, #155eef); box-shadow: 0 0 0 1px var(--state-accent-border, #155eef); }
.border-running { border-color: var(--state-accent-border, #155eef); animation: pulse-border 1.5s infinite; }
.border-success { border-color: var(--state-success-border, #12b76a); }
.border-failed { border-color: var(--state-destructive-border, #f04438); }
.border-exception { border-color: var(--state-warning-border, #f79009); }
.border-paused { border-color: var(--state-warning-border, #f79009); }

.node-run-meta {
  flex-shrink: 0;
  margin-left: 4px;
  padding: 1px 6px;
  border-radius: 6px;
  background: rgb(0 51 255 / 0.08);
  color: var(--text-accent, #0033ff);
  font-size: 11px;
  font-weight: 600;
  line-height: 16px;
  text-transform: none;
  letter-spacing: 0;
}

.node-description {
  margin: 0 12px 8px;
  color: var(--text-tertiary, #667085);
  font-size: 11px;
  line-height: 16px;
  overflow-wrap: anywhere;
}

@keyframes pulse-border {
  0% { box-shadow: 0 0 0 0 rgba(21, 94, 239, 0.4); }
  70% { box-shadow: 0 0 0 6px rgba(21, 94, 239, 0); }
  100% { box-shadow: 0 0 0 0 rgba(21, 94, 239, 0); }
}

</style>
