<template>
  <div class="setting-row" :class="{ warning }">
    <span class="setting-label">{{ label }}</span>
    <span class="setting-value" :title="displayValue">{{ displayValue }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '' },
  warning: { type: Boolean, default: false },
})

const displayValue = computed(() => String(props.value || '—'))
</script>

<style scoped>
.setting-row {
  display: flex;
  min-height: 24px;
  align-items: center;
  gap: 8px;
  padding: 3px 6px;
  border-radius: 6px;
  background: var(--workflow-block-parma-bg, #f2f4f7);
}

.setting-row.warning {
  border: 1px solid #fedf89;
  background: #fffaeb;
}

.setting-label {
  flex: none;
  color: var(--text-tertiary, #667085);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.setting-value {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: var(--text-secondary, #354052);
  font-size: 11px;
  font-weight: 500;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.warning .setting-value {
  color: #b54708;
}
</style>
