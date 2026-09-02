<template>
  <section class="debug-preview" aria-label="调试与预览">
    <header class="debug-header">
      <div>
        <h2>调试与预览</h2>
        <p>{{ modeLabel }}</p>
      </div>
      <div class="debug-header-actions">
        <button
          v-if="isChatflow"
          type="button"
          :disabled="isRunning"
          title="清空会话并开始新对话"
          @click="$emit('new-conversation')"
        >
          新对话
        </button>
        <button type="button" aria-label="关闭调试面板" @click="$emit('close')">×</button>
      </div>
    </header>

    <div class="debug-tabs" role="tablist">
      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'debug'"
        :class="{ active: activeTab === 'debug' }"
        @click="activeTab = 'debug'"
      >
        调试
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'nodes'"
        :class="{ active: activeTab === 'nodes' }"
        @click="activeTab = 'nodes'"
      >
        节点
      </button>
    </div>

    <div v-show="activeTab === 'debug'" class="debug-body" role="tabpanel">
      <form class="debug-form" @submit.prevent="handleSubmit">
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
        <div v-else class="field-hint">当前 Start 节点没有用户输入变量。</div>

        <label v-if="isChatflow" class="field">
          <span>调试消息 <em>*</em></span>
          <textarea
            v-model="formQuery"
            rows="3"
            :disabled="isRunning || isUploading"
            placeholder="输入本轮用户消息"
          />
        </label>

        <p v-if="validationError" class="validation-error" role="alert">{{ validationError }}</p>

        <div class="run-actions">
          <button
            type="submit"
            class="primary"
            :disabled="isRunning"
          >
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
        </div>
      </form>

      <div class="result-block">
        <div class="result-meta">
          <span class="status" :data-status="runStatus">{{ statusLabel }}</span>
          <span v-if="conversationId" class="conv-id" title="conversation_id">会话已续跑</span>
        </div>
        <div v-if="runError" class="run-error" aria-live="polite">{{ runError }}</div>
        <h3>输出</h3>
        <pre class="transcript">{{ transcriptDisplay }}</pre>
        <template v-if="runOutputs">
          <h3>终态 Outputs</h3>
          <pre class="transcript">{{ formatValue(runOutputs) }}</pre>
        </template>
      </div>
    </div>

    <div v-show="activeTab === 'nodes'" class="nodes-body" role="tabpanel">
      <div v-if="nodeItems.length" class="runtime-list">
        <article
          v-for="item in nodeItems"
          :key="item.nodeId"
          class="runtime-item"
          :class="{ active: item.nodeId === selectedNodeId }"
        >
          <button class="runtime-item-header" type="button" @click="$emit('select-node', item.nodeId)">
            <span class="node-title">{{ item.title || item.nodeId }}</span>
            <span class="status" :data-status="item.status">{{ nodeStatusLabel(item.status) }}</span>
          </button>
          <div v-if="item.error" class="run-error">{{ item.error }}</div>
          <div class="runtime-values">
            <div>
              <h3>输入</h3>
              <pre>{{ formatValue(item.inputs) }}</pre>
            </div>
            <div>
              <h3>输出</h3>
              <pre>{{ formatValue(item.outputs) }}</pre>
            </div>
          </div>
        </article>
      </div>
      <div v-else class="runtime-empty">运行后节点输入输出会显示在这里。</div>
      <div class="nodes-footer">
        <button type="button" @click="$emit('clear-nodes')">清空节点记录</button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import {
  buildStartVariableDefaults,
  RUN_STATUS,
  validateRequiredStartInputs,
} from '../../model/workflowDebugSession.js'
import { getProcessedStartVariableInputs } from '../startVariableUtils.js'
import StartVariableInput from '../StartVariableInput.vue'

const props = defineProps({
  mode: { type: String, default: 'workflow' },
  startVariables: { type: Array, default: () => [] },
  isRunning: { type: Boolean, default: false },
  canStop: { type: Boolean, default: false },
  runStatus: { type: String, default: RUN_STATUS.idle },
  transcript: { type: String, default: '' },
  runError: { type: String, default: '' },
  runOutputs: { type: [Object, Array, String, Number, Boolean], default: null },
  conversationId: { type: String, default: null },
  nodeItems: { type: Array, default: () => [] },
  selectedNodeId: { type: String, default: '' },
})

const emit = defineEmits([
  'close',
  'submit-run',
  'stop',
  'new-conversation',
  'select-node',
  'clear-nodes',
])

const activeTab = ref('debug')
const formInputs = reactive({})
const formQuery = ref('')
const validationError = ref('')
const uploadingVariables = new Set()
const isUploading = ref(false)

const isChatflow = computed(() => props.mode === 'advanced-chat')
const modeLabel = computed(() => (isChatflow.value ? 'Chatflow 调试' : 'Workflow 调试'))

const statusLabel = computed(() => ({
  [RUN_STATUS.idle]: '待运行',
  [RUN_STATUS.running]: '运行中',
  [RUN_STATUS.succeeded]: '成功',
  [RUN_STATUS.failed]: '失败',
  [RUN_STATUS.stopped]: '已停止',
}[props.runStatus] || props.runStatus))

const transcriptDisplay = computed(() => {
  if (props.transcript)
    return props.transcript
  if (props.isRunning)
    return '等待输出…'
  return '—'
})

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

function nodeStatusLabel(status) {
  return {
    running: '运行中',
    succeeded: '成功',
    failed: '失败',
    exception: '异常',
  }[status] || '等待'
}

function formatValue(value) {
  if (value === undefined || value === null)
    return '—'
  if (typeof value === 'string')
    return value
  try {
    return JSON.stringify(value, null, 2)
  }
  catch {
    return String(value)
  }
}

function focusForm() {
  activeTab.value = 'debug'
}

defineExpose({ focusForm, syncFormFromVariables })
</script>

<style scoped>
.debug-preview {
  position: absolute;
  right: 16px;
  bottom: 80px;
  z-index: 46;
  display: flex;
  width: min(420px, calc(100% - 32px));
  max-height: min(640px, calc(100% - 140px));
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
  border-radius: 14px;
  background: var(--components-panel-bg, #fff);
  box-shadow: 0 8px 24px rgb(16 24 40 / 8%);
}

.debug-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
}

.debug-header h2,
.debug-header p,
.field-group h3,
.result-block h3 {
  margin: 0;
}

.debug-header h2 {
  color: var(--text-primary, #101828);
  font-size: 14px;
}

.debug-header p {
  margin-top: 2px;
  color: var(--text-tertiary, #667085);
  font-size: 11px;
}

.debug-header-actions {
  display: flex;
  gap: 4px;
}

.debug-header-actions button,
.nodes-footer button,
.run-actions button {
  padding: 6px 10px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary, #354052);
  font-size: 12px;
  cursor: pointer;
}

.debug-header-actions button:hover,
.nodes-footer button:hover,
.run-actions button:hover:not(:disabled) {
  background: var(--components-actionbar-item-bg-hover, #f2f4f7);
}

.debug-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 12px 0;
}

.debug-tabs button {
  flex: 1;
  padding: 7px 8px;
  border: 0;
  border-radius: 8px 8px 0 0;
  background: transparent;
  color: var(--text-tertiary, #667085);
  font-size: 12px;
  cursor: pointer;
}

.debug-tabs button.active {
  background: #f8fafc;
  color: var(--text-primary, #101828);
  font-weight: 600;
}

.debug-body,
.nodes-body {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: auto;
  padding: 12px;
  background: #f8fafc;
}

.debug-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 12px;
  padding: 12px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
}

.field-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-group h3,
.result-block h3 {
  color: var(--text-tertiary, #667085);
  font-size: 11px;
  text-transform: uppercase;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary, #354052);
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
  background: #fff;
  color: #101828;
  font: inherit;
}

.field input:focus,
.field textarea:focus {
  outline: 2px solid rgba(0, 51, 255, 0.25);
  border-color: #0033ff;
}

.field-hint {
  color: var(--text-tertiary, #667085);
  font-size: 12px;
}

.validation-error,
.run-error {
  margin: 0;
  padding: 6px 8px;
  border-radius: 7px;
  background: #fef3f2;
  color: #b42318;
  font-size: 11px;
}

.run-actions {
  display: flex;
  gap: 8px;
}

.run-actions .primary {
  background: var(--state-accent-border, #0033ff);
  color: #fff;
}

.run-actions .primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.run-actions .stop {
  border: 1px solid #fda29b;
  color: #b42318;
}

.result-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
}

.result-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status {
  color: var(--text-tertiary, #667085);
  font-size: 11px;
}

.status[data-status='succeeded'] { color: #079455; }
.status[data-status='failed'] { color: #d92d20; }
.status[data-status='running'] { color: #0033ff; }
.status[data-status='stopped'] { color: #b54708; }

.conv-id {
  padding: 2px 6px;
  border-radius: 999px;
  background: #eff4ff;
  color: #155eef;
  font-size: 10px;
}

.transcript,
.runtime-values pre {
  min-height: 48px;
  max-height: 180px;
  margin: 0;
  overflow: auto;
  padding: 8px;
  border-radius: 7px;
  background: var(--workflow-block-parma-bg, #f2f4f7);
  color: var(--text-secondary, #354052);
  font: 10px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.runtime-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.runtime-item {
  border-radius: 10px;
  background: #fff;
  border: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
}

.runtime-item.active {
  background: var(--state-accent-active, rgba(0, 51, 255, 0.08));
}

.runtime-item-header {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  padding: 8px;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.node-title {
  color: var(--text-primary, #101828);
  font-size: 12px;
  font-weight: 600;
}

.runtime-values {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 0 8px 10px;
}

.runtime-values h3 {
  margin: 0 0 4px;
  color: var(--text-tertiary, #667085);
  font-size: 10px;
  text-transform: uppercase;
}

.runtime-empty {
  padding: 28px 16px;
  color: var(--text-tertiary, #667085);
  font-size: 12px;
  text-align: center;
}

.nodes-footer {
  margin-top: 8px;
}

@media (max-width: 640px) {
  .runtime-values {
    grid-template-columns: 1fr;
  }
}
</style>
