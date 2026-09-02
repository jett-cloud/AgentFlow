<!-- src/views/copilot/components/workflow/node/parameter-extractor/ParameterExtractorNode.vue -->
<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div v-if="modelName" class="pe-node-content">
      <div class="model-bar">
        <ModelIcon :provider="modelProvider" :model-name="modelName" size="md" />
        <span class="model-name" :title="modelName">{{ modelName }}</span>
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
  selected: { type: Boolean, default: false }
})

const modelName = computed(() => props.data?.model?.name || props.data?.model?.model || '')
const modelProvider = computed(() => props.data?.model?.provider || '')
</script>

<style scoped>
.pe-node-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 0;
}

.model-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 2px 8px 2px 4px;
  border-radius: 6px;
  background: var(--workflow-block-parma-bg, #f2f4f7);
}

.model-name {
  overflow: hidden;
  color: var(--text-secondary, #344054);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
