<template>
  <div class="credential-schema-fields">
    <div
      v-for="field in visibleFields"
      :key="field.variable"
      class="field"
    >
      <span class="field-label">
        {{ field.label }}{{ field.required ? ' *' : '' }}
      </span>

      <el-radio-group
        v-if="field.type === 'radio'"
        :model-value="String(modelValue[field.variable] ?? '')"
        :disabled="disabled"
        class="radio-group"
        @update:model-value="(val) => patch(field.variable, val)"
      >
        <el-radio
          v-for="option in visibleOptions(field)"
          :key="option.value"
          :value="option.value"
          :label="option.value"
        >
          {{ option.label }}
        </el-radio>
      </el-radio-group>

      <el-select
        v-else-if="field.type === 'select'"
        :model-value="String(modelValue[field.variable] ?? '')"
        clearable
        filterable
        class="w-full"
        :placeholder="field.placeholder || '请选择'"
        :disabled="disabled"
        @update:model-value="(val) => patch(field.variable, val)"
      >
        <el-option
          v-for="option in visibleOptions(field)"
          :key="option.value"
          :label="option.label"
          :value="option.value"
        />
      </el-select>

      <el-switch
        v-else-if="field.type === 'checkbox' || field.type === 'boolean'"
        :model-value="Boolean(modelValue[field.variable])"
        :disabled="disabled"
        @update:model-value="(val) => patch(field.variable, val)"
      />

      <input
        v-else
        :value="modelValue[field.variable] ?? ''"
        :type="inputType(field)"
        :placeholder="field.placeholder || field.variable"
        :disabled="disabled"
        :min="field.min"
        :max="field.max"
        autocomplete="off"
        @input="patch(field.variable, $event.target.value)"
      >
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  getVisibleCredentialFields,
  getVisibleOptions,
} from '../lib/credentialFormHelpers.js'

const props = defineProps({
  fields: { type: Array, default: () => [] },
  modelValue: { type: Object, default: () => ({}) },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const visibleFields = computed(() => getVisibleCredentialFields(props.fields, props.modelValue))

function visibleOptions(field) {
  return getVisibleOptions(field, props.modelValue)
}

function inputType(field) {
  if (field.type === 'secret-input' || field.secret)
    return 'password'
  if (field.type === 'number-input')
    return 'number'
  return 'text'
}

function patch(variable, value) {
  emit('update:modelValue', {
    ...props.modelValue,
    [variable]: value,
  })
}
</script>

<style scoped>
.credential-schema-fields { display: flex; flex-direction: column; gap: 0; }
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
  font-size: 12px;
  color: #344054;
}
.field-label { font-weight: 500; }
.field input {
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
}
.w-full { width: 100%; }
.radio-group { display: flex; flex-wrap: wrap; gap: 8px 16px; }
</style>
