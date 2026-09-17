<!-- src/views/copilot/components/workflow/node/question-classifier/QuestionClassifierNode.vue -->
<template>
  <BaseNode :id="id" :data="data" :selected="selected" :read-only="readOnly">
    <div class="qc-body">
      <div v-if="modelName" class="model-bar">
        <ModelIcon :provider="modelProvider" :model-name="modelName" size="md" />
        <span class="model-name" :title="modelName">{{ modelName }}</span>
      </div>
      <div v-for="(item, idx) in classes" :key="item.id" class="topic-row">
        <div class="topic-title">{{ item.label || `Class ${idx + 1}` }}</div>
        <div class="topic-name">{{ item.name || '-' }}</div>
        <NodeHandle
          :node-id="id"
          :data="data"
          type="source"
          position="right"
          :handle-id="item.id"
          :label="item.name || `Class ${idx + 1}`"
          :read-only="readOnly"
          branch
        />
      </div>
    </div>
  </BaseNode>
</template>

<script setup>
import { computed } from 'vue'
import BaseNode from '../base/BaseNode.vue'
import ModelIcon from '../base/ModelIcon.vue'
import NodeHandle from '../base/NodeHandle.vue'
import { useQuestionClassifierConfig } from './useQuestionClassifierConfig.js'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false }
})

defineEmits(['select'])

const { classes } = useQuestionClassifierConfig(props, () => {})
const modelName = computed(() => props.data?.model?.name || props.data?.model?.model || '')
const modelProvider = computed(() => props.data?.model?.provider || '')
</script>

<style scoped>
.qc-body {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding-bottom: 2px;
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
  min-width: 0;
  overflow: hidden;
  color: var(--text-secondary, #344054);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topic-row {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-radius: 6px;
  background: #f2f4f7;
  padding: 4px 6px;
}

.topic-title {
  font-size: 10px;
  font-weight: 600;
  color: #667085;
}

.topic-name {
  font-size: 11px;
  color: #344054;
  padding-right: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

</style>
