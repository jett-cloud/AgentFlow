<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div v-if="configurationRows.length || authorizationRequired" class="tool-node-content">
      <div v-for="row in configurationRows" :key="row.key" class="configuration-row">
        <span class="configuration-key" :title="row.key">{{ row.key }}</span>
        <span class="configuration-value" :title="row.title">{{ row.value }}</span>
      </div>
      <div v-if="authorizationRequired" class="authorization-warning">
        <span class="warning-dot" />
        <span>需要授权</span>
      </div>
    </div>
  </BaseNode>
</template>

<script setup>
import { computed } from 'vue'
import BaseNode from '../base/BaseNode.vue'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const SECRET_TYPES = new Set(['secret-input', 'secret_input', 'password'])
const SECRET_KEY = /token|secret|password|api[_-]?key/i

function displayConfiguration(key, configuration) {
  const value = configuration && typeof configuration === 'object' && 'value' in configuration
    ? configuration.value
    : configuration
  const type = configuration && typeof configuration === 'object' ? configuration.type : ''
  if (SECRET_TYPES.has(type) || SECRET_KEY.test(key))
    return '********'
  if (value == null || Number.isNaN(value))
    return ''
  if (typeof value === 'object')
    return value.model || value.name || ''
  return String(value)
}

const configurationRows = computed(() => Object.entries(props.data?.tool_configurations || {})
  .map(([key, configuration]) => {
    const value = displayConfiguration(key, configuration)
    return { key, value, title: value }
  })
  .filter(row => row.value !== ''))

const authorizationRequired = computed(() => Boolean(
  props.data?._authorizationRequired || props.data?._credentialMissing,
))
</script>

<style scoped>
.tool-node-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
}

.configuration-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 24px;
  padding: 0 6px;
  border-radius: 6px;
  background: var(--workflow-block-parma-bg, #f2f4f7);
}

.configuration-key {
  max-width: 100px;
  overflow: hidden;
  color: var(--text-tertiary, #667085);
  font-size: 11px;
  font-weight: 500;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.configuration-value {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: var(--text-secondary, #344054);
  font-size: 12px;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.authorization-warning {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 0 6px;
  border: 1px solid var(--state-warning-border, #f79009);
  border-radius: 6px;
  background: #fffaeb;
  color: #b54708;
  font-size: 12px;
}

.warning-dot {
  width: 4px;
  height: 4px;
  border-radius: 1px;
  background: currentColor;
}
</style>
