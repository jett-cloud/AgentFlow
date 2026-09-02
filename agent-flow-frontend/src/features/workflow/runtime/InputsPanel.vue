<template>
  <form class="inputs-panel" @submit.prevent="handleSubmit">
    <div v-if="startVariables.length" class="field-group">
      <h3>开始变量</h3>
      <label
        v-for="variable in startVariables"
        :key="variable.variable"
        class="field"
      >
        <span>
          {{ variable.label || variable.variable }}
          <em v-if="variable.required">*</em>
        </span>
        <StartVariableInput
          :variable="variable"
          :model-value="formInputs[variable.variable]"
          :disabled="isRunning"
          @update:model-value="formInputs[variable.variable] = $event"
          @uploading="handleUploading"
        />
      </label>
    </div>
    <div v-else class="field-hint">当前 Start 节点没有用户输入变量，可直接运行。</div>

    <label v-if="isChatflow" class="field">
      <span>调试消息 <em>*</em></span>
      <textarea
        v-model="formQuery"
        rows="3"
        :disabled="isRunning"
        placeholder="输入本轮用户消息"
      />
    </label>

    <p v-if="validationError" class="validation-error" role="alert">{{ validationError }}</p>

    <div class="run-actions">
      <button type="submit" class="primary" :disabled="isRunning || isUploading">
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

defineExpose({ syncFormFromVariables })
</script>

<style scoped>
.inputs-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.field-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.field-group h3 {
  margin: 0;
  color: #667085;
  font-size: 11px;
  text-transform: uppercase;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #354052;
}
.field em {
  color: #d92d20;
  font-style: normal;
}
.field input,
.field textarea {
  padding: 7px 9px;
  border: 1px solid #d0d5dd;
  border-radius: 7px;
  font: inherit;
}
.field-hint {
  color: #667085;
  font-size: 12px;
}
.validation-error {
  margin: 0;
  padding: 6px 8px;
  border-radius: 7px;
  background: #fef3f2;
  color: #b42318;
  font-size: 11px;
}
.run-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.run-actions button {
  padding: 7px 12px;
  border: 0;
  border-radius: 7px;
  background: #f2f4f7;
  color: #344054;
  font-size: 12px;
  cursor: pointer;
}
.run-actions .primary {
  background: #0033ff;
  color: #fff;
}
.run-actions .primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.run-actions .stop {
  border: 1px solid #fda29b;
  background: #fff;
  color: #b42318;
}
</style>
