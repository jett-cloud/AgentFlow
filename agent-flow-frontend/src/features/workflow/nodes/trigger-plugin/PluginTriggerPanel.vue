<template>
  <NodePanelShell v-bind="shellProps" block-type="trigger-plugin" @close="$emit('close')" @update:node-data="emitUpdate">
    <PanelSection label="插件 ID" required>
      <el-input
        :model-value="nodeData.plugin_id"
        name="trigger-plugin-id"
        autocomplete="off"
        placeholder="输入触发器插件 ID…"
        :disabled="readOnly"
        @input="updateField('plugin_id', $event)"
      />
    </PanelSection>
    <PanelSection label="订阅 ID" required>
      <el-input
        :model-value="nodeData.subscription_id"
        name="trigger-subscription-id"
        autocomplete="off"
        placeholder="选择或输入订阅 ID…"
        :disabled="readOnly"
        @input="updateField('subscription_id', $event)"
      />
    </PanelSection>
    <PanelSection label="触发配置">
      <el-input
        :model-value="configText"
        name="trigger-plugin-config"
        type="textarea"
        :rows="8"
        autocomplete="off"
        placeholder="输入 JSON 配置…"
        :disabled="readOnly"
        @change="updateConfig"
      />
      <span v-if="configError" class="config-error" aria-live="polite">{{ configError }}</span>
    </PanelSection>
  </NodePanelShell>
</template>

<script setup>
import { computed, ref } from 'vue'
import NodePanelShell from '../shared/NodePanelShell.vue'
import PanelSection from '../shared/PanelSection.vue'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:nodeData'])
const configError = ref('')
const shellProps = computed(() => ({ nodeId: props.nodeId, nodeData: props.nodeData, readOnly: props.readOnly }))
const configText = computed(() => JSON.stringify(props.nodeData.config || {}, null, 2))
const emitUpdate = data => emit('update:nodeData', data)
const updateField = (field, value) => emitUpdate({ ...props.nodeData, [field]: value })

function updateConfig(value) {
  try {
    const config = JSON.parse(value || '{}')
    configError.value = ''
    updateField('config', config)
  } catch {
    configError.value = '配置必须是有效的 JSON'
  }
}
</script>

<style scoped>
.config-error {
  color: var(--state-destructive-border, #f04438);
  font-size: 11px;
}
</style>
