<template>
  <form class="inputs-panel" @submit.prevent="handleSubmit">
    <div class="inputs-scroll">
      <div class="section-heading">
        <div>
          <h3>开始变量</h3>
          <p>填写工作流运行所需的输入参数</p>
        </div>
        <span v-if="startVariables.length" class="field-count">{{ startVariables.length }}</span>
      </div>

      <div v-if="startVariables.length" class="field-group">
        <label
          v-for="variable in startVariables"
          :key="variable.variable"
          class="field"
        >
          <span class="field-label">
            <span class="field-name">
              {{ variable.label || variable.variable }}
              <em v-if="variable.required">*</em>
            </span>
            <span class="field-type">{{ variableTypeLabel(variable.type) }}</span>
          </span>
          <StartVariableInput
            :variable="variable"
            :model-value="formInputs[variable.variable]"
            :disabled="isRunning"
            @update:model-value="formInputs[variable.variable] = $event"
            @uploading="handleUploading"
          />
          <span v-if="variable.label && variable.label !== variable.variable" class="field-key">
            {{ variable.variable }}
          </span>
        </label>
      </div>
      <div v-else class="field-hint">
        <span class="hint-icon" aria-hidden="true">✓</span>
        <div>
          <strong>无需输入参数</strong>
          <p>当前 Start 节点没有用户输入变量，可直接运行。</p>
        </div>
      </div>

      <label v-if="isChatflow" class="field query-field">
        <span class="field-label"><span class="field-name">调试消息 <em>*</em></span></span>
        <textarea
          v-model="formQuery"
          rows="3"
          :disabled="isRunning"
          placeholder="输入本轮用户消息"
        />
      </label>

      <p v-if="validationError" class="validation-error" role="alert">{{ validationError }}</p>
    </div>

    <div class="run-actions">
      <button type="submit" class="primary" :disabled="isRunning || isUploading">
        <svg v-if="!isRunning" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M7 5.5v9l7-4.5-7-4.5Z" />
        </svg>
        <span v-else class="spinner" aria-hidden="true" />
        {{ isRunning ? '运行中…' : '开始运行' }}
      </button>
      <button
        v-if="isRunning && canStop"
        type="button"
        class="stop"
        @click="$emit('stop')"
      >
        停止
      </button>
      <button
        v-if="isChatflow"
        type="button"
        :disabled="isRunning"
        @click="$emit('new-conversation')"
      >
        新对话
      </button>
    </div>
  </form>
</template>

<script setup>
import { reactive, ref, watch, computed } from 'vue'
import {
  buildStartVariableDefaults,
  validateRequiredStartInputs,
} from './applyWorkflowRunEvent.js'
import { getProcessedStartVariableInputs } from './startVariableUtils.js'
import StartVariableInput from './StartVariableInput.vue'

const props = defineProps({
  mode: { type: String, default: 'workflow' },
  startVariables: { type: Array, default: () => [] },
  isRunning: { type: Boolean, default: false },
  canStop: { type: Boolean, default: false },
})

const emit = defineEmits(['submit-run', 'stop', 'new-conversation'])

const formInputs = reactive({})
const formQuery = ref('')
const validationError = ref('')
const uploadingVariables = new Set()
const isUploading = ref(false)
const isChatflow = computed(() => props.mode === 'advanced-chat')

function syncFormFromVariables() {
  const defaults = buildStartVariableDefaults(props.startVariables)
  Object.keys(formInputs).forEach((key) => {
    if (!(key in defaults))
      delete formInputs[key]
  })
  Object.entries(defaults).forEach(([key, value]) => {
    if (formInputs[key] === undefined)
      formInputs[key] = value
  })
}

watch(() => props.startVariables, syncFormFromVariables, { immediate: true, deep: true })

function handleSubmit() {
  validationError.value = ''
  const missing = validateRequiredStartInputs(props.startVariables, formInputs)
  if (missing.length) {
    validationError.value = `请填写必填变量：${missing.join('、')}`
    return
  }
  if (isChatflow.value && !String(formQuery.value || '').trim()) {
    validationError.value = '请输入调试消息'
    return
  }
  if (isUploading.value) {
    validationError.value = '请等待附件上传完成'
    return
  }
  emit('submit-run', {
    inputs: getProcessedStartVariableInputs(props.startVariables, formInputs),
    query: formQuery.value,
  })
}

function handleUploading({ variable, uploading }) {
  if (uploading) uploadingVariables.add(variable)
  else uploadingVariables.delete(variable)
  isUploading.value = uploadingVariables.size > 0
}

function variableTypeLabel(type) {
  return ({
    paragraph: 'Paragraph',
    'text-input': 'Text',
    text: 'Text',
    string: 'Text',
    number: 'Number',
    select: 'Select',
    checkbox: 'Boolean',
    file: 'File',
    'file-list': 'Files',
    json_object: 'JSON',
    url: 'URL',
  })[type] || String(type || 'Text')
}

defineExpose({ syncFormFromVariables })
</script>

<style scoped>
.inputs-panel {
  display: flex;
  min-height: 100%;
  flex-direction: column;
}
.inputs-scroll {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 18px;
  padding: 18px 16px 22px;
}
.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.section-heading h3,
.section-heading p {
  margin: 0;
}
.section-heading h3 {
  color: #344054;
  font-size: 13px;
  font-weight: 650;
  line-height: 20px;
}
.section-heading p {
  margin-top: 2px;
  color: #98a2b3;
  font-size: 11px;
  line-height: 16px;
}
.field-count {
  display: grid;
  min-width: 22px;
  height: 22px;
  place-items: center;
  padding: 0 7px;
  border-radius: 999px;
  background: #f2f4f7;
  color: #667085;
  font-size: 11px;
  font-weight: 600;
}
.field-group {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 12px;
  color: #354052;
}
.field-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.field-name {
  min-width: 0;
  overflow: hidden;
  color: #344054;
  font-size: 12px;
  font-weight: 550;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.field em {
  margin-left: 2px;
  color: #f04438;
  font-style: normal;
}
.field-type {
  flex: 0 0 auto;
  color: #98a2b3;
  font-size: 10px;
  font-weight: 500;
}
.field-key {
  color: #98a2b3;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
  line-height: 14px;
}
.field input,
.field select,
.field textarea {
  width: 100%;
  box-sizing: border-box;
  min-height: 38px;
  padding: 9px 10px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  outline: none;
  background: #fff;
  color: #101828;
  font: inherit;
  line-height: 18px;
  box-shadow: 0 1px 2px rgb(16 24 40 / 4%);
  transition: border-color 150ms ease, box-shadow 150ms ease;
}
.field textarea {
  min-height: 80px;
  resize: vertical;
}
.field input::placeholder,
.field textarea::placeholder {
  color: #98a2b3;
}
.field input:hover:not(:disabled),
.field select:hover:not(:disabled),
.field textarea:hover:not(:disabled) {
  border-color: #98a2b3;
}
.field input:focus,
.field select:focus,
.field textarea:focus {
  border-color: #528bff;
  box-shadow: 0 0 0 3px rgb(21 94 239 / 10%), 0 1px 2px rgb(16 24 40 / 4%);
}
.field input:disabled,
.field select:disabled,
.field textarea:disabled {
  background: #f9fafb;
  color: #667085;
  cursor: not-allowed;
}
.field-hint {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px;
  border: 1px solid #eaecf0;
  border-radius: 10px;
  background: #f9fafb;
}
.hint-icon {
  display: grid;
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 50%;
  background: #dcfae6;
  color: #079455;
  font-size: 12px;
  font-weight: 700;
}
.field-hint strong {
  color: #344054;
  font-size: 12px;
}
.field-hint p {
  margin: 2px 0 0;
  color: #667085;
  font-size: 11px;
  line-height: 16px;
}
.query-field {
  padding-top: 2px;
}
.validation-error {
  margin: 0;
  padding: 9px 10px;
  border: 1px solid #fecdca;
  border-radius: 8px;
  background: #fef3f2;
  color: #b42318;
  font-size: 11px;
  line-height: 16px;
}
.run-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 16px 16px;
  border-top: 1px solid #f2f4f7;
  background: rgb(255 255 255 / 94%);
  box-shadow: 0 -8px 20px rgb(16 24 40 / 3%);
  backdrop-filter: blur(8px);
}
.run-actions button {
  display: inline-flex;
  min-height: 38px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #f2f4f7;
  color: #344054;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 1px 2px rgb(16 24 40 / 5%);
  transition: background 150ms ease, border-color 150ms ease, box-shadow 150ms ease;
}
.run-actions .primary {
  min-width: 100%;
  border-color: #155eef;
  background: #155eef;
  color: #fff;
  box-shadow: 0 1px 2px rgb(16 24 40 / 8%), inset 0 0 0 1px rgb(255 255 255 / 10%);
}
.run-actions .primary:hover:not(:disabled) {
  border-color: #004eeb;
  background: #004eeb;
}
.run-actions .primary svg {
  width: 16px;
  height: 16px;
  fill: currentColor;
}
.run-actions .primary:disabled {
  border-color: #b2ccff;
  background: #b2ccff;
  box-shadow: none;
  cursor: not-allowed;
}
.run-actions .stop {
  border: 1px solid #fda29b;
  background: #fff;
  color: #b42318;
}
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgb(255 255 255 / 45%);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 700ms linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
