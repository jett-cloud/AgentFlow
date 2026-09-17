<!-- src/views/copilot/components/workflow/node/loop/LoopNode.vue -->
<!--
  循环节点 (Loop Node)
  对齐 Dify React: web/app/components/workflow/nodes/loop/node.tsx
-->
<template>
  <BaseNode :id="id" :data="data" :selected="selected" :read-only="effectiveReadOnly">
    <div class="loop-inner-canvas">
      <AddBlock
        v-if="hasOnlyStartNode && !effectiveReadOnly"
        :container-id="id"
        :disabled="effectiveReadOnly"
      />
    </div>
  </BaseNode>
</template>

<script setup>
import { computed, inject } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import { useWorkflowStore } from '@/features/workflow/state/useWorkflowStore.js'
import BaseNode from '../base/BaseNode.vue'
import AddBlock from '../iteration/AddBlock.vue'
import { getLoopChildren } from './useLoopInteractions.js'
import { generateNewNode } from '../../model/dsl'
import { CUSTOM_EDGE, DEFAULT_SOURCE_HANDLE, DEFAULT_TARGET_HANDLE } from '../../model/constants.js'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})

const core = inject('workflowCore', null)
const store = useWorkflowStore()
const { getNodes, addNodes, addEdges } = useVueFlow()
const effectiveReadOnly = computed(() => props.readOnly || store.readOnly)

const startNodeId = computed(() => props.data?.start_node_id || `${props.id}start`)

const hasOnlyStartNode = computed(() => {
  return getLoopChildren(getNodes.value, props.id).length === 0
})

function handleAddChildNode(nodeType) {
  const { newNode } = generateNewNode({
    type: nodeType,
    position: { x: 160, y: 68 },
  })
  newNode.parentNode = props.id
  newNode.extent = 'parent'
  newNode.data.isInLoop = true
  newNode.data.loop_id = props.id

  core?.recordHistory?.()
  addNodes([newNode])
  addEdges([
    {
      id: `${startNodeId.value}-${DEFAULT_SOURCE_HANDLE}-${newNode.id}-${DEFAULT_TARGET_HANDLE}`,
      type: CUSTOM_EDGE,
      source: startNodeId.value,
      sourceHandle: DEFAULT_SOURCE_HANDLE,
      target: newNode.id,
      targetHandle: DEFAULT_TARGET_HANDLE,
      data: {
        sourceType: 'loop-start',
        targetType: nodeType,
        isInLoop: true,
        loop_id: props.id,
      },
    },
  ])
}
</script>

<style scoped>
.loop-inner-canvas {
  position: relative;
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  min-height: 120px;
  background-image: radial-gradient(#cbd5e1 1.2px, transparent 1.2px);
  background-size: 14px 14px;
  border-bottom-left-radius: 14px;
  border-bottom-right-radius: 14px;
}

</style>
