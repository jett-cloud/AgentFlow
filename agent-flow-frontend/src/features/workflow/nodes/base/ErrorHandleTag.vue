<template>
  <div v-if="label" class="error-handle-tag nodrag">
    <span class="error-handle-dot"></span>
    <span>{{ label }}</span>
    <NodeHandle
      v-if="isFailureBranch"
      :node-id="nodeId"
      :data="data"
      type="source"
      position="right"
      handle-id="fail-branch"
      label="失败"
      :read-only="readOnly"
      branch
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import NodeHandle from './NodeHandle.vue'

const props = defineProps({
  nodeId: { type: String, required: true },
  data: { type: Object, required: true },
  strategy: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
})

const labels = {
  'default-value': '默认值',
  defaultValue: '默认值',
  'fail-branch': '异常分支',
  failBranch: '异常分支',
  'continue-on-error': '忽略异常',
  continue_on_error: '忽略异常',
}

const label = computed(() => labels[props.strategy] || '')
const isFailureBranch = computed(() => (
  props.strategy === 'fail-branch' || props.strategy === 'failBranch'
))
</script>

<style scoped>
.error-handle-tag {
  position: relative;
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 0 12px 8px;
  padding: 5px 8px;
  border: 1px solid var(--state-warning-border-subtle, #fedf89);
  border-radius: 8px;
  background: var(--state-warning-bg, #fffaeb);
  color: var(--state-warning-text, #b54708);
  font-size: 11px;
  font-weight: 500;
}

.error-handle-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--state-warning-border, #f79009);
}
</style>
