<template>
  <button
    ref="handleRef"
    type="button"
    class="note-resizer nodrag"
    aria-label="调整便签大小"
    @pointerdown="startResize"
    @keydown="handleKeydown"
  />
</template>

<script setup>
import { inject, nextTick, onUnmounted, ref } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import { getResizedNoteSize } from './noteNode.js'

const KEYBOARD_STEP = 16

const props = defineProps({
  nodeId: { type: String, required: true },
  data: { type: Object, required: true },
})

const core = inject('workflowCore', null)
const handleRef = ref(null)
const { getViewport, updateNodeDimensions } = useVueFlow()
let resizeState = null

async function applySize(deltaX, deltaY) {
  if (!resizeState)
    return
  const size = getResizedNoteSize({
    width: resizeState.width,
    height: resizeState.height,
    deltaX,
    deltaY,
    zoom: getViewport?.().zoom || 1,
  })
  core?.updateNodeData?.(props.nodeId, size, { record: false })
  await nextTick()
  const nodeElement = handleRef.value?.closest?.('.vue-flow__node')
  if (nodeElement)
    updateNodeDimensions([{ id: props.nodeId, nodeElement, forceUpdate: true }])
}

function startResize(event) {
  core?.recordHistory?.()
  resizeState = {
    x: event.clientX,
    y: event.clientY,
    width: props.data.width,
    height: props.data.height,
  }
  event.currentTarget?.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', stopResize, { once: true })
}

function handlePointerMove(event) {
  if (!resizeState)
    return
  applySize(event.clientX - resizeState.x, event.clientY - resizeState.y)
}

function stopResize() {
  resizeState = null
  window.removeEventListener('pointermove', handlePointerMove)
}

function handleKeydown(event) {
  const directions = {
    ArrowRight: [KEYBOARD_STEP, 0],
    ArrowLeft: [-KEYBOARD_STEP, 0],
    ArrowDown: [0, KEYBOARD_STEP],
    ArrowUp: [0, -KEYBOARD_STEP],
  }
  const delta = directions[event.key]
  if (!delta)
    return
  event.preventDefault()
  core?.recordHistory?.()
  resizeState = {
    x: 0,
    y: 0,
    width: props.data.width,
    height: props.data.height,
  }
  applySize(delta[0], delta[1]).finally(() => {
    resizeState = null
  })
}

onUnmounted(stopResize)
</script>

<style scoped>
.note-resizer {
  position: absolute;
  right: -1px;
  bottom: -1px;
  z-index: 3;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: 0 0 5px;
  background:
    linear-gradient(135deg, transparent 45%, rgba(0, 0, 0, 0.28) 46%, rgba(0, 0, 0, 0.28) 54%, transparent 55%) 7px 7px / 7px 7px no-repeat;
  cursor: nwse-resize;
}

.note-resizer:focus-visible {
  outline: 2px solid var(--state-accent-border, #155eef);
  outline-offset: 2px;
}
</style>
