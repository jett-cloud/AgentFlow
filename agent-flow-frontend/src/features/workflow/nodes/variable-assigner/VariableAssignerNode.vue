<!-- src/views/copilot/components/workflow/node/variable-assigner/VariableAssignerNode.vue -->
<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div class="va-node-content">
      <div class="label">ASSIGN</div>
      <div v-for="(item, index) in items" :key="`${formatTarget(item)}:${index}`" class="va-row">
        <span class="var-name">{{ formatTarget(item) }}</span>
        <span class="op">←</span>
        <span class="var-val">{{ formatSource(item) }}</span>
      </div>
    </div>
  </BaseNode>
</template>

<script setup>
import { computed } from 'vue'
import BaseNode from '../base/BaseNode.vue'
import { formatValueSelector } from '../../model/variableOutputs.js'
import { getAssignmentSourceSelector, getAssignmentTargetSelector } from './variableAssigner.js'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false }
})

const items = computed(() => props.data?.items || [])
const formatTarget = item => formatValueSelector(getAssignmentTargetSelector(item))
const formatSource = item => formatValueSelector(getAssignmentSourceSelector(item))
</script>

<style scoped>
.va-node-content { display: flex; flex-direction: column; gap: 4px; padding: 4px 0; }
.label { font-size: 10px; color: #98a2b3; font-weight: 700; }
.va-row { display: flex; align-items: center; gap: 4px; font-size: 10px; background: #f8fafc; border: 1px solid #f1f5f9; padding: 2px 6px; border-radius: 4px; }
.var-name { font-weight: 600; color: #0284c7; font-family: ui-monospace, monospace; }
.op { color: #94a3b8; }
.var-val { color: #334155; font-family: ui-monospace, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
