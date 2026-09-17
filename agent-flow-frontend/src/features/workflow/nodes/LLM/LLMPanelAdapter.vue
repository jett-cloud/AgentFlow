<!-- src/views/copilot/components/workflow/node/LLM/LLMPanel.vue -->
<template>
  <LLMPanel v-bind="$props" @close="$emit('close')" @update:nodeData="$emit('update:nodeData', $event)" />
</template>

<script setup>
import LLMPanel from './LLMPanel.vue'

defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
  appMode: { type: String, default: 'chat' }
})

defineEmits(['close', 'update:nodeData'])
</script>
