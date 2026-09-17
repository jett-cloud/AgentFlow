<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div class="placeholder-body">
      {{ hint }}
    </div>
  </BaseNode>
</template>

<script setup>
import { computed } from 'vue'
import BaseNode from '../base/BaseNode.vue'
import { getStartPlaceholderHint } from './startPlaceholderNode.js'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const hint = computed(() => getStartPlaceholderHint(props.selected))
</script>

<style scoped>
.placeholder-body {
  padding: 5px 6px;
  border-radius: 6px;
  background: var(--workflow-block-parma-bg, #f2f4f7);
  color: #667085;
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
</style>
