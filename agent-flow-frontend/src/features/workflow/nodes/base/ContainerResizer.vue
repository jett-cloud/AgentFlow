<template>
  <button
    ref="handleRef"
    type="button"
    class="container-resizer nodrag"
    aria-label="调整容器大小"
    @pointerdown="startResize"
    @keydown="handleKeydown"
  />
</template>

<script setup>
import { inject, nextTick, onUnmounted, ref } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import {
  CONTAINER_MIN_HEIGHT,
  CONTAINER_MIN_WIDTH,
  getContainerFitSize,
} from '../../model/containerLayout.js'

const MIN_WIDTH = CONTAINER_MIN_WIDTH
const MIN_HEIGHT = CONTAINER_MIN_HEIGHT
const KEYBOARD_STEP = 16

const props = defineProps({
  nodeId: { type: String, required: true },
})

const core = inject('workflowCore', null)
const handleRef = ref(null)
const { getNodes, getViewport, updateNodeDimensions } = useVueFlow()
let resizeState = null

function findNode() {
  return getNodes.value.find(node => node.id === props.nodeId)
}

function currentSize(node) {
  return {
    width: Number.parseFloat(node?.style?.width) || node?.dimensions?.width || node?.width || MIN_WIDTH,
    height: Number.parseFloat(node?.style?.height) || node?.dimensions?.height || node?.height || MIN_HEIGHT,
  }
}

async function applySize(width, height) {
  const node = findNode()
  if (!node)
    return
  const minimum = getContainerFitSize({
    currentWidth: MIN_WIDTH,
    currentHeight: MIN_HEIGHT,
    children: getNodes.value.filter(child => (child.parentNode || child.parentId) === props.nodeId),
  })
  node.style = {
    ...node.style,
    width: `${Math.max(minimum.width, Math.round(width))}px`,
    height: `${Math.max(minimum.height, Math.round(height))}px`,
  }
  await nextTick()
  const nodeElement = handleRef.value?.closest?.('.vue-flow__node')
  if (nodeElement)
    updateNodeDimensions([{ id: props.nodeId, nodeElement, forceUpdate: true }])
}

function startResize(event) {
  const node = findNode()
  if (!node)
    return
  const size = currentSize(node)
  core?.recordHistory?.()
  resizeState = {
    x: event.clientX,
    y: event.clientY,
    width: size.width,
    height: size.height,
  }
  event.currentTarget?.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', stopResize, { once: true })
}

function handlePointerMove(event) {
  if (!resizeState)
    return
  const zoom = getViewport?.().zoom || 1
  applySize(
    resizeState.width + (event.clientX - resizeState.x) / zoom,
    resizeState.height + (event.clientY - resizeState.y) / zoom,
  )
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
  const node = findNode()
  const size = currentSize(node)
  core?.recordHistory?.()
  applySize(size.width + delta[0], size.height + delta[1])
}

onUnmounted(stopResize)
</script>

<style scoped>
.container-resizer {
  position: absolute;
  right: -1px;
  bottom: -1px;
  z-index: 25;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: 0 0 14px;
  background:
    linear-gradient(135deg, transparent 45%, var(--text-tertiary, #667085) 46%, var(--text-tertiary, #667085) 54%, transparent 55%) 7px 7px / 7px 7px no-repeat;
  cursor: nwse-resize;
}

.container-resizer:focus-visible {
  outline: 2px solid var(--state-accent-border, #155eef);
  outline-offset: 2px;
}
</style>
