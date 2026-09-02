<!-- Mirror Dify llm/node.tsx: compact model bar with provider icon -->
<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div class="llm-node-content">
      <div v-if="modelName" class="model-bar">
        <ModelIcon
          :provider="modelProvider"
          :model-name="modelName"
          size="md"
        />
        <span class="model-name-text" :title="modelName">{{ modelName }}</span>
      </div>
    </div>
  </BaseNode>
</template>

<script setup>
import { computed } from 'vue'
import BaseNode from '../base/BaseNode.vue'
import ModelIcon from '../base/ModelIcon.vue'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const modelName = computed(() => {
  const m = props.data?.model
  if (typeof m === 'string') return m
  return m?.name || m?.model || ''
})

const modelProvider = computed(() => {
  const m = props.data?.model
  if (typeof m === 'string') return ''
  return m?.provider || ''
})

</script>

<style scoped>
.llm-node-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 2px 0;
}

.model-bar {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  min-height: 24px;
  padding: 2px 8px 2px 4px;
  border: 1px solid #eaecf0;
  border-radius: 6px;
  background: #f9fafb;
}

.model-name-text {
  overflow: hidden;
  color: #344054;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

</style>
