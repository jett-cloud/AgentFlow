<!-- src/views/copilot/components/workflow/node/human-input/HumanInputNode.vue -->
<template>
  <BaseNode :id="id" :data="data" :selected="selected" :read-only="readOnly">
    <div class="human-input-body">
      <div class="delivery-title">DELIVERY METHOD</div>
      <div class="delivery-row">
        <span v-if="deliveryMethods.includes('webapp')" class="delivery-chip">WebApp</span>
        <span v-if="deliveryMethods.includes('email')" class="delivery-chip">Email</span>
        <span v-if="!deliveryMethods?.length" class="delivery-empty">未配置渠道</span>
      </div>
      <div class="prompt-preview">{{ prompt || '请人工介入确认' }}</div>

      <div v-for="branch in targetBranches" :key="branch.id" class="branch-row">
        <span class="branch-label" :class="branch.isTimeout ? 'timeout' : branch.style">{{ branch.name }}</span>
        <NodeHandle
          :node-id="id"
          :data="data"
          type="source"
          position="right"
          :handle-id="branch.id"
          :label="branch.name"
          :read-only="readOnly"
          branch
        />
      </div>
    </div>
  </BaseNode>
</template>

<script setup>
import BaseNode from '../base/BaseNode.vue'
import NodeHandle from '../base/NodeHandle.vue'
import { useHumanInputConfig } from './useHumanInputConfig.js'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false }
})

const emit = defineEmits(['select'])

const { prompt, deliveryMethods, targetBranches } = useHumanInputConfig(props, (event, val) => {
  emit(event, val)
})

</script>

<style scoped>
.human-input-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-bottom: 2px;
}

.delivery-title {
  font-size: 10px;
  font-weight: 700;
  color: #98a2b3;
}

.delivery-row {
  display: flex;
  gap: 6px;
  margin-bottom: 2px;
}

.delivery-chip {
  font-size: 10px;
  font-weight: 600;
  color: #344054;
  border-radius: 999px;
  background: #f2f4f7;
  padding: 2px 7px;
}

.delivery-empty {
  font-size: 10px;
  color: #98a2b3;
}

.prompt-preview {
  font-size: 11px;
  color: #475467;
  background: #f9fafb;
  border-radius: 6px;
  padding: 5px 7px;
  max-height: 42px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.branch-row {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  min-height: 20px;
}

.branch-label {
  margin-right: 18px;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
}
.primary { color: #155eef; background: #eff4ff; }
.default { color: #475467; background: #f2f4f7; }
.accent { color: #6941c6; background: #f4ebff; }
.ghost { color: #344054; background: #ffffff; border: 1px solid #d0d5dd; }
.danger { color: #b42318; background: #fef3f2; }
.timeout { color: #b54708; background: #fffaeb; }

</style>
