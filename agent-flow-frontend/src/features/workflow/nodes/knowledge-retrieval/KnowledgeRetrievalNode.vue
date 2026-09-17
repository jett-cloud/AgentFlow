<!-- src/views/copilot/components/workflow/node/knowledge-retrieval/KnowledgeRetrievalNode.vue -->
<!--
  知识检索节点 (Knowledge Retrieval Node) - 画布 Node 渲染组件
  用于 RAG 混合检索与向量检索配置，展示检索变量来源、检索模式及 TopK。
-->
<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div class="kr-node-content">
      <!-- 检索模式 Badge -->
      <div class="mode-row">
        <span class="kr-mode-tag">
          {{ formatModeName(data.retrieval_mode) }}
        </span>
        <span class="topk-tag">TOP {{ topK }}</span>
      </div>

      <!-- 检索变量源提示 -->
      <div class="kr-info-box">
        <span class="label">查询变量:</span>
        <span class="query-val">{{ formatSelector(data.query_variable_selector) }}</span>
      </div>
    </div>
  </BaseNode>
</template>

<script setup>
import BaseNode from '../base/BaseNode.vue'
import { computed } from 'vue'
import { RETRIEVAL_MODES } from './useKnowledgeRetrievalConfig.js'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false }
})

const topK = computed(() => {
  return props.data?.top_k ?? props.data?.multiple_retrieval_config?.top_k ?? 4
})

const formatSelector = (selector) => {
  if (!selector) return 'start.query'
  if (Array.isArray(selector)) return selector.join('.')
  return String(selector)
}

const formatModeName = (mode) => {
  const item = RETRIEVAL_MODES.find((m) => m.value === mode)
  return item ? item.label.split(' ')[0] : '混合检索'
}
</script>

<style scoped>
.kr-node-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 0;
}

.mode-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.kr-mode-tag {
  font-size: 10px;
  font-weight: 600;
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
  padding: 2px 6px;
  border-radius: 4px;
}

.topk-tag {
  font-size: 10px;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: ui-monospace, monospace;
}

.kr-info-box {
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.label {
  color: #64748b;
}

.query-val {
  color: #155eef;
  font-weight: 600;
  font-family: ui-monospace, monospace;
}
</style>
