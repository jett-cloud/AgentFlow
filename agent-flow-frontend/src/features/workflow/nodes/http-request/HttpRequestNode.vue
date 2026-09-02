<!-- src/views/copilot/components/workflow/node/http-request/HttpRequestNode.vue -->
<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div v-if="data.url" class="http-node-content">
      <div class="http-tag-row">
        <span class="method-tag" :class="methodClass">{{ method }}</span>
        <span class="url-text" :title="data.url">{{ data.url }}</span>
      </div>
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

const method = computed(() => String(props.data?.method || 'GET').toUpperCase())
const methodClass = computed(() => {
  if (method.value === 'POST') return 'post'
  if (method.value === 'PUT') return 'put'
  if (method.value === 'DELETE') return 'delete'
  return 'get'
})
</script>

<style scoped>
.http-node-content { display: flex; flex-direction: column; gap: 4px; padding: 4px 0; }
.http-tag-row { display: flex; align-items: center; gap: 6px; }
.method-tag { font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 4px; font-family: ui-monospace, monospace; }
.method-tag.get { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }
.method-tag.post { background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }
.method-tag.put { background: #fefce8; color: #a16207; border: 1px solid #fef08a; }
.method-tag.delete { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
.url-text { font-size: 11px; color: #475569; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: ui-monospace, monospace; }
</style>
