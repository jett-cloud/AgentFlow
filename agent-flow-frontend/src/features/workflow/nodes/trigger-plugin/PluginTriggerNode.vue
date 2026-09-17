<template>
  <BaseNode :id="id" :data="data" :selected="selected" :read-only="readOnly">
    <div class="plugin-trigger-content">
      <div v-if="!data.subscription_id" class="subscription-warning">请选择有效订阅</div>
      <SettingRow
        v-for="item in configRows"
        :key="item.key"
        :label="item.key"
        :value="item.value"
      />
    </div>
  </BaseNode>
</template>

<script setup>
import { computed } from 'vue'
import BaseNode from '../base/BaseNode.vue'
import SettingRow from '../base/SettingRow.vue'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})

function formatValue(rawValue) {
  const value = rawValue && typeof rawValue === 'object' && !Array.isArray(rawValue)
    ? rawValue.value
    : rawValue
  if (value === null || value === undefined) return ''
  if (Array.isArray(value)) return value.join('.')
  if (typeof value === 'object') return JSON.stringify(value)
  const text = String(value)
  return text.toLowerCase().includes('secret') ? '********' : text
}

const configRows = computed(() =>
  Object.entries(props.data?.config || {}).map(([key, value]) => ({
    key,
    value: formatValue(value),
  })),
)
</script>

<style scoped>
.plugin-trigger-content {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.subscription-warning {
  padding: 5px 7px;
  border: 1px solid #fedf89;
  border-radius: 6px;
  background: #fffaeb;
  color: #b54708;
  font-size: 10px;
}
</style>
