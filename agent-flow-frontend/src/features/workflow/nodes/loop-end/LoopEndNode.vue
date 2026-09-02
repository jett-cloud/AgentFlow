<template>
  <BaseNode
    :id="id"
    :data="data"
    :selected="selected"
    :read-only="readOnly"
  />
</template>

<script setup>
import BaseNode from '../base/BaseNode.vue'

defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})
</script>
