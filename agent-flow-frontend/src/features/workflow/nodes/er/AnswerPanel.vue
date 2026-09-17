<template>
  <div class="answer-panel">
    <div class="panel-header">
      <div class="header-left">
        <BlockIcon type="answer" :size="20" />
        <input v-model="nodeTitle" class="title-input" placeholder="直接回复" :disabled="readOnly" />
      </div>
      <button class="close-btn" type="button" aria-label="关闭面板" @click="$emit('close')">
        <el-icon><Close /></el-icon>
      </button>
    </div>

    <div class="panel-body">
      <div class="form-section">
        <label class="section-label">回复内容 (Answer)</label>
        <PromptVariableTextarea
          v-model="answer"
          :rows="8"
          :node-id="nodeId"
          :read-only="readOnly"
          :filter-var="answerVariableFilter"
          placeholder="输入直接回复用户的文本或 Markdown，支持插入上游变量"
        />

        <div class="hint-box">
          <span class="hint-title">提示：</span>
          <p class="hint-text">
            此内容会在 Chatflow 中回复给用户；输入 { 或点击“插入变量”可选择当前节点可用的上游变量。
          </p>
        </div>
      </div>

      <NextStep :node-id="nodeId" :node-data="nodeData" :read-only="readOnly" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Close } from '@element-plus/icons-vue'
import BlockIcon from '../base/BlockIcon.vue'
import NextStep from '../shared/NextStep.vue'
import PromptVariableTextarea from '../shared/PromptVariableTextarea.vue'
import { useAnswerConfig } from './useAnswerConfig.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'update:nodeData'])
const { readOnly, answer, answerVariableFilter } = useAnswerConfig(props, emit)

const nodeTitle = computed({
  get: () => props.nodeData?.title || '直接回复',
  set: title => emit('update:nodeData', { ...props.nodeData, title }),
})
</script>

<style scoped>
.answer-panel {
  display: flex;
  height: 100%;
  max-height: 100%;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid #eaecf0;
  background: #fff;
}

.panel-header {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #f2f4f7;
  background: #fafafa;
  padding: 12px 16px;
}

.header-left {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 8px;
}

.title-input {
  width: 100%;
  border: 1px solid transparent;
  border-radius: 4px;
  outline: none;
  background: transparent;
  padding: 2px 6px;
  color: #101828;
  font-size: 14px;
  font-weight: 600;
}

.title-input:hover:not(:disabled) {
  border-color: #d0d5dd;
  background: #fff;
}

.close-btn {
  border: 0;
  border-radius: 4px;
  background: transparent;
  padding: 4px;
  color: #667085;
  cursor: pointer;
}

.close-btn:hover {
  background: #f2f4f7;
  color: #101828;
}

.panel-body {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  padding: 16px;
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-label {
  color: #344054;
  font-size: 12px;
  font-weight: 600;
}

.hint-box {
  margin-top: 4px;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
  background: #f8fafc;
  padding: 8px 10px;
}

.hint-title {
  color: #475569;
  font-size: 11px;
  font-weight: 600;
}

.hint-text {
  margin: 2px 0 0;
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}
</style>
