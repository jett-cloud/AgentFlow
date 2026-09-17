<template>
  <!-- Aligns with Dify TracingPanel flat NodePanel mode (collapse + I/O). -->
  <div class="tracing-panel">
    <div v-if="items.length" class="list">
      <article
        v-for="(item, index) in items"
        :key="`${item.nodeId}-${item.retryIndex || 0}-${index}`"
        class="item"
        :class="{ active: item.nodeId === selectedNodeId, open: isOpen(index) }"
      >
        <button type="button" class="item-header" @click="toggle(index, item.nodeId)">
          <span class="chevron" aria-hidden="true">{{ isOpen(index) ? '▾' : '▸' }}</span>
          <span class="title">{{ item.title || item.nodeId }}</span>
          <span v-if="item.retryIndex" class="meta-chip">retry {{ item.retryIndex }}</span>
          <span v-if="elapsedOf(item)" class="meta-chip">{{ elapsedOf(item) }}</span>
          <span v-if="tokensOf(item) != null" class="meta-chip">{{ tokensOf(item) }} tok</span>
          <span class="status" :data-status="item.status">{{ statusLabel(item.status) }}</span>
        </button>

        <div v-if="isOpen(index)" class="item-body">
          <div v-if="item.error" class="error">{{ formatError(item.error) }}</div>
          <div class="grid">
            <div>
              <h3>INPUT</h3>
              <pre>{{ formatJsonValue(item.inputs) }}</pre>
            </div>
            <div>
              <h3>OUTPUT</h3>
              <pre>{{ formatJsonValue(item.outputs) }}</pre>
            </div>
          </div>
          <template v-if="item.processData">
            <h3>PROCESS DATA</h3>
            <pre>{{ formatJsonValue(item.processData) }}</pre>
          </template>
          <div v-if="item.nodeType" class="foot">{{ item.nodeType }}</div>
        </div>
      </article>
    </div>
    <div v-else class="empty">运行后节点轨迹会显示在这里。</div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import {
  extractTotalTokens,
  formatElapsed,
  formatJsonValue,
} from './applyWorkflowRunEvent.js'

const props = defineProps({
  items: { type: Array, default: () => [] },
  selectedNodeId: { type: String, default: '' },
})

const emit = defineEmits(['select-node'])

const openIndexes = ref(new Set())

watch(() => props.items.length, (len, prev) => {
  // Auto-expand the newest running/finished entry for live feel.
  if (len > (prev || 0))
    openIndexes.value = new Set([len - 1])
})

function isOpen(index) {
  return openIndexes.value.has(index)
}

function toggle(index, nodeId) {
  const next = new Set(openIndexes.value)
  if (next.has(index))
    next.delete(index)
  else
    next.add(index)
  openIndexes.value = next
  if (nodeId)
    emit('select-node', nodeId)
}

function statusLabel(status) {
  return {
    running: '运行中',
    succeeded: '成功',
    failed: '失败',
    exception: '异常',
    paused: '暂停',
    waiting: '等待',
  }[status] || '等待'
}

function elapsedOf(item) {
  return formatElapsed(item?.elapsed_time)
}

function tokensOf(item) {
  return extractTotalTokens(item?.executionMetadata) ?? extractTotalTokens(item)
}

function formatError(error) {
  if (!error)
    return ''
  return typeof error === 'string' ? error : (error.message || String(error))
}
</script>

<style scoped>
.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.item {
  border: 1px solid #eaecf0;
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}
.item.active {
  border-color: #b2ccff;
  background: rgba(0, 51, 255, 0.04);
}
.item-header {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
}
.chevron {
  color: #98a2b3;
  font-size: 10px;
  width: 10px;
}
.title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 600;
  color: #101828;
}
.meta-chip {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 999px;
  background: #f2f4f7;
  color: #667085;
  font-size: 10px;
}
.status {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 600;
  color: #667085;
}
.status[data-status='succeeded'] { color: #079455; }
.status[data-status='failed'],
.status[data-status='exception'] { color: #d92d20; }
.status[data-status='running'] { color: #0033ff; }
.status[data-status='paused'] { color: #f79009; }
.item-body {
  padding: 0 10px 10px;
  border-top: 1px solid #f2f4f7;
}
.error {
  margin: 8px 0;
  padding: 6px 8px;
  border-radius: 7px;
  background: #fef3f2;
  color: #b42318;
  font-size: 11px;
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 8px;
}
h3 {
  margin: 8px 0 4px;
  color: #667085;
  font-size: 10px;
  text-transform: uppercase;
}
pre {
  margin: 0;
  max-height: 140px;
  overflow: auto;
  padding: 8px;
  border-radius: 7px;
  background: #f2f4f7;
  font: 10px/1.5 ui-monospace, Consolas, monospace;
  white-space: pre-wrap;
}
.foot {
  margin-top: 8px;
  color: #98a2b3;
  font-size: 10px;
}
.empty {
  padding: 28px 12px;
  color: #98a2b3;
  font-size: 12px;
  text-align: center;
}
@media (max-width: 640px) {
  .grid { grid-template-columns: 1fr; }
}
</style>
