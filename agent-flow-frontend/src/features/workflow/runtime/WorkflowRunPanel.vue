<template>
  <ChatDebugPanel
    v-if="isChatflow"
    :app-id="appId"
    :start-variables="startVariables"
    :chat-list="chatList"
    :features="features"
    :human-input-forms="humanInputForms"
    :submit-human-input="submitHumanInput"
    :after-answer-suggestions="afterAnswerSuggestions"
    :is-running="isRunning"
    :can-stop="canStop"
    @close="$emit('close')"
    @submit-run="$emit('submit-run', $event)"
    @stop="$emit('stop')"
    @new-conversation="$emit('new-conversation')"
  />
  <aside
    v-else
    class="workflow-run-panel"
    aria-label="工作流调试与预览"
  >
    <header class="panel-header">
      <div>
        <h2>{{ panelTitle }}</h2>
        <p>{{ modeLabel }}</p>
      </div>
      <button type="button" class="close-btn" aria-label="关闭" @click="$emit('close')">×</button>
    </header>

    <div class="tabs" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        role="tab"
        :aria-selected="activeTab === tab.id"
        :class="{ active: activeTab === tab.id }"
        @click="$emit('update:activeTab', tab.id)"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="panel-body">
      <InputsPanel
        v-show="activeTab === 'INPUT'"
        :mode="mode"
        :start-variables="startVariables"
        :is-running="isRunning"
        :can-stop="canStop"
        @submit-run="$emit('submit-run', $event)"
        @stop="$emit('stop')"
        @new-conversation="$emit('new-conversation')"
      />
      <ResultPanel
        v-show="activeTab === 'RESULT'"
        :run-status="runStatus"
        :result-text="resultText"
        :run-error="runError"
        :conversation-id="conversationId"
        :is-running="isRunning"
        :result="result"
        :human-input-forms="humanInputForms"
        :submit-human-input="submitHumanInput"
        @go-detail="$emit('update:activeTab', RUN_TABS.DETAIL)"
      />
      <DetailPanel
        v-show="activeTab === 'DETAIL'"
        :run-status="runStatus"
        :task-id="taskId"
        :run-error="runError"
        :result="result"
        :tracing-count="tracing.length"
        @go-tracing="$emit('update:activeTab', RUN_TABS.TRACING)"
      />
      <TracingPanel
        v-show="activeTab === 'TRACING'"
        :items="tracing"
        :selected-node-id="selectedNodeId"
        @select-node="$emit('select-node', $event)"
      />
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { RUN_TABS } from './applyWorkflowRunEvent.js'
import ChatDebugPanel from './ChatDebugPanel.vue'
import InputsPanel from './InputsPanel.vue'
import ResultPanel from './ResultPanel.vue'
import DetailPanel from './DetailPanel.vue'
import TracingPanel from './TracingPanel.vue'

const props = defineProps({
  mode: { type: String, default: 'workflow' },
  activeTab: { type: String, default: RUN_TABS.INPUT },
  startVariables: { type: Array, default: () => [] },
  chatList: { type: Array, default: () => [] },
  features: { type: Object, default: () => ({}) },
  appId: { type: String, default: '' },
  humanInputForms: { type: Array, default: () => [] },
  submitHumanInput: { type: Function, default: null },
  afterAnswerSuggestions: { type: Array, default: () => [] },
  isRunning: { type: Boolean, default: false },
  canStop: { type: Boolean, default: false },
  runStatus: { type: String, default: 'idle' },
  resultText: { type: String, default: '' },
  runOutputs: { type: [Object, Array, String, Number, Boolean], default: null },
  runError: { type: String, default: '' },
  conversationId: { type: String, default: null },
  taskId: { type: String, default: '' },
  result: { type: Object, default: null },
  tracing: { type: Array, default: () => [] },
  selectedNodeId: { type: String, default: '' },
})

defineEmits([
  'close',
  'update:activeTab',
  'submit-run',
  'stop',
  'new-conversation',
  'select-node',
])

const tabs = [
  { id: RUN_TABS.INPUT, label: 'INPUT' },
  { id: RUN_TABS.RESULT, label: 'RESULT' },
  { id: RUN_TABS.DETAIL, label: 'DETAIL' },
  { id: RUN_TABS.TRACING, label: 'TRACING' },
]

const isChatflow = computed(() => props.mode === 'advanced-chat')
const modeLabel = computed(() => (
  isChatflow.value ? 'Chatflow 调试' : 'Workflow 调试'
))
const panelTitle = computed(() => (
  isChatflow.value ? '调试与预览' : '测试运行'
))
</script>

<style scoped>
.workflow-run-panel {
  position: absolute;
  top: 56px;
  right: 0;
  bottom: 0;
  z-index: 48;
  display: flex;
  width: min(420px, 100%);
  flex-direction: column;
  border-left: 1px solid #eaecf0;
  background: #fff;
  box-shadow: -8px 0 24px rgb(16 24 40 / 6%);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid #f2f4f7;
}

.panel-header h2,
.panel-header p {
  margin: 0;
}

.panel-header h2 {
  color: #101828;
  font-size: 14px;
}

.panel-header p {
  margin-top: 2px;
  color: #667085;
  font-size: 11px;
}

.close-btn {
  padding: 4px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #667085;
  font-size: 18px;
  cursor: pointer;
}

.close-btn:hover {
  background: #f2f4f7;
}

.tabs {
  display: flex;
  gap: 2px;
  padding: 8px 10px 0;
  border-bottom: 1px solid #f2f4f7;
  background: #fafafa;
}

.tabs button {
  flex: 1;
  padding: 8px 4px;
  border: 0;
  border-radius: 8px 8px 0 0;
  background: transparent;
  color: #667085;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.tabs button.active {
  background: #fff;
  color: #101828;
  box-shadow: 0 -1px 0 #fff;
}

.panel-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px;
  background: #fff;
}
</style>
