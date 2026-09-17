<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div class="code-summary">
      <span class="language">{{ languageLabel }}</span>
      <span>{{ inputCount }} 个输入</span>
      <span>{{ outputCount }} 个输出</span>
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

const languageLabel = computed(() => props.data?.code_language === 'javascript' ? 'JavaScript' : 'Python 3')
const inputCount = computed(() => Array.isArray(props.data?.variables) ? props.data.variables.length : 0)
const outputCount = computed(() => Object.keys(props.data?.outputs || {}).length)
</script>

<style scoped>
.code-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #667085;
  font-size: 11px;
}
.language {
  padding: 2px 6px;
  border-radius: 5px;
  background: #f2f4f7;
  color: #344054;
  font-weight: 600;
}
</style>
