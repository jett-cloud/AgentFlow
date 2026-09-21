<template>
  <div ref="listRef" class="assist-message-list" @scroll="onListScroll">
    <div v-if="!messages.length && !disabled" class="empty">
      <p class="empty-title">{{ copy.emptyTitle }}</p>
      <p class="empty-hint">{{ copy.emptyHint }}</p>
    </div>

    <article
      v-for="(group, groupIndex) in timeline"
      :key="groupKey(group, groupIndex)"
      :class="['message', groupRole(group) === 'user' ? 'is-user' : 'is-assistant']"
    >
      <div v-if="group.kind === 'turn'" class="bubble turn">
        <template v-for="(block, blockIndex) in group.blocks" :key="blockKey(block, blockIndex)">
          <div
            v-if="block.kind === 'assistant_text'"
            class="turn-text markdown-body"
          >
            <details v-if="hasReasoning(block)" class="thought">
              <summary>{{ thoughtLabel(block) }}</summary>
              <div class="thought-body">{{ block.reasoning }}</div>
            </details>
            <div v-if="block.text" v-html="assistantHtml(block.text)" />
          </div>
          <ul v-else-if="block.kind === 'activity' || block.kind === 'operations'" class="turn-ops">
            <li v-for="(operation, operationIndex) in block.items" :key="operation.key || operationIndex">
              <span :class="['activity-item-dot', `is-${operation.status || 'done'}`]" aria-hidden="true" />
              {{ operation.message || operation.action || copy.statusWorking }}
            </li>
          </ul>
          <div
            v-else-if="block.kind === 'completion'"
            class="turn-completion markdown-body"
            v-html="completionHtml(block)"
          />
        </template>
      </div>

      <div v-else-if="group.message.kind === 'clarification'" class="bubble clarification">
        <AssistClarificationCard
          :questions="group.message.clarification?.questions || []"
          :language="language"
          :disabled="disabled || group.message.status === 'resolved' || group.message.resolved"
          @submit="answers => submitClarification(group.message, answers)"
        />
        <p v-if="group.message.statusText" class="message-status">{{ group.message.statusText }}</p>
      </div>

      <div
        v-else-if="group.message.kind === 'completion'"
        class="bubble completion markdown-body"
        v-html="completionHtml(group.message)"
      />

      <div
        v-else-if="group.message.kind === 'assistant_text' || (group.message.role === 'assistant' && (group.message.text || hasReasoning(group.message)))"
        class="bubble markdown-body"
      >
        <details v-if="hasReasoning(group.message)" class="thought">
          <summary>{{ thoughtLabel(group.message) }}</summary>
          <div class="thought-body">{{ group.message.reasoning }}</div>
        </details>
        <div v-if="group.message.text" v-html="assistantHtml(group.message.text)" />
      </div>

      <div v-else-if="group.message.role === 'user' && group.message.references?.length" class="bubble">
        <template v-for="(part, partIndex) in mentionParts(group.message)" :key="partIndex">
          <span v-if="part.reference" class="mention-chip">{{ part.reference.label }}</span>
          <template v-else>{{ part.text }}</template>
        </template>
      </div>

      <div v-else class="bubble">{{ group.message.text }}</div>
    </article>

    <section v-if="friendlyErrors.length" class="error-list" role="alert">
      <div v-for="(error, index) in friendlyErrors" :key="index">
        <p>{{ error.text || copy.globalError }}</p>
        <details v-if="error.raw && error.raw !== error.text">
          <summary>{{ copy.rawError }}</summary>
          <pre>{{ error.raw }}</pre>
        </details>
      </div>
      <button v-if="retryable" type="button" @click="$emit('retry')">
        {{ copy.retryThisStep }}
      </button>
      <button v-else-if="errorAction === 'retry'" type="button" @click="$emit('retry')">
        {{ copy.retry }}
      </button>
      <div v-else-if="errorAction === 'shorten_or_switch_model'" class="error-actions">
        <button type="button" @click="$emit('shorten-requirement')">{{ copy.shortenRequirement }}</button>
        <button type="button" @click="$emit('switch-model')">{{ copy.switchModel }}</button>
      </div>
    </section>

    <section v-if="warnings.length" class="warning-list" role="status">
      <p v-for="(warning, index) in warnings" :key="index">{{ warning.detail || warning.message || warning }}</p>
    </section>

    <p class="assist-live-announcement visually-hidden" role="status" aria-live="polite" aria-atomic="true">
      {{ liveAnnouncement }}
    </p>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { renderMarkdown } from '../utils/helpers.js'
import AssistClarificationCard from './AssistClarificationCard.vue'
import { friendlyAssistError } from './assistErrors.js'
import { assistCopy, formatAssistCompletionMarkdown } from './assistLanguage.js'
import { createAssistLiveAnnouncement } from './assistLiveAnnouncement.js'
import { stripAssistToolJson, groupAssistTimeline } from './assistStreamMessage.js'
import { splitTextByMentions } from './assistMentions.js'

const SCROLL_PIN_PX = 48
const SCROLL_MERGE_MS = 50

const props = defineProps({
  disabled: { type: Boolean, default: false },
  messages: { type: Array, default: () => [] },
  errors: { type: Array, default: () => [] },
  warnings: { type: Array, default: () => [] },
  retryable: { type: Boolean, default: false },
  errorAction: { type: String, default: 'none' },
  language: { type: String, default: 'zh-Hans' },
})

const emit = defineEmits(['answer-clarification', 'retry', 'shorten-requirement', 'switch-model'])
const copy = computed(() => assistCopy(props.language))
const friendlyErrors = computed(() => props.errors.map(error => friendlyAssistError(error, props.language)))
const listRef = ref(null)
const liveAnnouncement = ref('')
const live = createAssistLiveAnnouncement({
  onAnnounce: text => { liveAnnouncement.value = text },
})
const timeline = computed(() => groupAssistTimeline(props.messages))
let pinnedToBottom = true
let scrollTimer = 0

const streamingText = computed(() => {
  for (let index = props.messages.length - 1; index >= 0; index -= 1) {
    const message = props.messages[index]
    if (message?.kind === 'assistant_text' && message.streaming)
      return String(message.text || '')
  }
  return ''
})

function groupKey(group, index) {
  if (group.kind === 'turn') {
    const first = group.blocks[0]
    return `turn:${first?.message_id || first?.items?.[0]?.key || first?.kind || index}`
  }
  const message = group.message
  return message?.turnKey || message?.clarification?.clarification_id || `${message?.run_id || 'message'}:${message?.sequence ?? index}`
}

function groupRole(group) {
  if (group.kind === 'turn')
    return 'assistant'
  return group.message?.role
}

function blockKey(block, index) {
  return block?.message_id || block?.items?.[0]?.key || `${block?.kind || 'block'}:${index}`
}

function submitClarification(message, answers) {
  if (!answers?.length)
    return
  emit('answer-clarification', { index: props.messages.indexOf(message), answers })
}

function hasReasoning(message) {
  return Boolean(String(message?.reasoning || '').trim())
}

function thoughtLabel(message) {
  return message?.reasoningStreaming ? copy.value.thinking : copy.value.thought
}

function mentionParts(message) {
  return splitTextByMentions(message?.text, message?.references)
}

function assistantHtml(text) {
  return renderMarkdown(stripAssistToolJson(text))
}

function completionHtml(message) {
  return renderMarkdown(formatAssistCompletionMarkdown(message, props.language))
}

function isPinnedToBottom(el) {
  if (!el)
    return true
  return el.scrollHeight - el.scrollTop - el.clientHeight <= SCROLL_PIN_PX
}

function onListScroll() {
  pinnedToBottom = isPinnedToBottom(listRef.value)
}

function scheduleScrollToBottom() {
  if (scrollTimer)
    return
  scrollTimer = globalThis.setTimeout(() => {
    scrollTimer = 0
    void flushScrollToBottom()
  }, SCROLL_MERGE_MS)
}

async function flushScrollToBottom() {
  await nextTick()
  const el = listRef.value
  if (!el || !pinnedToBottom)
    return
  el.scrollTop = el.scrollHeight
}

watch(streamingText, value => live.update(value))
watch(() => props.messages, scheduleScrollToBottom, { deep: true })
watch(() => props.errors.length, scheduleScrollToBottom)
onBeforeUnmount(() => {
  if (scrollTimer)
    globalThis.clearTimeout(scrollTimer)
  live.dispose()
})
</script>

<style scoped>
.assist-message-list {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 12px;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 16px 14px;
  background: #f8fafc;
}

.empty {
  margin: auto;
  padding: 28px 16px;
  color: #667085;
  text-align: center;
}

.empty-title {
  color: #344054;
  font-weight: 600;
}

.message {
  display: flex;
  min-width: 0;
  max-width: 92%;
}

.message.is-user {
  margin-left: auto;
}

.message.is-assistant {
  width: 92%;
}

.message.is-assistant > .bubble {
  width: 100%;
}

.bubble {
  box-sizing: border-box;
  min-width: 0;
  max-width: 100%;
  padding: 10px 12px;
  border: 1px solid #e4e7ec;
  border-radius: 12px;
  background: #fff;
  color: #101828;
  line-height: 1.5;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble.markdown-body {
  white-space: normal;
}

.bubble.turn {
  display: grid;
  gap: 10px;
}

.turn-text,
.turn-completion {
  min-width: 0;
  white-space: normal;
}

.thought {
  margin: 0 0 8px;
  color: #667085;
}

.thought summary {
  display: flex;
  cursor: pointer;
  align-items: center;
  list-style: none;
  font-size: 13px;
  font-weight: 600;
  user-select: none;
}

.thought summary::-webkit-details-marker {
  display: none;
}

.thought summary::before {
  display: inline-block;
  width: 0.55em;
  margin-right: 6px;
  content: '▸';
  transition: transform 0.2s;
}

.thought[open] summary::before {
  transform: rotate(90deg);
}

.thought-body {
  margin-top: 6px;
  border-left: 2px solid #d0d5dd;
  padding: 8px 10px;
  background: #f2f4f7;
  color: #475467;
  font-size: 13px;
  line-height: 1.45;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.turn-ops {
  display: grid;
  min-width: 0;
  gap: 6px;
  margin: 0;
  padding: 8px 10px;
  list-style: none;
  border-radius: 8px;
  background: #f2f4f7;
}

.turn-ops li {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 7px;
  color: #344054;
  font-size: 13px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.is-user .bubble {
  border-color: #175cd3;
  background: #175cd3;
  color: #fff;
}

.mention-chip {
  display: inline-flex;
  align-items: center;
  margin: 0 1px;
  border: 1px solid rgb(255 255 255 / 55%);
  border-radius: 999px;
  background: rgb(255 255 255 / 16%);
  padding: 0 8px;
  font-size: 12px;
  line-height: 1.6;
}

.markdown-body :deep(p) {
  margin: 0 0 0.6em;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(strong) {
  font-weight: 700;
}

.markdown-body :deep(.markdown-inline-code) {
  padding: 1px 4px;
  border-radius: 4px;
  background: rgb(16 24 40 / 8%);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 90%;
  overflow-wrap: anywhere;
}

.markdown-body :deep(.markdown-code-block) {
  box-sizing: border-box;
  max-width: 100%;
  margin: 6px 0;
  padding: 8px;
  overflow: auto;
  border-radius: 6px;
  background: #101828;
  color: #f2f4f7;
  font: 12px/1.4 ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: pre;
}

.markdown-body :deep(.markdown-list) {
  margin: 4px 0;
  padding-left: 18px;
}

.markdown-body :deep(.markdown-link) {
  color: #155eef;
  text-decoration: underline;
}

.markdown-body :deep(.markdown-heading) {
  margin: 0.4em 0 0.2em;
  font-weight: 700;
}

.activity ul {
  display: grid;
  gap: 6px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}

.activity li {
  display: flex;
  align-items: flex-start;
  gap: 7px;
}

.clarification {
  min-width: 240px;
}

.error-list button {
  min-height: 32px;
}

.clarification :deep(button:focus-visible),
.clarification :deep(input:focus-visible),
.error-list button:focus-visible,
.activity summary:focus-visible {
  outline: 2px solid #175cd3;
  outline-offset: 2px;
}

.activity summary {
  display: flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
}

.activity-dot,
.activity-item-dot {
  flex: 0 0 auto;
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 50%;
  background: #667085;
}

.activity-dot {
  margin-top: 0;
}

.activity-dot.is-running,
.activity-item-dot.is-running {
  background: #175cd3;
}

.activity-dot.is-failed,
.activity-item-dot.is-failed {
  background: #d92d20;
}

.activity-item-dot.is-done,
.activity-dot.is-completed {
  background: #12b76a;
}

.error-list,
.warning-list {
  padding: 10px 12px;
  border-radius: 10px;
}

.error-list {
  background: #fef3f2;
  color: #b42318;
}

.warning-list {
  background: #fffaeb;
  color: #b54708;
}

.error-actions {
  display: flex;
  gap: 8px;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

@media (prefers-reduced-motion: reduce) {
  .assist-message-list,
  .bubble {
    scroll-behavior: auto;
    transition: none;
  }
}
</style>
