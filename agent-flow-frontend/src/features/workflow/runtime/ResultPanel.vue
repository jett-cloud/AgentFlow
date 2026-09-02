<template>
  <!-- Aligns with Dify draft RESULT = ResultText (Markdown text-first). -->
  <div class="result-panel">
    <div class="meta">
      <span class="status" :data-status="runStatus">{{ statusLabel }}</span>
      <span v-if="conversationId" class="badge">会话已续跑</span>
      <button
        v-if="canCopy"
        type="button"
        class="copy-btn"
        @click="copyResult"
      >
        {{ copied ? '已复制' : '复制' }}
      </button>
    </div>

    <div v-if="runError" class="error" aria-live="polite">{{ runError }}</div>

    <HumanInputFormList
      v-if="humanInputForms.length && submitHumanInput"
      :forms="humanInputForms"
      :submit-form="submitHumanInput"
    />

    <div v-if="isRunning && !resultText && !humanInputForms.length" class="waiting">
      <span class="spinner" aria-hidden="true" />
      生成中…
    </div>

    <template v-else-if="resultText">
      <h3>RESULT</h3>
      <!-- Contrasts Dify result-text.tsx Markdown; copy still uses raw resultText. -->
      <div
        ref="bodyRef"
        class="body markdown-body"
        v-html="renderedResult"
      />
    </template>

    <div v-else-if="!isRunning && !resultFileGroups.length" class="empty">
      <p>暂无结果文本。</p>
      <button type="button" class="link-btn" @click="$emit('go-detail')">查看 DETAIL</button>
    </div>

    <ResultFileList :groups="resultFileGroups" />
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { RUN_STATUS } from './applyWorkflowRunEvent.js'
import HumanInputFormList from './HumanInputFormList.vue'
import ResultFileList from './ResultFileList.vue'
import { resolveResultFileGroups } from './resultFiles.js'
import { renderMarkdown } from '../utils/helpers.js'
import { hydrateMermaidDiagrams } from '../utils/mermaidHydrate.js'

const props = defineProps({
  runStatus: { type: String, default: RUN_STATUS.idle },
  resultText: { type: String, default: '' },
  runError: { type: String, default: '' },
  conversationId: { type: String, default: null },
  isRunning: { type: Boolean, default: false },
  result: { type: Object, default: null },
  humanInputForms: { type: Array, default: () => [] },
  submitHumanInput: { type: Function, default: null },
})

defineEmits(['go-detail'])

const copied = ref(false)
const bodyRef = ref(null)

const statusLabel = computed(() => ({
  [RUN_STATUS.idle]: '待运行',
  [RUN_STATUS.running]: '运行中',
  [RUN_STATUS.succeeded]: '成功',
  [RUN_STATUS.failed]: '失败',
  [RUN_STATUS.stopped]: '已停止',
  [RUN_STATUS.paused]: '已暂停',
}[props.runStatus] || props.runStatus))

const renderedResult = computed(() => renderMarkdown(props.resultText, {
  isResponding: props.isRunning,
}))
const resultFileGroups = computed(() => resolveResultFileGroups(props.result))
const canCopy = computed(() => (
  !!props.resultText
  && (props.runStatus === RUN_STATUS.succeeded || props.runStatus === RUN_STATUS.stopped)
))

watch(renderedResult, async () => {
  await nextTick()
  await hydrateMermaidDiagrams(bodyRef.value)
}, { flush: 'post' })
async function copyResult() {
  if (!props.resultText)
    return
  try {
    await navigator.clipboard.writeText(props.resultText)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  }
  catch {
    copied.value = false
  }
}
</script>

<style scoped>
.result-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.status {
  font-size: 12px;
  font-weight: 600;
  color: #667085;
}
.status[data-status='succeeded'] { color: #079455; }
.status[data-status='failed'] { color: #d92d20; }
.status[data-status='running'] { color: #0033ff; }
.status[data-status='stopped'] { color: #b54708; }
.status[data-status='paused'] { color: #f79009; }
.badge {
  padding: 2px 6px;
  border-radius: 999px;
  background: #eff4ff;
  color: #155eef;
  font-size: 10px;
}
.copy-btn,
.link-btn {
  margin-left: auto;
  padding: 4px 8px;
  border: 1px solid #eaecf0;
  border-radius: 6px;
  background: #fff;
  color: #344054;
  font-size: 11px;
  cursor: pointer;
}
.link-btn {
  margin-left: 0;
  color: #0033ff;
  border-color: #b2ccff;
}
.error {
  padding: 6px 8px;
  border-radius: 7px;
  background: #fef3f2;
  color: #b42318;
  font-size: 11px;
}
.waiting {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  color: #667085;
  font-size: 13px;
}
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid #d0d5dd;
  border-top-color: #0033ff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.empty {
  padding: 20px;
  border: 1px dashed #eaecf0;
  border-radius: 10px;
  background: #f9fafb;
  color: #667085;
  font-size: 13px;
  text-align: center;
}
.empty p { margin: 0 0 10px; }
h3 {
  margin: 0;
  color: #667085;
  font-size: 11px;
  text-transform: uppercase;
}
.body {
  margin: 0;
  min-height: 120px;
  max-height: 360px;
  overflow: auto;
  padding: 10px;
  border-radius: 8px;
  background: #f2f4f7;
  color: #101828;
  font: 12px/1.55 ui-sans-serif, system-ui, -apple-system, sans-serif;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.markdown-body :deep(strong) {
  font-weight: 700;
  color: #101828;
}

.markdown-body :deep(em) {
  font-style: italic;
}

.markdown-body :deep(.markdown-link) {
  color: #155eef;
  text-decoration: underline;
}

.markdown-body :deep(.markdown-list) {
  margin: 6px 0;
  padding-left: 20px;
}

.markdown-body :deep(ul.markdown-list) {
  list-style-type: disc;
}

.markdown-body :deep(ol.markdown-list) {
  list-style-type: decimal;
}

.markdown-body :deep(.markdown-list li) {
  margin-bottom: 4px;
}

.markdown-body :deep(.markdown-inline-code) {
  padding: 1px 4px;
  border-radius: 4px;
  background: rgb(16 24 40 / 6%);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 90%;
}

.markdown-body :deep(.markdown-code-block) {
  margin: 8px 0;
  padding: 8px 10px;
  overflow: auto;
  border-radius: 6px;
  background: #101828;
  color: #f2f4f7;
  font: 11px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: pre;
}

.markdown-body :deep(.markdown-heading) {
  margin: 8px 0 4px;
  color: #101828;
  font-weight: 700;
  line-height: 1.3;
}
.markdown-body :deep(h1.markdown-heading) { font-size: 16px; }
.markdown-body :deep(h2.markdown-heading) { font-size: 14px; }
.markdown-body :deep(h3.markdown-heading) { font-size: 13px; }
.markdown-body :deep(h4.markdown-heading),
.markdown-body :deep(h5.markdown-heading),
.markdown-body :deep(h6.markdown-heading) { font-size: 12px; }

.markdown-body :deep(.md-think) {
  margin: 8px 0;
  color: #475467;
  font-size: 12px;
}
.markdown-body :deep(.md-think-summary) {
  cursor: pointer;
  list-style: none;
  font-weight: 700;
  color: #667085;
  user-select: none;
}
.markdown-body :deep(.md-think-summary)::-webkit-details-marker {
  display: none;
}
.markdown-body :deep(.md-think-body) {
  margin: 6px 0 0 8px;
  padding: 8px 10px;
  border-left: 2px solid #d0d5dd;
  background: #f9fafb;
  color: #475467;
}
</style>
