<!-- src/views/copilot/components/workflow/node/variable-aggregator/VariableAggregatorNode.vue -->
<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div class="vag-node-content">
      <span class="label">AGGREGATE</span>
      <div v-if="variables && variables.length" class="var-chips">
        <span v-for="(v, idx) in variables" :key="idx" class="v-chip font-mono">
          {{ Array.isArray(v) ? v.join('.') : v }}
        </span>
      </div>
      <div v-else class="empty-tip">No inputs</div>
    </div>
  </BaseNode>
</template>

<script setup>
import { computed } from 'vue'
import BaseNode from '../base/BaseNode.vue'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false }
})

const variables = computed(() => props.data?.variables || [])
</script>

<style scoped>
.vag-node-content { display: flex; flex-direction: column; gap: 4px; padding: 4px 0; }
.label { font-size: 10px; color: #64748b; font-weight: 600; }
.var-chips { display: flex; flex-wrap: wrap; gap: 4px; }
.v-chip { font-size: 10px; background: #faf5ff; border: 1px solid #f3e8ff; color: #7e22ce; padding: 1px 5px; border-radius: 4px; }
.empty-tip { font-size: 10px; color: #98a2b3; background: #f9fafb; border-radius: 6px; padding: 4px 6px; }
</style>
