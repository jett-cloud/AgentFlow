<template>
  <BaseNode :id="id" :data="data" :selected="selected" :read-only="readOnly">
    <div class="agent-node-content">
      <div class="agent-roster-label">AGENT ROSTER</div>
      <div class="agent-roster-card" :class="{ 'is-missing': !bindingReady }">
        <div class="agent-avatar" aria-hidden="true">A</div>
        <div class="agent-details">
          <span class="agent-name" :title="agentName">{{ agentName }}</span>
          <span class="agent-role">{{ agentRole }}</span>
        </div>
      </div>
    </div>
  </BaseNode>
</template>

<script setup>
import { computed } from 'vue'
import BaseNode from '../base/BaseNode.vue'
import {
  hasValidAgentBinding,
  hasValidInlineAgentBinding,
  hasValidRosterAgentBinding,
} from './agentBinding.js'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})

const binding = computed(() => props.data?.agent_binding || {})
const bindingReady = computed(() => hasValidAgentBinding(binding.value))
const isInline = computed(() => hasValidInlineAgentBinding(binding.value))

const agentName = computed(() => {
  if (isInline.value)
    return props.data?.agent_name || '内联 Agent'
  if (hasValidRosterAgentBinding(binding.value))
    return props.data?.agent_name || binding.value.agent_name || binding.value.agent_id
  return '未配置 Agent'
})

const agentRole = computed(() => {
  if (isInline.value)
    return '内联配置'
  if (hasValidRosterAgentBinding(binding.value))
    return 'Roster Agent'
  return '请选择 Agent'
})
</script>

<style scoped>
.agent-node-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
}

.agent-roster-label {
  padding: 0 2px;
  color: var(--text-tertiary, #667085);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.04em;
}

.agent-roster-card {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
  padding: 4px;
  border-radius: 8px;
  background: var(--workflow-block-parma-bg, #f2f4f7);
}

.agent-roster-card.is-missing {
  box-shadow: inset 0 0 0 1px var(--state-destructive-border, #f04438);
}

.agent-avatar {
  display: flex;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #e4e7ec;
  color: #667085;
  font-size: 12px;
  font-weight: 600;
}

.agent-details {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.agent-name,
.agent-role {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-name {
  color: var(--text-secondary, #344054);
  font-size: 12px;
}

.agent-role {
  color: var(--text-tertiary, #667085);
  font-size: 10px;
}
</style>
