<!-- src/views/copilot/components/workflow/node/list-operator/ListOperatorNode.vue -->
<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div class="lo-node-content">
      <span class="label">LIST</span>
      <span class="val font-mono">{{ formatSelector(data.variable) }}</span>
    </div>
  </BaseNode>
</template>

<script setup>
import BaseNode from '../base/BaseNode.vue'

defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false }
})

const formatSelector = (sel) => {
  if (!Array.isArray(sel) || !sel.length) return '未选择数组'
  if (Array.isArray(sel)) return sel.join('.')
  return String(sel)
}
</script>

<style scoped>
.lo-node-content { display: flex; flex-direction: column; gap: 4px; padding: 4px 0; }
.label { font-size: 10px; color: #64748b; font-weight: 600; }
.val { font-size: 11px; color: #0d9488; background: #f0fdfa; border: 1px solid #ccfbf1; padding: 2px 6px; border-radius: 4px; }
</style>
