<template>
  <NodePanelShell v-bind="shellProps" block-type="trigger-webhook" @close="$emit('close')" @update:node-data="emitUpdate">
    <PanelSection label="Webhook URL">
      <el-input
        :model-value="nodeData.webhook_url || nodeData.url || ''"
        name="webhook-url"
        autocomplete="off"
        placeholder="发布后由 Dify 生成；也可粘贴已有 URL"
        :disabled="readOnly"
        @input="updateField('webhook_url', $event)"
      />
    </PanelSection>

    <PanelSection label="HTTP 方法">
      <el-select
        :model-value="nodeData.method || 'POST'"
        :disabled="readOnly"
        @change="updateField('method', $event)"
      >
        <el-option v-for="method in httpMethods" :key="method" :label="method" :value="method" />
      </el-select>
    </PanelSection>

    <PanelSection label="内容类型">
      <el-select
        :model-value="nodeData.content_type || 'application/json'"
        :disabled="readOnly"
        @change="updateField('content_type', $event)"
      >
        <el-option v-for="type in contentTypes" :key="type" :label="type" :value="type" />
      </el-select>
    </PanelSection>

    <PanelSection label="成功状态码">
      <el-input-number
        :model-value="Number(nodeData.status_code || 200)"
        :min="100"
        :max="599"
        :disabled="readOnly"
        @change="updateField('status_code', $event)"
      />
    </PanelSection>

    <PanelSection label="请求头（每行 Key: Value）">
      <el-input
        :model-value="headersText"
        type="textarea"
        :rows="3"
        :disabled="readOnly"
        placeholder="Authorization: Bearer …&#10;X-Custom: value"
        @input="updateHeaders"
      />
    </PanelSection>

    <PanelSection label="请求字段（每行 name:type）">
      <el-input
        :model-value="parametersText"
        type="textarea"
        :rows="4"
        :disabled="readOnly"
        placeholder="query:string&#10;payload:object"
        @input="updateParameters"
      />
    </PanelSection>
  </NodePanelShell>
</template>

<script setup>
import { computed } from 'vue'
import NodePanelShell from '../shared/NodePanelShell.vue'
import PanelSection from '../shared/PanelSection.vue'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:nodeData'])
const httpMethods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD']
const contentTypes = [
  'application/json',
  'application/x-www-form-urlencoded',
  'text/plain',
  'application/octet-stream',
  'multipart/form-data',
]
const shellProps = computed(() => ({ nodeId: props.nodeId, nodeData: props.nodeData, readOnly: props.readOnly }))
const parametersText = computed(() => (props.nodeData.parameters || [])
  .map(parameter => `${parameter.name}:${parameter.type || 'string'}`)
  .join('\n'))
const headersText = computed(() => (props.nodeData.headers || [])
  .map(header => `${header.key || header.name || ''}: ${header.value || ''}`)
  .filter(line => line.trim() !== ':')
  .join('\n'))
const emitUpdate = data => emit('update:nodeData', data)
const updateField = (field, value) => emitUpdate({ ...props.nodeData, [field]: value })
function updateParameters(value) {
  const parameters = String(value || '')
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, type = 'string'] = line.split(':')
      return { name: name.trim(), type: type.trim() || 'string' }
    })
    .filter(item => item.name)
  updateField('parameters', parameters)
}
function updateHeaders(value) {
  const headers = String(value || '')
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.indexOf(':')
      if (idx < 0)
        return { key: line.trim(), value: '' }
      return {
        key: line.slice(0, idx).trim(),
        value: line.slice(idx + 1).trim(),
      }
    })
    .filter(item => item.key)
  updateField('headers', headers)
}
</script>
