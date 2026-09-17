<template>
  <!-- Aligns with Dify header view-history (debug runs ≠ publish versions). -->
  <aside class="run-history-panel" aria-label="运行记录">
    <header>
      <div>
        <h2>运行记录</h2>
        <p>调试运行历史（非发布版本）</p>
      </div>
      <button type="button" aria-label="关闭" @click="$emit('close')">×</button>
    </header>

    <div v-if="loading" class="state">加载中…</div>
    <div v-else-if="error" class="state error">{{ error }}</div>
    <div v-else-if="!items.length" class="state">还没有调试运行记录。</div>
    <ul v-else class="list">
      <li v-for="item in items" :key="item.id">
        <button
          type="button"
          class="row"
          :class="{ active: item.id === activeRunId }"
          :disabled="loadingDetail"
          @click="$emit('select', item)"
        >
          <span class="status" :data-status="item.status">{{ item.status || '—' }}</span>
          <span class="meta">
            <strong>{{ formatTime(item.created_at || item.finished_at) }}</strong>
            <small>
              {{ formatElapsed(item.elapsed_time) || '—' }}
              · {{ item.total_tokens != null ? `${item.total_tokens} tok` : '—' }}
            </small>
          </span>
        </button>
      </li>
    </ul>
  </aside>
</template>

<script setup>
import { formatElapsed } from '../applyWorkflowRunEvent.js'

defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  loadingDetail: { type: Boolean, default: false },
  error: { type: String, default: '' },
  activeRunId: { type: String, default: '' },
})

defineEmits(['close', 'select'])

function formatTime(value) {
  if (!value)
    return '未知时间'
  const ms = typeof value === 'number' ? (value < 1e12 ? value * 1000 : value) : Date.parse(value)
  if (!Number.isFinite(ms))
    return String(value)
  return new Date(ms).toLocaleString()
}
</script>

<style scoped>
.run-history-panel {
  position: absolute;
  top: 56px;
  right: 16px;
  z-index: 55;
  display: flex;
  width: min(360px, calc(100% - 32px));
  max-height: min(480px, calc(100% - 80px));
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 12px 32px rgb(16 24 40 / 12%);
}
header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid #f2f4f7;
}
header h2, header p { margin: 0; }
header h2 { font-size: 14px; color: #101828; }
header p { margin-top: 2px; font-size: 11px; color: #667085; }
header button {
  border: 0;
  background: transparent;
  color: #667085;
  font-size: 18px;
  cursor: pointer;
}
.state {
  padding: 28px 16px;
  color: #98a2b3;
  font-size: 12px;
  text-align: center;
}
.state.error { color: #b42318; }
.list {
  list-style: none;
  margin: 0;
  padding: 8px;
  overflow: auto;
}
.row {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
  padding: 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  text-align: left;
}
.row:hover { background: #f9fafb; }
.row.active {
  border-color: #b2ccff;
  background: #f5f8ff;
}
.status {
  flex-shrink: 0;
  min-width: 64px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  color: #667085;
}
.status[data-status='succeeded'] { color: #079455; }
.status[data-status='failed'] { color: #d92d20; }
.status[data-status='running'] { color: #0033ff; }
.status[data-status='stopped'] { color: #b54708; }
.meta {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}
.meta strong {
  color: #101828;
  font-size: 12px;
}
.meta small {
  color: #667085;
  font-size: 11px;
}
</style>
