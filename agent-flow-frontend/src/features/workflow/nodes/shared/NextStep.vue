<template>
  <section v-if="groups.length" class="next-step-wrapper">
    <header class="next-step-header">
      <h3>下一步</h3>
      <p>添加此工作流中的下一个节点</p>
    </header>

    <div class="next-step-tree">
      <div class="node-icon-box" aria-hidden="true">
        <BlockIcon
          :type="nodeData.type || 'default'"
          :size="18"
          :tool-icon="nodeData.type === 'tool' ? nodeData.provider_icon : null"
        />
      </div>

      <div class="branch-tree" :class="{ 'has-multiple-branches': groups.length > 1 }">
        <div v-for="group in groups" :key="group.id" class="branch-row">
          <div class="branch-line" aria-hidden="true" />
          <div class="branch-card" :class="{ 'is-failure': group.kind === 'failure' }">
            <div v-if="group.name" class="branch-name">{{ group.name }}</div>

            <button
              v-for="node in group.nextNodes"
              :key="node.id"
              type="button"
              class="next-node-card"
              :aria-label="`打开节点 ${getNodeTitle(node)}`"
              @click.stop="$emit('select-node', node.id)"
            >
              <BlockIcon
                :type="getNodeData(node).type || node.type || 'default'"
                :size="16"
                :tool-icon="getNodeData(node).type === 'tool' ? getNodeData(node).provider_icon : null"
              />
              <span>{{ getNodeTitle(node) }}</span>
              <el-icon><ArrowRight /></el-icon>
            </button>

            <button
              type="button"
              class="add-node-card"
              :disabled="readOnly"
              :aria-label="group.name ? `从 ${group.name} 选择下一个节点` : '选择下一个节点'"
              @click.stop="handleAddClick(group, $event)"
            >
              <span class="add-icon-box"><el-icon><Plus /></el-icon></span>
              <span>{{ group.nextNodes.length ? '添加并行节点' : '选择下一个节点' }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, inject } from 'vue'
import { Plus, ArrowRight } from '@element-plus/icons-vue'
import BlockIcon from '../base/BlockIcon.vue'
import { getNextStepGroups } from '../../model/nextStepGroups.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  nextNodes: { type: Array, default: () => [] },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['add-next-node', 'select-node'])
const ui = inject('workflowUi', null)
const graph = inject('workflowGraph', null)

const groups = computed(() => {
  if (graph?.getNodes && graph?.getEdges) {
    return getNextStepGroups({
      nodeId: props.nodeId,
      nodeData: props.nodeData,
      nodes: graph.getNodes(),
      edges: graph.getEdges(),
    })
  }
  return getNextStepGroups({
    nodeId: props.nodeId,
    nodeData: props.nodeData,
  }).map((group, index) => ({
    ...group,
    nextNodes: index === 0 ? props.nextNodes : [],
  }))
})

function getNodeData(node) {
  return node?.data || node || {}
}

function getNodeTitle(node) {
  const data = getNodeData(node)
  return data.title || data.type || node?.type || '下游节点'
}

function handleAddClick(group, event) {
  if (props.readOnly) return
  if (ui?.openNodeSelector) {
    const rect = event?.currentTarget?.getBoundingClientRect?.()
    ui.openNodeSelector({
      direction: 'after',
      nodeId: props.nodeId,
      sourceHandle: group.id,
      clientX: rect?.left || 0,
      clientY: rect?.top || 0,
      preferSourcePosition: true,
    })
    return
  }
  emit('add-next-node', { nodeId: props.nodeId, sourceHandle: group.id })
}
</script>

<style scoped>
.next-step-wrapper {
  user-select: none;
  padding: 16px 20px 20px;
  border-top: 1px solid var(--components-panel-border, #e4e7ec);
}

.next-step-header {
  margin-bottom: 12px;
}

.next-step-header h3,
.next-step-header p {
  margin: 0;
}

.next-step-header h3 {
  color: var(--text-secondary, #344054);
  font-size: 12px;
  font-weight: 600;
  line-height: 18px;
  text-transform: uppercase;
}

.next-step-header p {
  color: var(--text-tertiary, #667085);
  font-size: 12px;
  line-height: 18px;
}

.next-step-tree {
  display: flex;
  align-items: flex-start;
}

.node-icon-box {
  z-index: 1;
  display: flex;
  width: 36px;
  height: 36px;
  flex: none;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--components-panel-border, #e4e7ec);
  border-radius: 10px;
  background: var(--components-panel-bg, #fff);
  box-shadow: 0 1px 2px rgb(16 24 40 / 6%);
}

.branch-tree {
  position: relative;
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 10px;
  padding-left: 24px;
}

.branch-tree::before {
  position: absolute;
  top: 18px;
  left: 0;
  width: 24px;
  height: 1px;
  background: var(--workflow-link-line, #d0d5dd);
  content: '';
}

.branch-tree.has-multiple-branches::after {
  position: absolute;
  top: 18px;
  bottom: 18px;
  left: 12px;
  width: 1px;
  background: var(--workflow-link-line, #d0d5dd);
  content: '';
}

.branch-row {
  position: relative;
  min-width: 0;
}

.branch-line {
  position: absolute;
  top: 18px;
  left: -12px;
  width: 12px;
  height: 1px;
  background: var(--workflow-link-line, #d0d5dd);
}

.branch-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
  padding: 6px;
  border-radius: 12px;
  background: var(--workflow-block-parma-bg, #f2f4f7);
}

.branch-card.is-failure {
  background: var(--state-warning-bg, #fffaeb);
}

.branch-name {
  padding: 0 6px;
  color: var(--text-tertiary, #667085);
  font-size: 10px;
  font-weight: 600;
  line-height: 16px;
  text-transform: uppercase;
}

.next-node-card,
.add-node-card {
  display: flex;
  min-height: 38px;
  width: 100%;
  box-sizing: border-box;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-radius: 9px;
  font: inherit;
  text-align: left;
}

.next-node-card {
  border: 1px solid var(--components-panel-border, #e4e7ec);
  background: var(--components-panel-bg, #fff);
  color: var(--text-primary, #101828);
  cursor: pointer;
}

.next-node-card span {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  font-size: 12px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.next-node-card:hover,
.next-node-card:focus-visible {
  border-color: var(--state-accent-border, #155eef);
}

.add-node-card {
  border: 1px dashed var(--components-panel-border-strong, #d0d5dd);
  background: color-mix(in srgb, var(--components-panel-bg, #fff) 70%, transparent);
  color: var(--text-tertiary, #667085);
  cursor: pointer;
}

.add-node-card:hover:not(:disabled),
.add-node-card:focus-visible {
  border-color: var(--state-accent-border, #155eef);
  background: var(--state-accent-bg, #eff4ff);
  color: var(--text-accent, #155eef);
}

.next-node-card:focus-visible,
.add-node-card:focus-visible {
  outline: 2px solid var(--state-accent-border, #155eef);
  outline-offset: 2px;
}

.add-node-card:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.add-icon-box {
  display: inline-flex;
  width: 22px;
  height: 22px;
  flex: none;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--components-panel-border, #e4e7ec);
  border-radius: 6px;
  background: var(--components-panel-bg, #fff);
}
</style>
