<template>
  <div class="field-editor">
    <div v-if="!modelValue.length" class="empty-tip">尚未添加需要人工填写的字段</div>
    <div v-for="(field, index) in modelValue" :key="field.output_variable_name || index" class="field-card">
      <div class="field-row">
        <div class="name-field">
          <el-input
            :model-value="fieldNameDisplay(field, index)"
            placeholder="输出变量名"
            :disabled="readOnly"
            @update:model-value="commitFieldName(index, $event)"
          />
          <span v-if="fieldNameError(field, index)" class="field-error">{{ fieldNameError(field, index) }}</span>
        </div>
        <el-select
          :model-value="field.type"
          :disabled="readOnly"
          @change="changeFieldType(index, $event)"
        >
          <el-option v-for="type in FORM_INPUT_TYPES" :key="type.value" :label="type.label" :value="type.value" />
        </el-select>
        <el-button v-if="!readOnly" link @click="removeField(index)">删除</el-button>
      </div>

      <template v-if="field.type === 'paragraph'">
        <div class="field-row compact">
          <span class="field-label">默认值来源</span>
          <el-radio-group
            :model-value="field.default?.type"
            :disabled="readOnly"
            @change="changeSourceType(index, 'default', $event)"
          >
            <el-radio-button value="constant">固定值</el-radio-button>
            <el-radio-button value="variable">变量</el-radio-button>
          </el-radio-group>
        </div>
        <VarReferencePicker
          v-if="field.default?.type === 'variable'"
          :model-value="field.default.selector"
          :node-id="nodeId"
          :read-only="readOnly"
          @update:model-value="updateSource(index, 'default', { selector: $event })"
        />
        <el-input
          v-else
          :model-value="field.default?.value"
          type="textarea"
          :rows="2"
          placeholder="默认文本（可留空）"
          :disabled="readOnly"
          @update:model-value="updateSource(index, 'default', { value: $event })"
        />
      </template>

      <template v-if="field.type === 'select'">
        <div class="field-row compact">
          <span class="field-label">选项来源</span>
          <el-radio-group
            :model-value="field.option_source?.type"
            :disabled="readOnly"
            @change="changeSourceType(index, 'option_source', $event)"
          >
            <el-radio-button value="constant">固定选项</el-radio-button>
            <el-radio-button value="variable">变量</el-radio-button>
          </el-radio-group>
        </div>
        <VarReferencePicker
          v-if="field.option_source?.type === 'variable'"
          :model-value="field.option_source.selector"
          :node-id="nodeId"
          :read-only="readOnly"
          :filter-var="isStringArrayVariable"
          @update:model-value="updateSource(index, 'option_source', { selector: $event })"
        />
        <el-input
          v-else
          :model-value="constantOptions(field)"
          type="textarea"
          :rows="3"
          placeholder="每行一个选项"
          :disabled="readOnly"
          @update:model-value="updateConstantOptions(index, $event)"
        />
      </template>

      <template v-if="field.type === 'file' || field.type === 'file-list'">
        <div class="field-group">
          <span class="field-label">允许的文件类型</span>
          <el-checkbox-group
            :model-value="field.allowed_file_types"
            :disabled="readOnly"
            @update:model-value="updateField(index, { allowed_file_types: $event })"
          >
            <el-checkbox v-for="type in FILE_TYPE_OPTIONS" :key="type.value" :value="type.value">{{ type.label }}</el-checkbox>
          </el-checkbox-group>
        </div>
        <el-input
          v-if="field.allowed_file_types?.includes('custom')"
          :model-value="field.allowed_file_extensions.join(', ')"
          placeholder="扩展名，例如 .csv, .md"
          :disabled="readOnly"
          @update:model-value="updateExtensions(index, $event)"
        />
        <div class="field-group">
          <span class="field-label">上传方式</span>
          <el-checkbox-group
            :model-value="field.allowed_file_upload_methods"
            :disabled="readOnly"
            @update:model-value="updateField(index, { allowed_file_upload_methods: $event })"
          >
            <el-checkbox value="local_file">本地上传</el-checkbox>
            <el-checkbox value="remote_url">远程链接</el-checkbox>
          </el-checkbox-group>
        </div>
        <div v-if="field.type === 'file-list'" class="field-row compact">
          <span class="field-label">最大文件数</span>
          <el-input-number
            :model-value="field.number_limits"
            :min="0"
            :step="1"
            step-strictly
            :disabled="readOnly"
            @update:model-value="updateField(index, { number_limits: $event })"
          />
        </div>
      </template>
    </div>
    <el-button v-if="!readOnly" class="add-field" @click="addField">添加字段</el-button>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import {
  applyHumanInputFieldNameInput,
  createHumanInputField,
  humanInputDraftKey,
  humanInputFieldNameErrorMessage,
  pruneHumanInputDrafts,
} from './humanInputNode.js'
import { FORM_INPUT_TYPES } from './useHumanInputConfig.js'

const FILE_TYPE_OPTIONS = [
  { value: 'image', label: '图片' },
  { value: 'document', label: '文档' },
  { value: 'audio', label: '音频' },
  { value: 'video', label: '视频' },
  { value: 'custom', label: '自定义' },
]

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  nodeId: { type: String, required: true },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'rename-field', 'remove-field'])
const nameDrafts = ref({})

function fieldDraftKey(field, index) {
  return humanInputDraftKey(field?.output_variable_name, index)
}

function fieldNameDisplay(field, index) {
  return nameDrafts.value[fieldDraftKey(field, index)] ?? field.output_variable_name
}

function fieldNameError(field, index) {
  const stored = field?.output_variable_name || ''
  const raw = nameDrafts.value[fieldDraftKey(field, index)] ?? stored
  const others = props.modelValue
    .map(item => item.output_variable_name)
    .filter((_, current) => current !== index)
  return humanInputFieldNameErrorMessage(applyHumanInputFieldNameInput(raw, others, stored).error)
}

function replaceField(index, nextField) {
  emit('update:modelValue', props.modelValue.map((field, current) => current === index ? nextField : field))
}

function updateField(index, partial) {
  replaceField(index, { ...props.modelValue[index], ...partial })
}

function changeFieldType(index, type) {
  replaceField(index, createHumanInputField(type, props.modelValue[index]?.output_variable_name))
}

function changeSourceType(index, key, type) {
  updateField(index, {
    [key]: { type, selector: [], value: type === 'constant' && key === 'option_source' ? [] : '' },
  })
}

function updateSource(index, key, partial) {
  updateField(index, { [key]: { ...props.modelValue[index]?.[key], ...partial } })
}

function constantOptions(field) {
  return Array.isArray(field.option_source?.value) ? field.option_source.value.join('\n') : ''
}

function updateConstantOptions(index, value) {
  const options = String(value).split(/\r?\n/).map(item => item.trim()).filter(Boolean)
  updateSource(index, 'option_source', { value: options })
}

function updateExtensions(index, value) {
  const extensions = String(value).split(/[\s,;]+/).map(item => item.trim()).filter(Boolean)
  updateField(index, { allowed_file_extensions: [...new Set(extensions)] })
}

function isStringArrayVariable(variable) {
  return ['arrayString', 'array[string]'].includes(variable?.type)
}

function commitFieldName(index, raw) {
  const stored = props.modelValue[index]?.output_variable_name || ''
  const others = props.modelValue
    .map(item => item.output_variable_name)
    .filter((_, current) => current !== index)
  const result = applyHumanInputFieldNameInput(raw, others, stored)
  const key = fieldDraftKey(props.modelValue[index], index)
  if (result.error) {
    nameDrafts.value = { ...nameDrafts.value, [key]: result.display }
    return
  }
  const next = { ...nameDrafts.value }
  delete next[key]
  nameDrafts.value = next
  if (stored === result.value)
    return
  updateField(index, { output_variable_name: result.value })
  emit('rename-field', { oldName: stored, newName: result.value })
}

function addField() {
  const usedNames = new Set(props.modelValue.map(field => field.output_variable_name))
  let index = props.modelValue.length + 1
  while (usedNames.has(`field_${index}`))
    index += 1
  emit('update:modelValue', [...props.modelValue, createHumanInputField('paragraph', `field_${index}`)])
}

function removeField(index) {
  const name = props.modelValue[index]?.output_variable_name
  const remaining = props.modelValue
    .filter((_, current) => current !== index)
    .map((field, current) => fieldDraftKey(field, current))
  nameDrafts.value = pruneHumanInputDrafts(nameDrafts.value, remaining)
  emit('update:modelValue', props.modelValue.filter((_, current) => current !== index))
  emit('remove-field', { name, oldName: name })
}
</script>

<style scoped>
.field-editor,
.field-card,
.field-group { display: flex; flex-direction: column; gap: 8px; }
.field-card { padding: 10px; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; }
.field-row { display: grid; grid-template-columns: minmax(0, 1fr) 140px auto; gap: 8px; align-items: start; }
.field-row.compact { grid-template-columns: minmax(90px, auto) 1fr; align-items: center; }
.name-field { display: flex; min-width: 0; flex-direction: column; gap: 3px; }
.field-error { color: #d92d20; font-size: 10px; line-height: 1.2; }
.field-label { font-size: 11px; font-weight: 600; color: #475569; }
.empty-tip { padding: 8px; border: 1px dashed #d0d5dd; border-radius: 6px; color: #98a2b3; font-size: 11px; text-align: center; }
.add-field { width: 100%; }
</style>
