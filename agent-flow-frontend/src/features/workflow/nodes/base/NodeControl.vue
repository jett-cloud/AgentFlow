<template>
  <div class="node-control-toolbar" @click.stop>
    <el-tooltip content="加入 Agent 对话（也可拖动）" placement="top">
      <button
        class="control-btn assist-drag-handle"
        type="button"
        :disabled="disabled"
        aria-label="加入 Agent 对话"
        draggable="true"
        @dragstart="handleAssistDragStart"
        @click="handleAddToAssist"
      >
        <el-icon><ChatDotRound /></el-icon>
      </button>
    </el-tooltip>

    <el-tooltip v-if="showRun" content="运行此步骤" placement="top">
      <button class="control-btn" type="button" :disabled="disabled" aria-label="运行此步骤" @click="handleRun">
        <el-icon><CaretRight /></el-icon>
      </button>
    </el-tooltip>

    <el-tooltip v-if="copyable" content="复制节点" placement="top">
      <button class="control-btn" type="button" :disabled="disabled" aria-label="复制节点" @click="handleCopy">
        <el-icon><CopyDocument /></el-icon>
      </button>
    </el-tooltip>

    <el-tooltip content="删除节点" placement="top">
      <button class="control-btn delete-btn" type="button" :disabled="disabled" aria-label="删除节点" @click="handleDelete">
        <el-icon><Delete /></el-icon>
      </button>
    </el-tooltip>
  </div>
</template>

<script setup>
import { computed, inject } from 'vue'
import { CaretRight, ChatDotRound, CopyDocument, Delete } from '@element-plus/icons-vue'
import { canRunBySingle } from '../../model/canRunBySingle.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, default: () => ({}) },
  disabled: { type: Boolean, default: false },
  copyable: { type: Boolean, default: true },
})

const emit = defineEmits(['run', 'copy', 'delete'])
const core = inject('workflowCore', null)
const graph = inject('workflowGraph', null)
const addSelectionToWorkflowAssist = inject('addSelectionToWorkflowAssist', null)

const isChildNode = computed(() => {
  const nodes = graph?.getNodes?.() || []
  const node = nodes.find(n => n.id === props.nodeId)
  return !!(node?.parentNode || node?.parentId)
})

const showRun = computed(() => canRunBySingle(props.nodeData?.type, isChildNode.value))

const handleRun = () => {
  core?.runNode?.(props.nodeId)
  emit('run', props.nodeId)
}

const handleAssistDragStart = (event) => {
  const payload = JSON.stringify({
    id: props.nodeId,
    title: props.nodeData?.title || props.nodeData?.type || props.nodeId,
    type: props.nodeData?.type || '',
  })
  event.dataTransfer?.setData('application/x-workflow-assist-node', payload)
  event.dataTransfer?.setData('text/plain', props.nodeData?.title || props.nodeId)
  if (event.dataTransfer)
    event.dataTransfer.effectAllowed = 'copy'
}

const handleAddToAssist = () => addSelectionToWorkflowAssist?.(props.nodeId)

const handleCopy = () => {
  if (core?.duplicateNode)
    core.duplicateNode(props.nodeId)
  emit('copy', props.nodeId)
}

const handleDelete = () => {
  if (core?.removeNode)
    core.removeNode(props.nodeId)
  emit('delete', props.nodeId)
}
</script>

<style scoped>
.node-control-toolbar {
  position: absolute;
  top: -40px;
  right: 0;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px;
  background: var(--components-actionbar-bg, rgba(255, 255, 255, 0.95));
  border: 1px solid var(--components-actionbar-border, rgba(16, 24, 40, 0.04));
  border-radius: 10px;
  box-shadow: 0 4px 12px rgba(16, 24, 40, 0.1);
  backdrop-filter: blur(8px);
  z-index: 30;
}

.control-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  border-radius: 7px;
  cursor: pointer;
  color: #606266;
  transition: all 0.2s;
}

.control-btn:hover {
  background: #f2f4f7;
  color: #155eef;
}

.control-btn:focus-visible {
  outline: 2px solid var(--state-accent-border, #155eef);
  outline-offset: 1px;
}

.control-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.control-btn.delete-btn:hover {
  background: #fef0f0;
  color: #f56c6c;
}
</style>
