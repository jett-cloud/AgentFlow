<template>
  <section class="agent-chat-panel">
    <header class="top-bar">
      <button type="button" class="config-toggle" @click="configOpen = !configOpen">
        <span class="dot" :class="{ on: configOpen }" />
        {{ configOpen ? '隐藏插件配置' : '插件配置 · 模型' }}
      </button>
      <button
        v-if="pluginLocked"
        type="button"
        class="add-tool-btn"
        :disabled="running"
        @click="emit('add-tool')"
      >
        新增工具
      </button>
    </header>

    <div v-show="configOpen" class="config-sheet">
      <div class="meta-fields">
        <label :class="{ invalid: authorError }">
          <span>作者</span>
          <input
            :value="form.author"
            type="text"
            :placeholder="authorPlaceholder"
            spellcheck="false"
            :disabled="pluginLocked"
            @input="patchIdentity('author', $event.target.value)"
          >
          <small class="field-help" :class="{ error: authorError }">
            {{ authorError || authorHelp }}
          </small>
        </label>
        <label :class="{ invalid: pluginError }">
          <span>插件名称</span>
          <input
            :value="form.pluginName"
            type="text"
            :placeholder="pluginPlaceholder"
            spellcheck="false"
            :disabled="pluginLocked"
            @input="patchIdentity('pluginName', $event.target.value)"
          >
          <small class="field-help" :class="{ error: pluginError }">
            {{ pluginError || pluginHelp }}
          </small>
        </label>
        <label class="tool-name-field" :class="{ invalid: toolError }">
          <span>工具名称</span>
          <input
            :value="form.toolName"
            type="text"
            :placeholder="toolPlaceholder"
            spellcheck="false"
            @input="patchIdentity('toolName', $event.target.value)"
          >
          <small class="field-help" :class="{ error: toolError }">
            {{ toolError || toolHelp }}
          </small>
        </label>
      </div>
      <div v-if="toolNames.length" class="tool-chips">
        <button
          v-for="name in toolNames"
          :key="name"
          type="button"
          class="tool-chip"
          :class="{ active: name === form.toolName }"
          @click="patchForm('toolName', name)"
        >
          {{ name }}
        </button>
      </div>
      <label class="model-field">
        <span>模型</span>
        <ModelSelector
          :model-value="selectedModel"
          :require-tool-call="true"
          placeholder="选择支持 Function Calling 的模型"
          @update:model-value="emit('update:selectedModel', $event)"
        />
      </label>
    </div>

    <div ref="scrollEl" class="messages-scroll" @scroll="onMessageScroll">
      <div v-if="!messages.length && !running" class="greeting">
        <h2>需要我帮你做什么？</h2>
        <p>描述工具能力、粘贴 API；空仓库时 Agent 会自动 bootstrap 脚手架。</p>
      </div>

      <div v-for="(item, index) in messages" :key="`${item.role}-${index}`" class="msg-row" :class="item.role">
        <div v-if="item.role === 'assistant'" class="avatar" aria-hidden="true">✦</div>

        <div class="msg-body">
          <div
            v-if="item.role === 'user'"
            class="bubble user-bubble"
            :class="{ clamped: !expanded[index] && isLong(item.content) }"
          >
            {{ item.content }}
          </div>

          <div
            v-else-if="item.role === 'assistant'"
            class="assistant-text"
            :class="{ clamped: !expanded[index] && isLong(item.content) }"
            v-html="renderAssistantMarkdown(item.content)"
          />

          <div v-else-if="item.role === 'tool'" class="tool-card">
            <div class="tool-head">
              <span class="tool-icon">⚒</span>
              <span class="tool-name">{{ toolNameOf(item) }}</span>
              <span class="tool-badge" :class="{ err: isToolError(item) }">
                {{ isToolError(item) ? 'Error' : 'Completed' }}
              </span>
            </div>
            <pre v-if="toolDetail(item)" class="tool-detail">{{ toolDetail(item) }}</pre>
          </div>

          <details v-else-if="item.role === 'thinking'" class="thinking-card" :open="!item.done">
            <summary>模型思考</summary>
            <pre class="thinking-detail">{{ item.content || '模型处理中…' }}</pre>
          </details>

          <div v-else class="system-line">{{ item.content }}</div>

          <button
            v-if="(item.role === 'user' || item.role === 'assistant') && isLong(item.content)"
            type="button"
            class="expand-btn"
            @click="expanded[index] = !expanded[index]"
          >
            {{ expanded[index] ? '收起' : '展开' }}
          </button>
        </div>
      </div>

      <div v-if="running" class="msg-row assistant">
        <div class="avatar" aria-hidden="true">✦</div>
        <div class="thinking-row">
          <span class="timeline-pill thinking">Thinking</span>
          <span class="shimmer">正在思考并修改插件…</span>
        </div>
      </div>
    </div>

    <footer class="composer-wrap">
      <div class="composer" :class="{ disabled: running }">
        <textarea
          :value="input"
          rows="1"
          placeholder="描述要生成或修改的工具…"
          :disabled="running"
          @input="onInput"
          @keydown="onKeydown"
        />
        <div class="composer-bar">
          <button
            v-if="running"
            type="button"
            class="icon-btn stop"
            title="停止"
            @click="emit('stop')"
          >
            <span class="stop-square" />
            停止
          </button>
          <button
            v-else
            type="button"
            class="icon-btn send"
            title="发送"
            :disabled="!canSend"
            @click="emit('send')"
          >
            <span class="send-arrow">↑</span>
          </button>
        </div>
      </div>
      <p class="composer-hint">Enter 发送 · Shift+Enter 换行</p>
    </footer>
  </section>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { useModelStore } from '@/features/integrations/state/useModelStore.js'
import ModelSelector from '@/features/workflow/nodes/shared/ModelSelector.vue'
import { renderMarkdown } from '@/features/workflow/utils/helpers.js'
import { supportsFunctionCalling } from './modelCapabilities.js'
import {
  AUTHOR_FIELD_HELP,
  AUTHOR_FIELD_PLACEHOLDER,
  PLUGIN_FIELD_HELP,
  PLUGIN_FIELD_PLACEHOLDER,
  TOOL_FIELD_HELP,
  TOOL_FIELD_PLACEHOLDER,
  pluginIdentityFieldError,
  toolIdentityFieldError,
} from './pluginIdentityHelpers.js'
import {
  agentStreamScrollVersion,
  isAgentConversationPinned,
  scrollAgentConversationToLatest,
} from './agentEventHelpers.js'

const props = defineProps({
  form: { type: Object, required: true },
  selectedModel: { type: Object, required: true },
  messages: { type: Array, default: () => [] },
  input: { type: String, default: '' },
  running: { type: Boolean, default: false },
  pluginLocked: { type: Boolean, default: false },
  toolNames: { type: Array, default: () => [] },
  identityReady: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:selectedModel',
  'update:input',
  'send',
  'stop',
  'patch-form',
  'add-tool',
])

const configOpen = ref(false)
const scrollEl = ref(null)
const expanded = reactive({})
let scrollPinned = true
const modelStore = useModelStore()
const authorPlaceholder = AUTHOR_FIELD_PLACEHOLDER
const pluginPlaceholder = PLUGIN_FIELD_PLACEHOLDER
const toolPlaceholder = TOOL_FIELD_PLACEHOLDER
const authorHelp = AUTHOR_FIELD_HELP
const pluginHelp = PLUGIN_FIELD_HELP
const toolHelp = TOOL_FIELD_HELP

const authorError = computed(() => pluginIdentityFieldError(props.form.author, { required: true }))
const pluginError = computed(() => pluginIdentityFieldError(props.form.pluginName, { required: true }))
const toolError = computed(() => toolIdentityFieldError(props.form.toolName, { required: true }))
const modelReady = computed(() => Boolean(
  props.selectedModel?.provider?.trim()
  && props.selectedModel?.name?.trim()
  && supportsFunctionCalling(
    modelStore.getModelSpec(props.selectedModel.name, props.selectedModel.provider),
  ),
))
const canSend = computed(() => Boolean(props.input.trim()) && props.identityReady && modelReady.value)

watch(
  () => [props.messages.length, props.running, agentStreamScrollVersion(props.messages)],
  async () => {
    await nextTick()
    scrollAgentConversationToLatest(scrollEl.value, { scrollOuter: scrollPinned })
  },
)

function onMessageScroll() {
  scrollPinned = isAgentConversationPinned(scrollEl.value)
}

function patchForm(key, value) {
  emit('patch-form', { key, value })
}

function patchIdentity(key, value) {
  patchForm(key, value)
}

function toolNameOf(item) {
  const call = item.tool_calls?.[0]
  return call?.tool || call?.name || 'tool'
}

function toolDetail(item) {
  const call = item.tool_calls?.[0]
  return call?.result || call?.summary || ''
}

function isToolError(item) {
  const call = item.tool_calls?.[0]
  return call?.ok === false || call?.status === 'error' || String(item.content || '').includes('失败')
}

function isLong(content) {
  return String(content || '').length > 280 || String(content || '').split('\n').length > 8
}

function renderAssistantMarkdown(content) {
  return renderMarkdown(content || '…')
}

function onInput(event) {
  emit('update:input', event.target.value)
  const el = event.target
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 140)}px`
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    if (!props.running && canSend.value)
      emit('send')
  }
}
</script>

<style scoped>
.agent-chat-panel {
  --ink: #101828;
  --body: #344054;
  --muted: #667085;
  --muted-soft: #98a2b3;
  --hairline: #eaecf0;
  --hairline-strong: #d0d5dd;
  --canvas: #f9fafb;
  --canvas-soft: #f8fafc;
  --surface: #ffffff;
  --surface-strong: #f2f4f7;
  --primary: #5368a9;
  --primary-active: #43558d;
  --error: #d92d20;
  --success: #079455;
  --timeline-thinking: #eef0f8;
  --font: var(--font-sans, Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
  --mono: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--canvas-soft);
  color: var(--ink);
  font-family: var(--font);
}

.top-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 16px 0;
}
.config-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 0;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  padding: 4px 0;
}
.config-toggle:hover { color: var(--ink); }
.add-tool-btn {
  border: 1px solid var(--hairline-strong);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink);
  font-size: 12px;
  font-weight: 500;
  padding: 6px 12px;
  cursor: pointer;
}
.add-tool-btn:disabled { opacity: .55; cursor: not-allowed; }
.tool-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.tool-chip {
  border: 1px solid var(--hairline);
  border-radius: 999px;
  background: var(--surface);
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 4px 10px;
  cursor: pointer;
}
.tool-chip.active {
  border-color: var(--ink);
  background: var(--surface-strong);
  color: var(--ink);
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--muted-soft);
}
.dot.on { background: var(--primary); }

.config-sheet {
  flex-shrink: 0;
  margin: 8px 16px 0;
  padding: 16px;
  border: 1px solid var(--hairline);
  border-radius: 12px;
  background: var(--surface);
}
.meta-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.tool-name-field {
  grid-column: 1 / -1;
}
.field-help {
  display: block;
  margin-top: 4px;
  color: var(--muted-soft);
  font-size: 11px;
  line-height: 1.35;
}
.field-help.error {
  color: var(--error);
}
.model-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
}
label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 500;
}
input {
  box-sizing: border-box;
  width: 100%;
  height: 40px;
  border: 1px solid var(--hairline);
  border-radius: 8px;
  padding: 10px 14px;
  background: var(--surface);
  color: var(--ink);
  font: inherit;
  font-size: 14px;
}
label.invalid input {
  border-color: var(--error);
}

.messages-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 16px 16px;
}

.greeting {
  min-height: 55%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 24px 8px;
}
.greeting h2 {
  margin: 0;
  font-size: 26px;
  font-weight: 400;
  letter-spacing: -0.325px;
  color: var(--ink);
}
.greeting p {
  margin: 10px 0 0;
  color: var(--body);
  font-size: 14px;
}
.msg-row {
  display: flex;
  gap: 10px;
  margin: 14px 0;
  max-width: 100%;
}
.msg-row.user {
  justify-content: flex-end;
}
.msg-row.user .msg-body {
  max-width: 85%;
}
.msg-row.assistant .msg-body,
.msg-row.tool .msg-body,
.msg-row.system .msg-body {
  max-width: 92%;
}
.avatar {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: var(--primary);
  color: #ffffff;
  font-size: 12px;
  margin-top: 2px;
}

.user-bubble {
  background: var(--primary);
  color: #ffffff;
  border-radius: 12px 12px 4px 12px;
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
.assistant-text {
  font-size: 14px;
  line-height: 1.65;
  overflow-wrap: anywhere;
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--hairline-strong);
  border-radius: 4px 12px 12px 12px;
  padding: 10px 14px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}
.assistant-text :deep(.markdown-heading) {
  margin: 0 0 8px;
  color: var(--ink);
  font-weight: 650;
  line-height: 1.35;
}
.assistant-text :deep(h1.markdown-heading) { font-size: 1.25em; }
.assistant-text :deep(h2.markdown-heading) { font-size: 1.15em; }
.assistant-text :deep(h3.markdown-heading),
.assistant-text :deep(h4.markdown-heading),
.assistant-text :deep(h5.markdown-heading),
.assistant-text :deep(h6.markdown-heading) { font-size: 1em; }
.assistant-text :deep(.markdown-list) {
  margin: 8px 0;
  padding-left: 22px;
}
.assistant-text :deep(.markdown-list li) { padding-left: 3px; }
.assistant-text :deep(strong) { font-weight: 650; }
.assistant-text :deep(.markdown-inline-code) {
  border: 1px solid var(--hairline);
  border-radius: 4px;
  background: var(--surface-strong);
  padding: 2px 5px;
  color: var(--primary-active);
  font-family: var(--mono);
  font-size: .9em;
}
.assistant-text :deep(.markdown-code-block) {
  margin: 10px 0;
  overflow-x: auto;
  border: 1px solid var(--hairline);
  border-radius: 8px;
  background: #f8fafc;
  padding: 10px 12px;
  color: var(--body);
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre;
}
.assistant-text :deep(.markdown-link) {
  color: var(--primary-active);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.assistant-text :deep(.markdown-link:hover) { color: var(--primary); }
.clamped {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 8;
  overflow: hidden;
}
.expand-btn {
  border: 0;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  padding: 6px 0 0;
  cursor: pointer;
}
.expand-btn:hover { color: var(--ink); }
.system-line {
  color: var(--muted);
  font-size: 12px;
  padding: 4px 0;
}

.tool-card {
  width: 100%;
  border: 1px solid var(--hairline);
  border-radius: 12px;
  background: var(--surface);
  overflow: hidden;
}
.tool-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--canvas);
  border-bottom: 1px solid var(--hairline);
  font-size: 12px;
}
.tool-icon { opacity: .7; }
.tool-name { font-weight: 600; color: var(--ink); }
.tool-badge {
  margin-left: auto;
  border-radius: 999px;
  background: #e8f6f0;
  color: var(--success);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 2px 8px;
}
.tool-badge.err {
  background: #fce8ee;
  color: var(--error);
}
.tool-detail {
  margin: 0;
  padding: 8px 10px;
  font-size: 12px;
  color: var(--body);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 120px;
  overflow: auto;
  font-family: var(--mono);
}

.thinking-card {
  width: 100%;
  border: 1px solid var(--hairline);
  border-radius: 10px;
  background: var(--canvas);
  color: var(--muted);
  font-size: 12px;
}
.thinking-card summary {
  padding: 8px 10px;
  cursor: pointer;
  font-weight: 600;
  color: var(--body);
}
.thinking-detail {
  margin: 0;
  padding: 8px 10px 10px;
  border-top: 1px solid var(--hairline);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow: auto;
  font: inherit;
  line-height: 1.5;
}

.thinking-row {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--surface);
  border: 1px solid var(--hairline-strong);
  border-radius: 4px 12px 12px 12px;
  padding: 8px 12px;
}
.timeline-pill {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.88px;
  text-transform: uppercase;
  color: var(--ink);
}
.timeline-pill.thinking {
  background: var(--timeline-thinking);
}
.shimmer {
  font-size: 13px;
  font-weight: 500;
  color: var(--body);
}

.composer-wrap {
  flex-shrink: 0;
  padding: 8px 16px 14px;
  background: linear-gradient(180deg, rgb(250 250 247 / 0%) 0%, var(--canvas-soft) 28%);
}
.composer {
  border: 1px solid var(--hairline);
  border-radius: 12px;
  background: var(--surface);
  padding: 10px 10px 8px;
}
.composer.disabled { opacity: .92; }
.composer textarea {
  width: 100%;
  border: 0;
  outline: none;
  resize: none;
  min-height: 44px;
  max-height: 140px;
  padding: 4px 6px;
  font: inherit;
  font-size: 14px;
  line-height: 1.5;
  color: var(--ink);
  background: transparent;
}
.composer textarea::placeholder {
  color: var(--muted-soft);
}
.composer-bar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 0;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
}
.icon-btn.send {
  width: 36px;
  height: 36px;
  padding: 0;
  justify-content: center;
  background: var(--primary);
  color: #fff;
}
.icon-btn.send:hover:not(:disabled) {
  background: var(--primary-active);
}
.icon-btn.send:disabled {
  background: var(--surface-strong);
  color: var(--muted-soft);
  cursor: not-allowed;
}
.send-arrow { font-size: 16px; font-weight: 700; line-height: 1; }
.icon-btn.stop {
  background: var(--ink);
  color: var(--canvas);
}
.stop-square {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  background: currentColor;
}
.composer-hint {
  margin: 8px 4px 0;
  text-align: center;
  color: var(--muted-soft);
  font-size: 11px;
}
</style>
