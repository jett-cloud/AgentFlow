<!-- src/views/copilot/components/workflow/node/start/StartNode.vue -->
<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div v-if="variables && variables.length" class="start-node-content">
      <div 
        v-for="item in variables" 
        :key="item.variable"
        class="var-item-row"
      >
        <div class="var-left">
          <!-- Dify 风格紫蓝色变量图标 -->
          <svg class="var-icon-svg" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M4.5 3.5L3 8L4.5 12.5" stroke="#155EEF" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M11.5 3.5L13 8L11.5 12.5" stroke="#155EEF" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M9 5.5L7 10.5" stroke="#155EEF" stroke-width="1.25" stroke-linecap="round"/>
          </svg>
          <span class="var-key" :title="item.variable">{{ item.variable }}</span>
        </div>
        <div class="var-right">
          <span v-if="item.required" class="required-text">Required</span>
          <span class="type-text">{{ formatVarTypeTag(item.type) }}</span>
        </div>
      </div>
    </div>
  </BaseNode>
</template>

<script setup>
import { computed } from 'vue'
import BaseNode from '../base/BaseNode.vue'
import { formatVarTypeTag } from './useStartConfig.js'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false }
})

const variables = computed(() => {
  return props.data?.variables || []
})
</script>

<style scoped>
.start-node-content {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 4px 10px 8px 10px;
}

.var-item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 24px;
  background-color: #f2f4f7;
  border-radius: 6px;
  padding: 0 6px;
  gap: 8px;
}

.var-left {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.var-icon-svg {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.var-key {
  font-size: 12px;
  font-weight: 400;
  color: #344054;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.var-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.required-text {
  font-size: 10px;
  color: #98a2b3;
  text-transform: uppercase;
  font-weight: 500;
}

.type-text {
  font-size: 10px;
  color: #667085;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
</style>
