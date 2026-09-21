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
      <div class="panel-heading">
        <h2>{{ panelTitle }}</h2>
        <p><span class="mode-dot" aria-hidden="true" />{{ modeLabel }}</p>
      </div>
      <button type="button" class="close-btn" aria-label="关闭" @click="$emit('close')">
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="m5 5 10 10M15 5 5 15" />
        </svg>
      </button>
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
  width: min(480px, 100%);
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgb(16 24 40 / 8%);
  border-right: 0;
  border-radius: 16px 0 0 16px;
  background: rgb(255 255 255 / 98%);
  box-shadow: -12px 0 32px rgb(16 24 40 / 8%), -2px 0 8px rgb(16 24 40 / 4%);
  backdrop-filter: blur(12px);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 64px;
  padding: 16px 20px 12px;
}

.panel-heading {
  min-width: 0;
}

.panel-header h2,
.panel-header p {
  margin: 0;
}

.panel-header h2 {
  color: #101828;
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.01em;
  line-height: 22px;
}

.panel-header p {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 1px;
  color: #98a2b3;
  font-size: 11px;
  line-height: 16px;
}

.mode-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #12b76a;
  box-shadow: 0 0 0 3px rgb(18 183 106 / 10%);
}

.close-btn {
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #667085;
  cursor: pointer;
  transition: color 150ms ease, background 150ms ease;
}

.close-btn svg {
  width: 18px;
  height: 18px;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
}

.close-btn:hover {
  background: #f2f4f7;
  color: #101828;
}

.tabs {
  display: flex;
  min-height: 45px;
  gap: 28px;
  padding: 0 20px;
  border-bottom: 1px solid #eaecf0;
  background: #fff;
}

.tabs button {
  position: relative;
  padding: 0;
  border: 0;
  background: transparent;
  color: #98a2b3;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  cursor: pointer;
  transition: color 150ms ease;
}

.tabs button::after {
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: #155eef;
  content: '';
  opacity: 0;
  transform: scaleX(0.55);
  transition: opacity 150ms ease, transform 150ms ease;
}

.tabs button:hover {
  color: #475467;
}

.tabs button.active {
  color: #344054;
}

.tabs button.active::after {
  opacity: 1;
  transform: scaleX(1);
}

.panel-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: #fff;
  scrollbar-color: #d0d5dd transparent;
  scrollbar-width: thin;
}

@media (max-width: 640px) {
  .workflow-run-panel {
    top: 52px;
    width: 100%;
    border-left: 0;
    border-radius: 0;
  }
}
</style>
