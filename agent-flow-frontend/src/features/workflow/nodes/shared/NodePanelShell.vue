<template>
  <div class="node-panel-shell">
    <PanelHeader
      :block-type="blockType"
      :title="nodeData.title"
      :description="nodeData.desc"
      :legacy-description="nodeData.description"
      :read-only="readOnly"
      @update:title="updateTitle"
      @update:description="updateDescription"
      @close="$emit('close')"
    />
    <div class="node-panel-body">
      <slot />
      <NextStep :node-id="nodeId" :node-data="nodeData" :read-only="readOnly" />
    </div>
  </div>
</template>

<script setup>
import PanelHeader from './PanelHeader.vue'
import NextStep from './NextStep.vue'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  blockType: { type: String, required: true },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'update:nodeData'])

function updateTitle(title) {
  emit('update:nodeData', { ...props.nodeData, title })
}

function updateDescription(description) {
  const { description: _legacyDescription, ...nodeData } = props.nodeData
  emit('update:nodeData', { ...nodeData, desc: description })
}
</script>

<style scoped>
.node-panel-shell {
  display: flex;
  height: 100%;
  flex-direction: column;
  overflow: hidden;
  background: var(--components-panel-bg, #fff);
}

.node-panel-body {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 16px 20px 24px;
}
</style>
