<!-- src/views/copilot/components/workflow/components/CustomEdge.vue -->
<!--
  自定义边：贝塞尔曲线 + hover 时中点显示删除按钮。
  对齐 Dify custom-edge 的交互（悬停出现操作按钮）。
  通过 inject('workflowCore') 拿到内核以执行删除。
-->
<template>
  <BaseEdge
    :id="id"
    :path="path[0]"
    :style="edgeStyle"
    :marker-end="markerEnd"
    :interaction-width="24"
    @dblclick.stop="onEdgeDblClick"
    @mouseenter="onMouseEnter"
    @mouseleave="onMouseLeave"
  />

  <EdgeLabelRenderer>
    <div
      class="edge-label-wrapper"
      :style="{
        transform: `translate(-50%, -50%) translate(${path[1]}px, ${path[2]}px)`,
      }"
      @mouseenter="onMouseEnter"
      @mouseleave="onMouseLeave"
    >
      <div v-show="isTriggerVisible && !readOnly" class="edge-actions">
        <button class="edge-action-btn edge-add-btn" type="button" aria-label="在连线上添加节点" title="在连线上添加节点" @click.stop="onAdd($event)">＋</button>
        <button class="edge-action-btn edge-delete-btn" type="button" aria-label="删除连线" title="删除连线" @click.stop="onDelete">×</button>
      </div>
    </div>
  </EdgeLabelRenderer>
</template>

<script setup>
import { computed, inject, ref } from 'vue'
import { BaseEdge, EdgeLabelRenderer, getBezierPath } from '@vue-flow/core'
import { useWorkflowStore } from '@/features/workflow/state/useWorkflowStore.js'
import { resolveEdgeStroke } from '../../model/canvasRuntime.js'

defineOptions({
  name: 'CustomEdge',
  inheritAttrs: false,
})

const props = defineProps({
  id: { type: String, required: true },
  sourceX: { type: Number, required: true },
  sourceY: { type: Number, required: true },
  targetX: { type: Number, required: true },
  targetY: { type: Number, required: true },
  sourcePosition: { type: String, default: 'right' },
  targetPosition: { type: String, default: 'left' },
  markerEnd: { type: String, default: '' },
  selected: { type: Boolean, default: false },
  source: { type: String, required: true },
  sourceHandleId: { type: String, default: 'source' },
  data: { type: Object, default: () => ({}) },
})

const store = useWorkflowStore()
const readOnly = computed(() => store.readOnly)
const hovered = ref(false)
let leaveTimer = null

// 从画布注入的交互内核（在 WorkflowCanvas 中 provide）
const core = inject('workflowCore', null)
const ui = inject('workflowUi', null)

const path = computed(() =>
  getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  }),
)

const isTriggerVisible = computed(() => !!(props.data?._hovering || hovered.value))

const edgeStyle = computed(() => {
  const waiting = !!props.data?._waitingRun
  const stroke = resolveEdgeStroke({
    selected: props.selected,
    hovering: isTriggerVisible.value,
    sourceHandleId: props.sourceHandleId,
    sourceRunningStatus: props.data?._sourceRunningStatus,
    targetRunningStatus: props.data?._targetRunningStatus,
  })
  return {
    strokeWidth: 2,
    cursor: readOnly.value ? 'default' : 'pointer',
    stroke,
    opacity: waiting ? 0.7 : 1,
  }
})

function onMouseEnter() {
  if (leaveTimer) {
    clearTimeout(leaveTimer)
    leaveTimer = null
  }
  hovered.value = true
}

function onMouseLeave() {
  if (leaveTimer) clearTimeout(leaveTimer)
  leaveTimer = setTimeout(() => {
    hovered.value = false
  }, 150)
}

function onEdgeDblClick(e) {
  if (readOnly.value) return
  e?.stopPropagation?.()
  core?.removeEdge?.(props.id)
}

function onAdd(event) {
  ui?.openNodeSelector?.({
    edgeId: props.id,
    clientX: event?.clientX,
    clientY: event?.clientY,
    placeImmediately: true,
  })
}

function onDelete() {
  if (readOnly.value) return
  core?.removeEdge?.(props.id)
}
</script>

<style scoped>
.edge-label-wrapper {
  position: absolute;
  pointer-events: all;
  /* 扩大 hover 命中区域 */
  width: 44px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.edge-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--components-actionbar-border, #e4e7ec);
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(16, 24, 40, 0.12);
}

.edge-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #667085;
  font-size: 15px;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.edge-action-btn:focus-visible {
  outline: 2px solid var(--state-accent-border, #0033ff);
  outline-offset: 1px;
}

.edge-add-btn:hover {
  background: #eff4ff;
  color: #155eef;
}

.edge-delete-btn:hover {
  background: #fef3f2;
  color: #f04438;
}
</style>
