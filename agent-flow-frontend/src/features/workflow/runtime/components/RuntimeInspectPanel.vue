<template>
  <section class="runtime-panel" aria-label="工作流运行与变量检查">
    <header class="runtime-header">
      <div>
        <h2>变量检查</h2>
        <p>查看节点最近一次运行的输入和输出</p>
      </div>
      <div class="runtime-actions">
        <button type="button" @click="$emit('clear')">清空</button>
        <button type="button" aria-label="关闭变量检查" @click="$emit('close')">×</button>
      </div>
    </header>

    <div v-if="items.length" class="runtime-list">
      <article
        v-for="item in items"
        :key="item.nodeId"
        class="runtime-item"
        :class="{ active: item.nodeId === selectedNodeId }"
      >
        <button class="runtime-item-header" type="button" @click="$emit('select-node', item.nodeId)">
          <span class="node-title">{{ item.title || item.nodeId }}</span>
          <span class="status" :data-status="item.status">{{ statusLabel(item.status) }}</span>
        </button>
        <div v-if="item.error" class="runtime-error" aria-live="polite">{{ item.error }}</div>
        <div class="runtime-values">
          <div>
            <h3>输入</h3>
            <pre>{{ formatValue(item.inputs) }}</pre>
          </div>
          <div>
            <h3>输出</h3>
            <pre>{{ formatValue(item.outputs) }}</pre>
          </div>
        </div>
      </article>
    </div>
    <div v-else class="runtime-empty">运行节点后，输入和输出会显示在这里。</div>
  </section>
</template>

<script setup>
defineProps({
  items: { type: Array, default: () => [] },
  selectedNodeId: { type: String, default: '' },
})

defineEmits(['clear', 'close', 'select-node'])

function statusLabel(status) {
  return {
    running: '运行中',
    succeeded: '成功',
    failed: '失败',
    exception: '异常',
  }[status] || '等待'
}

function formatValue(value) {
  if (value === undefined || value === null) return '—'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
</script>

<style scoped>
.runtime-panel {
  position: absolute;
  right: 16px;
  bottom: 80px;
  z-index: 45;
  display: flex;
  width: min(560px, calc(100% - 32px));
  max-height: min(480px, calc(100% - 140px));
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
  border-radius: 14px;
  background: var(--components-panel-bg, #fff);
}

.runtime-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
}

h2,
h3,
p {
  margin: 0;
}

h2 {
  color: var(--text-primary, #101828);
  font-size: 14px;
}

.runtime-header p {
  margin-top: 2px;
  color: var(--text-tertiary, #667085);
  font-size: 11px;
}

.runtime-actions {
  display: flex;
  gap: 4px;
}

.runtime-actions button {
  padding: 5px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary, #354052);
  cursor: pointer;
}

.runtime-actions button:hover,
.runtime-actions button:focus-visible {
  outline: none;
  background: var(--components-actionbar-item-bg-hover, #f2f4f7);
}

.runtime-list {
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 8px;
}

.runtime-item {
  border-radius: 10px;
}

.runtime-item.active {
  background: var(--state-accent-active, rgba(0, 51, 255, 0.08));
}

.runtime-item-header {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  padding: 8px;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.node-title {
  color: var(--text-primary, #101828);
  font-size: 12px;
  font-weight: 600;
}

.status {
  color: var(--text-tertiary, #667085);
  font-size: 10px;
}

.status[data-status='succeeded'] {
  color: #079455;
}

.status[data-status='failed'],
.status[data-status='exception'] {
  color: #d92d20;
}

.status[data-status='running'] {
  color: var(--text-accent, #0033ff);
}

.runtime-values {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 0 8px 10px;
}

.runtime-values h3 {
  margin-bottom: 4px;
  color: var(--text-tertiary, #667085);
  font-size: 10px;
  text-transform: uppercase;
}

pre {
  min-height: 48px;
  max-height: 180px;
  margin: 0;
  overflow: auto;
  padding: 8px;
  border-radius: 7px;
  background: var(--workflow-block-parma-bg, #f2f4f7);
  color: var(--text-secondary, #354052);
  font: 10px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.runtime-error {
  margin: 0 8px 8px;
  padding: 6px 8px;
  border-radius: 7px;
  background: #fef3f2;
  color: #b42318;
  font-size: 11px;
}

.runtime-empty {
  padding: 28px 16px;
  color: var(--text-tertiary, #667085);
  font-size: 12px;
  text-align: center;
}

@media (max-width: 640px) {
  .runtime-values {
    grid-template-columns: 1fr;
  }
}
</style>
