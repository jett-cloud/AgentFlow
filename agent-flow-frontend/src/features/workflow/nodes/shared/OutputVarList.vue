<!-- panel/base/OutputVarList.vue -->
<!--
  展示节点固定/动态输出变量列表（对齐 Dify PanelOutputSection 的只读展示部分）。
-->
<template>
  <div class="output-var-list">
    <div
      v-for="v in resolvedVars"
      :key="v.variable"
      class="var-badge"
    >
      <span class="var-name">{{ v.variable }}</span>
      <span class="var-type">{{ typeLabel(v.type) }}</span>
      <span v-if="v.des" class="var-desc">{{ v.des }}</span>
    </div>
    <div v-if="resolvedVars.length === 0" class="empty-tip">暂无输出变量</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { getNodeOutputVars } from '../../model/variableOutputs.js'

const props = defineProps({
  /** 直接传 vars 列表 */
  vars: { type: Array, default: null },
  /** 或传 nodeType + nodeData 自动推导 */
  nodeType: { type: String, default: '' },
  nodeData: { type: Object, default: () => ({}) },
  /** 额外追加的变量（如 structured_output） */
  extraVars: { type: Array, default: () => [] },
})

const TYPE_LABELS = {
  string: 'String',
  number: 'Number',
  boolean: 'Boolean',
  object: 'Object',
  array: 'Array',
  file: 'File',
  arrayFile: 'Array[File]',
  arrayObject: 'Array[Object]',
}

function typeLabel(t) {
  return TYPE_LABELS[t] || t || 'String'
}

const resolvedVars = computed(() => {
  if (props.vars) return [...props.vars, ...props.extraVars]
  const fakeNode = { data: { type: props.nodeType || props.nodeData?.type, ...props.nodeData } }
  return [...getNodeOutputVars(fakeNode), ...props.extraVars]
})
</script>

<style scoped>
.output-var-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.var-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f9fafb;
  border: 1px solid #f2f4f7;
  padding: 6px 10px;
  border-radius: 6px;
}
.var-name {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  font-weight: 600;
  color: #155eef;
}
.var-type {
  font-size: 10px;
  color: #667085;
  background: #f2f4f7;
  padding: 1px 6px;
  border-radius: 4px;
}
.var-desc {
  font-size: 11px;
  color: #98a2b3;
  margin-left: auto;
}
.empty-tip {
  font-size: 12px;
  color: #98a2b3;
  padding: 8px 0;
}
</style>
