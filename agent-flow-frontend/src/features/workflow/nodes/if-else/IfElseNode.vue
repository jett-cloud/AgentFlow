<!-- src/views/copilot/components/workflow/node/if-else/IfElseNode.vue -->
<!--
  IF/ELSE 条件分支节点 - 画布 Node 渲染组件
  特点：节点右侧边缘定制有多个分支输出 Handles (如 IF, ELIF, ELSE)，
  允许用户将不同的判定分支独立拉线连接到下游不同节点。
-->
<template>
  <BaseNode :id="id" :data="data" :selected="selected" :read-only="readOnly">
    <div class="ifelse-body">
      <template v-for="(caseItem, cIdx) in cases" :key="caseItem.case_id || cIdx">
        <div class="case-head-row">
          <div class="case-label">{{ cases.length > 1 ? `CASE ${cIdx + 1}` : '' }}</div>
          <div class="case-kind">{{ cIdx === 0 ? 'IF' : 'ELIF' }}</div>
          <NodeHandle
            :node-id="id"
            :data="data"
            type="source"
            position="right"
            :handle-id="caseItem.case_id || `case-${cIdx}`"
            :label="cIdx === 0 ? 'IF' : `ELIF ${cIdx}`"
            :read-only="readOnly"
            branch
          />
        </div>
        <div v-if="caseItem.conditions?.length" class="condition-list">
          <div v-for="(cond, condIdx) in caseItem.conditions" :key="condIdx" class="cond-row">
            <span class="mono">{{ formatVarSelector(cond.variable_selector) }}</span>
            <span class="op">{{ formatOpName(cond.comparison_operator) }}</span>
            <span class="mono">{{ cond.value || '-' }}</span>
          </div>
        </div>
        <div v-else class="condition-empty">条件未配置</div>
      </template>

      <div class="case-head-row else-row">
        <div class="case-kind">ELSE</div>
        <NodeHandle :node-id="id" :data="data" type="source" position="right" handle-id="false" label="ELSE" :read-only="readOnly" branch />
      </div>
    </div>
  </BaseNode>
</template>

<script setup>
import BaseNode from '../base/BaseNode.vue'
import NodeHandle from '../base/NodeHandle.vue'
import { useIfElseConfig, COMPARISON_OPERATORS } from './useIfElseConfig.js'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false }
})

const { cases } = useIfElseConfig(props, () => {})

// 格式化变量路径文本
const formatVarSelector = (selector) => {
  if (!selector) return '未指定'
  if (Array.isArray(selector)) return selector.join('.')
  return String(selector)
}

// 格式化比较运算符缩写
const formatOpName = (opValue) => {
  const target = COMPARISON_OPERATORS.find((item) => item.value === opValue)
  return target ? target.name.split(' ')[0] : opValue || '=='
}
</script>

<style scoped>
.ifelse-body {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 0 0 2px;
}

.case-head-row {
  position: relative;
  display: flex;
  align-items: center;
  min-height: 24px;
  padding: 0 4px;
}

.case-label {
  font-size: 10px;
  font-weight: 700;
  color: #98a2b3;
}

.case-kind {
  margin-left: auto;
  margin-right: 18px;
  font-size: 12px;
  font-weight: 600;
  color: #344054;
}

.condition-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0 4px;
}

.cond-row {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  border-radius: 6px;
  background: #f2f4f7;
  padding: 4px 6px;
}

.mono {
  font-family: ui-monospace, monospace;
  color: #475467;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.op {
  font-size: 9px;
  color: #155eef;
  font-weight: 600;
  white-space: nowrap;
}

.condition-empty {
  margin: 0 4px;
  font-size: 10px;
  color: #98a2b3;
  border-radius: 6px;
  background: #f9fafb;
  padding: 4px 6px;
}

.else-row {
  justify-content: flex-end;
}

</style>
