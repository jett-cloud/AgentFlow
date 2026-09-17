<template>
  <aside class="history-panel" aria-label="工作流版本历史">
    <header>
      <div>
        <h2>版本历史</h2>
        <p>已发布到 Dify 的工作流版本</p>
      </div>
      <button type="button" aria-label="关闭版本历史" @click="$emit('close')">×</button>
    </header>

    <div v-if="loading" class="history-empty">正在加载版本列表…</div>
    <div v-else-if="error" class="history-empty error">{{ error }}</div>
    <div v-else-if="versions.length" class="history-list">
      <div v-for="version in versions" :key="version.id" class="history-item">
        <div>
          <strong>{{ versionLabel(version) }}</strong>
          <span>{{ formatTime(version.created_at || version.createdAt) }}</span>
        </div>
        <button type="button" :disabled="restoringId === version.id" @click="$emit('restore', version.id)">
          {{ restoringId === version.id ? '恢复中…' : '恢复' }}
        </button>
      </div>
    </div>
    <div v-else class="history-empty">还没有已发布版本。点击顶栏「发布」后会出现在这里。</div>
  </aside>
</template>

<script setup>
defineProps({
  versions: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  restoringId: { type: String, default: '' },
})

defineEmits(['close', 'restore'])

function versionLabel(version) {
  return version.marked_name
    || version.name
    || (version.version ? `版本 ${version.version}` : null)
    || `发布 ${String(version.id || '').slice(0, 8)}`
}

function formatTime(value) {
  if (!value) return ''
  const ts = typeof value === 'number' ? value * (value < 1e12 ? 1000 : 1) : Date.parse(value)
  if (!Number.isFinite(ts)) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(ts))
}
</script>

<style scoped>
.history-panel {
  position: absolute;
  top: 60px;
  right: 12px;
  z-index: 70;
  width: 340px;
  max-height: calc(100% - 76px);
  overflow: hidden;
  border: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
  border-radius: 12px;
  background: var(--components-panel-bg, #fff);
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
}

h2,
p {
  margin: 0;
}

h2 {
  color: var(--text-primary, #101828);
  font-size: 14px;
}

p {
  margin-top: 2px;
  color: var(--text-tertiary, #667085);
  font-size: 11px;
}

header button,
.history-item button {
  padding: 5px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary, #354052);
  cursor: pointer;
}

header button:hover,
header button:focus-visible,
.history-item button:hover,
.history-item button:focus-visible {
  outline: none;
  background: var(--components-actionbar-item-bg-hover, #f2f4f7);
}

.history-item button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.history-list {
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 6px;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px;
  border-radius: 8px;
}

.history-item:hover {
  background: #f9fafb;
}

.history-item div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.history-item strong {
  color: var(--text-primary, #101828);
  font-size: 12px;
}

.history-item span {
  color: var(--text-tertiary, #667085);
  font-size: 10px;
}

.history-empty {
  padding: 24px 14px;
  color: var(--text-tertiary, #667085);
  font-size: 12px;
  text-align: center;
}

.history-empty.error {
  color: #b42318;
}
</style>
