<template>
  <g>
    <path class="connection-path" fill="none" :d="path[0]" />
    <rect
      class="connection-target"
      :x="targetX"
      :y="targetY - 4"
      width="2"
      height="8"
      rx="1"
    />
  </g>
</template>

<script setup>
import { computed } from 'vue'
import { getBezierPath } from '@vue-flow/core'

const props = defineProps({
  sourceX: { type: Number, required: true },
  sourceY: { type: Number, required: true },
  targetX: { type: Number, required: true },
  targetY: { type: Number, required: true },
  sourcePosition: { type: String, default: 'right' },
  targetPosition: { type: String, default: 'left' },
})

const path = computed(() => getBezierPath({
  sourceX: props.sourceX,
  sourceY: props.sourceY,
  sourcePosition: props.sourcePosition,
  targetX: props.targetX,
  targetY: props.targetY,
  targetPosition: props.targetPosition,
  curvature: 0.16,
}))
</script>

<style scoped>
.connection-path {
  stroke: var(--workflow-link-line-normal, #d0d5dc);
  stroke-width: 2;
}

.connection-target {
  fill: var(--workflow-link-line-active, #085afc);
}
</style>
