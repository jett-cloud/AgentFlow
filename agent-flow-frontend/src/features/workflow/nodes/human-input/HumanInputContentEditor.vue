<template>
  <div class="content-editor">
    <div class="field-toolbar">
      <el-button
        v-for="field in fields"
        :key="field.output_variable_name"
        size="small"
        :type="activeField === field.output_variable_name ? 'primary' : 'default'"
        @click="selectField(field)"
      >
        {{ field.output_variable_name || '未命名字段' }}
      </el-button>
      <el-button v-if="!readOnly" size="small" @click="addField">添加字段并插入</el-button>
      <el-button size="small" link @click="expanded = !expanded">{{ expanded ? '收起字段' : '展开字段' }}</el-button>
    </div>
    <PromptVariableTextarea
      ref="editorRef"
      :model-value="modelValue"
      :node-id="nodeId"
      :rows="6"
      :read-only="readOnly"
      :placeholder="editorPlaceholder"
      @update:model-value="$emit('update:modelValue', $event)"
    />
    <HumanInputFormFields
      v-if="expanded"
      :model-value="fields"
      :node-id="nodeId"
      :read-only="readOnly"
      @update:model-value="$emit('update:fields', $event)"
      @rename-field="$emit('rename-field', $event)"
      @remove-field="$emit('remove-field', $event)"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import PromptVariableTextarea from '../shared/PromptVariableTextarea.vue'
import HumanInputFormFields from './HumanInputFormFields.vue'
import { createHumanInputField, formatHumanInputOutputToken } from './humanInputNode.js'

const props = defineProps({
  modelValue: { type: String, default: '' },
  fields: { type: Array, default: () => [] },
  nodeId: { type: String, required: true },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'update:fields', 'add-field', 'rename-field', 'remove-field'])
const editorPlaceholder = '支持 Markdown、上游变量，以及人工字段 {{#$output.name#}}'
const editorRef = ref(null)
const expanded = ref(true)
const activeField = ref('')

function selectField(field) {
  activeField.value = field.output_variable_name
  expanded.value = true
}

function addField() {
  const usedNames = new Set(props.fields.map(field => field.output_variable_name))
  let index = props.fields.length + 1
  while (usedNames.has(`field_${index}`))
    index += 1
  const name = `field_${index}`
  const next = [...props.fields, createHumanInputField('paragraph', name)]
  emit('update:fields', next)
  emit('add-field', { name })
  editorRef.value?.insertText(formatHumanInputOutputToken(name))
  activeField.value = name
  expanded.value = true
}
</script>

<style scoped>
.content-editor,
.field-toolbar { display: flex; flex-direction: column; gap: 8px; }
.field-toolbar { flex-direction: row; flex-wrap: wrap; align-items: center; }
</style>
