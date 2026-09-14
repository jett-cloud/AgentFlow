<template>
  <el-select
    v-if="isBoolean"
    :model-value="condition.value"
    class="condition-value"
    :disabled="readOnly"
    @change="$emit('update:value', $event)"
  >
    <el-option label="True" :value="true" />
    <el-option label="False" :value="false" />
  </el-select>
  <el-select
    v-else-if="isStringList"
    :model-value="normalizedList"
    class="condition-value"
    multiple
    filterable
    allow-create
    default-first-option
    :disabled="readOnly"
    @change="$emit('update:value', $event)"
  />
  <el-input
    v-else
    :model-value="condition.value"
    class="condition-value"
    placeholder="比较目标值"
    :disabled="readOnly"
    @input="$emit('update:value', $event)"
  />
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  condition: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})

defineEmits(['update:value'])

const isBoolean = computed(() => ['boolean', 'arrayBoolean'].includes(props.condition.varType))
const isStringList = computed(() => ['in', 'not in'].includes(props.condition.comparison_operator))
const normalizedList = computed(() => Array.isArray(props.condition.value) ? props.condition.value : [])
</script>

<style scoped>
.condition-value {
  flex: 1;
  min-width: 0;
}
</style>
