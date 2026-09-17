<template>
  <BaseNode :id="id" :data="data" :selected="selected" :read-only="readOnly">
    <div class="webhook-content">
      <span class="webhook-label">URL</span>
      <div class="webhook-url" :title="data.webhook_url || '—'">{{ data.webhook_url || '—' }}</div>
    </div>
  </BaseNode>
</template>

<script setup>
import BaseNode from '../base/BaseNode.vue'

defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})
</script>

<style scoped>
.webhook-label {
  display: block;
  margin-bottom: 4px;
  color: var(--text-tertiary, #667085);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.04em;
}

.webhook-url {
  overflow: hidden;
  padding: 5px 8px;
  border-radius: 6px;
  background: var(--workflow-block-parma-bg, #f2f4f7);
  color: var(--text-secondary, #354052);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
