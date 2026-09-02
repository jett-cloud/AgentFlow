<!-- src/views/copilot/components/workflow/node/end/EndNode.vue -->
<!--
  结束节点 (End Node) - 画布节点卡片渲染组件
  用于 Workflow（工作流模式）的终点，在画布节点卡片上直观呈现配置的输出变量名和引用的上游变量选择路径。
-->
<template>
  <BaseNode :id="id" :data="data" :selected="selected" :read-only="readOnly">
    <!-- 1. 当已配置输出变量时，循环渲染输出变量列表 -->
    <div v-if="outputs && outputs.length" class="end-node-content">
      <div 
        v-for="(item, index) in outputs" 
        :key="item.variable + index"
        class="output-item-row"
      >
        <!-- 左侧：输出变量图标与变量名 -->
        <div class="output-left">
          <!-- Dify 绿色风格变量 {x} 图标 -->
          <svg class="var-icon-svg" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M4.5 3.5L3 8L4.5 12.5" stroke="#10B981" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M11.5 3.5L13 8L11.5 12.5" stroke="#10B981" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M9 5.5L7 10.5" stroke="#10B981" stroke-width="1.25" stroke-linecap="round"/>
          </svg>
          <!-- 变量 key 名称 (如 result, text) -->
          <span class="var-key" :title="item.variable">{{ item.variable }}</span>
        </div>

        <!-- 右侧：绑定的上游变量节点路径 Selector 标签 (如 llm.text) -->
        <div class="output-right">
          <span class="selector-text" :title="formatValueSelector(item.value_selector)">
            {{ formatValueSelector(item.value_selector) }}
          </span>
        </div>
      </div>
    </div>
  </BaseNode>
</template>

<script setup>
import { computed } from 'vue'
import BaseNode from '../base/BaseNode.vue'

// 节点属性定义：从 VueFlow 传参接收
const props = defineProps({
  id: { type: String, required: true },       // 节点唯一 ID
  data: { type: Object, required: true },     // 节点完整配置数据 (包含 outputs 数组)
  selected: { type: Boolean, default: false }, // 当前节点在画布中是否处于选中高亮状态
  readOnly: { type: Boolean, default: false },
})

// 响应式获取当前配置的输出变量数组
const outputs = computed(() => {
  return (props.data?.outputs || []).filter(item => (
    Array.isArray(item?.value_selector) && item.value_selector.length > 0
  ))
})

/**
 * 格式化变量选择器路径 (value_selector)
 * 例如把 ['llm', 'text'] 拼接转换为字符串 "llm.text"
 */
const formatValueSelector = (selector) => {
  if (!selector) return '未绑定'
  if (Array.isArray(selector)) {
    return selector.join('.') || '未绑定'
  }
  return String(selector)
}
</script>

<style scoped>
/* 节点内容容器基础排版 */
.end-node-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 10px 8px 10px;
}

/* 每一个输出变量条目的横向两端对齐行 */
.output-item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 24px;
  background-color: #f0fdf4;
  border: 1px solid #dcfce7;
  border-radius: 6px;
  padding: 0 6px;
  gap: 8px;
}

/* 左侧变量图标与名称容器 */
.output-left {
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
  font-weight: 500;
  color: #065f46;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 右侧绑定路径值样式 */
.output-right {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.selector-text {
  font-size: 10px;
  color: #047857;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  background: rgba(16, 185, 129, 0.1);
  padding: 1px 4px;
  border-radius: 4px;
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

</style>
