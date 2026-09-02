<!-- src/views/copilot/components/workflow/node/answer/AnswerNode.vue -->
<!--
  直接回复节点 (Answer Node) - 画布节点卡片渲染组件
  用于 Chatflow（高级对话流模式）的输出节点，在画布节点卡片上直观预览输出文本模板及插值变量。
-->
<template>
  <BaseNode :id="id" :data="data" :selected="selected" :read-only="readOnly">
    <div class="answer-node-content">
      <!-- 1. 已配置直接回复内容时，预览文本模板 (最多展示3行) -->
      <div v-if="data.answer" class="answer-preview">
        <span class="label">ANSWER</span>
        <p class="text">{{ data.answer }}</p>
      </div>

    </div>
  </BaseNode>
</template>

<script setup>
import BaseNode from '../base/BaseNode.vue'

// 节点属性定义：接收画布由 VueFlow 传参
defineProps({
  id: { type: String, required: true },       // 节点唯一标志符
  data: { type: Object, required: true },     // 节点配置数据对象 (包含 answer 属性)
  selected: { type: Boolean, default: false }, // 是否处于选中高亮框状态
  readOnly: { type: Boolean, default: false },
})
</script>

<style scoped>
/* 节点内容排版容器 */
.answer-node-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 0;
}

/* 回复模版文本预览框 */
.answer-preview {
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 11px;
}

.answer-preview .label {
  font-weight: 600;
  color: #64748b;
  display: block;
  margin-bottom: 2px;
}

/* 预览文本样式：超过 3 行自动省略并使用折行保持 */
.answer-preview .text {
  color: #334155;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  white-space: pre-wrap;
  word-break: break-all;
}

</style>
