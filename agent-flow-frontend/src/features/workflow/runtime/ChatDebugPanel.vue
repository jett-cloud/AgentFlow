<template>
  <aside class="chat-debug-panel" aria-label="Chatflow 调试与预览">
    <header class="panel-header">
      <div>
        <h2>调试与预览</h2>
        <p>Chatflow 调试</p>
      </div>
      <div class="header-actions">
        <button
          type="button"
          class="ghost"
          :disabled="isRunning"
          @click="$emit('new-conversation')"
        >
          新对话
        </button>
        <button type="button" class="close-btn" aria-label="关闭" @click="$emit('close')">×</button>
      </div>
    </header>

    <details v-if="startVariables.length" class="start-vars" open>
      <summary>开始变量</summary>
      <div class="start-vars-body">
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
            @uploading="handleStartUploading"
          />
        </label>
      </div>
    </details>

    <div ref="messagesRef" class="messages" role="log" aria-live="polite">
      <template v-if="showWelcome">
        <div v-if="openingText" class="bubble-row assistant">
          <div
            class="bubble assistant opening markdown-body"
            v-html="renderMarkdown(openingText)"
          />
        </div>
        <div v-if="suggestedQuestions.length" class="suggestions" aria-label="建议问题">
          <button
            v-for="(question, index) in suggestedQuestions"
            :key="`${index}-${question}`"
            type="button"
            class="suggestion-chip"
            :disabled="isRunning"
            @click="useSuggestion(question)"
          >
            {{ question }}
          </button>
        </div>
        <div v-if="!openingText && !suggestedQuestions.length" class="empty">
          输入消息开始调试对话。会话会跨轮保留，点击「新对话」可重置。
        </div>
      </template>

      <div
        v-for="msg in chatList"
        :key="msg.id"
        class="bubble-row"
        :class="msg.role"
      >
        <div class="bubble" :class="[msg.role, msg.role === 'assistant' ? 'markdown-body' : '']">
          <div
            v-if="msg.content && msg.role === 'assistant'"
            v-html="renderMarkdown(msg.content, { isResponding: msg.status === 'streaming' })"
          />
          <pre v-else-if="msg.content">{{ msg.content }}</pre>
          <span v-else-if="msg.role === 'assistant' && isRunning" class="waiting">生成中…</span>
          <span v-else-if="msg.role === 'assistant' && msg.error" class="error-text">{{ msg.error }}</span>
          <span v-else-if="msg.role === 'assistant'" class="waiting">（空回复）</span>
          <ChatMessageFiles
            v-if="msg.message_files?.length"
            :files="msg.message_files"
          />
          <CitationList
            v-if="msg.role === 'assistant' && showCitations && msg.citation?.length"
            :items="msg.citation"
          />
          <div
            v-if="msg.role === 'assistant' && showTts && msg.content && msg.status !== 'streaming'"
            class="bubble-actions"
          >
            <button
              type="button"
              class="tts-btn"
              :disabled="ttsPlayingId === msg.id"
              @click="playAssistantAudio(msg)"
            >
              {{ ttsPlayingId === msg.id ? '播放中…' : '播放' }}
            </button>
          </div>
        </div>
      </div>

      <HumanInputFormList
        v-if="humanInputForms.length && submitHumanInput"
        :forms="humanInputForms"
        :submit-form="submitHumanInput"
      />

      <div
        v-if="!isRunning && afterAnswerSuggestions.length"
        class="suggestions after-answer"
        aria-label="回答后建议问题"
      >
        <button
          v-for="(question, index) in afterAnswerSuggestions"
          :key="`after-${index}-${question}`"
          type="button"
          class="suggestion-chip"
          @click="useSuggestion(question)"
        >
          {{ question }}
        </button>
      </div>
    </div>

    <p v-if="validationError" class="validation-error" role="alert">{{ validationError }}</p>

    <form class="composer" @submit.prevent="handleSend">
      <div v-if="fileUploadEnabled && pendingFiles.length" class="pending-files" aria-label="待发送附件">
        <div
          v-for="file in pendingFiles"
          :key="file.id"
          class="pending-file"
          :class="{ failed: file.progress === -1, uploading: file.progress >= 0 && file.progress < 100 }"
        >
          <span class="pending-name">{{ file.name }}</span>
          <button
            type="button"
            class="ghost danger"
            :disabled="isRunning || uploading"
            aria-label="移除附件"
            @click="removePendingFile(file.id)"
          >
            ×
          </button>
        </div>
      </div>
      <div v-if="showRemoteAttach" class="remote-row">
        <input
          v-model="remoteUrl"
          type="url"
          :disabled="isRunning || uploading || !canAttachMore"
          placeholder="粘贴文件链接 (https://…)"
          @keydown.enter.prevent="onRemoteAdd"
        >
        <button
          type="button"
          class="remote-btn"
          :disabled="isRunning || uploading || !canAttachMore"
          @click="onRemoteAdd"
        >
          添加链接
        </button>
      </div>
      <textarea
        v-model="formQuery"
        rows="2"
        :disabled="isRunning"
        placeholder="输入本轮用户消息"
        @keydown.enter.exact.prevent="handleSend"
      />
      <div class="composer-actions">
        <template v-if="showLocalAttach">
          <input
            ref="fileInputRef"
            type="file"
            class="hidden-file"
            :accept="fileAccept"
            multiple
            :disabled="isRunning || uploading || !canAttachMore"
            @change="onPickFiles"
          />
          <button
            type="button"
            class="ghost attach"
            :disabled="isRunning || uploading || !canAttachMore"
            @click="openFilePicker"
          >
            {{ uploading ? '上传中…' : '附件' }}
          </button>
        </template>
        <button
          v-if="showStt"
          type="button"
          class="ghost stt"
          :class="{ recording: sttStatus === 'recording' }"
          :disabled="isRunning || uploading || sttStatus === 'converting'"
          @click="toggleStt"
        >
          {{ sttLabel }}
        </button>
        <button
          v-if="isRunning && canStop"
          type="button"
          class="stop"
          @click="$emit('stop')"
        >
          停止
        </button>
        <button type="submit" class="primary" :disabled="isRunning || uploading || sttStatus !== 'idle'">
          {{ isRunning ? '发送中…' : '发送' }}
        </button>
      </div>
      <p v-if="sttError" class="stt-error" role="alert">{{ sttError }}</p>
    </form>
  </aside>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import {
  buildStartVariableDefaults,
  validateRequiredStartInputs,
} from './applyWorkflowRunEvent.js'
import { getProcessedStartVariableInputs } from './startVariableUtils.js'
import {
  allowsFileUploadLocal,
  allowsFileUploadRemote,
  getFileUploadAccept,
  getFileUploadNumberLimits,
  getOpeningStatementText,
  getSuggestedQuestions,
  isCitationEnabled,
  isFileUploadEnabled,
  isTextToSpeechEnabled,
  isSpeechToTextEnabled,
  getTextToSpeechVoice,
} from '../model/workflowFeatures.js'
import {
  processOpeningStatement,
  processOpeningSuggestedQuestions,
} from '../model/processOpeningStatement.js'
import HumanInputFormList from './HumanInputFormList.vue'
import ChatMessageFiles from './ChatMessageFiles.vue'
import CitationList from './CitationList.vue'
import { renderMarkdown } from '../utils/helpers.js'
import { hydrateMermaidDiagrams } from '../utils/mermaidHydrate.js'
import { uploadConsoleFile, uploadRemoteFileInfo } from '@/shared/media/difyFilesApi.js'
import { textToAudio, audioToText } from '@/shared/media/difyAudioApi.js'
import {
  buildRecordingBlob,
  mergeTranscriptIntoQuery,
  pickRecorderMimeType,
  STT_MAX_SECONDS,
} from './sttRecorder.js'
import {
  createLocalHumanInputFileEntity,
  createRemoteHumanInputFileEntity,
  getProcessedHumanInputFiles,
  isValidRemoteFileUrl,
  markHumanInputFileUploaded,
} from './humanInputFormUtils.js'
import { normalizeChatMessageFilesFromPending } from './chatMessageFiles.js'
import StartVariableInput from './StartVariableInput.vue'

const props = defineProps({
  startVariables: { type: Array, default: () => [] },
  chatList: { type: Array, default: () => [] },
  features: { type: Object, default: () => ({}) },
  humanInputForms: { type: Array, default: () => [] },
  submitHumanInput: { type: Function, default: null },
  afterAnswerSuggestions: { type: Array, default: () => [] },
  isRunning: { type: Boolean, default: false },
  canStop: { type: Boolean, default: false },
  appId: { type: String, default: '' },
})

const emit = defineEmits(['close', 'submit-run', 'stop', 'new-conversation'])

const formInputs = reactive({})
const formQuery = ref('')
const remoteUrl = ref('')
const validationError = ref('')
const messagesRef = ref(null)
const fileInputRef = ref(null)
const pendingFiles = ref([])
const uploading = ref(false)
const startUploadingVariables = new Set()
const ttsPlayingId = ref('')
/** @type {import('vue').Ref<HTMLAudioElement | null>} */
const ttsAudio = ref(null)

const openingText = computed(() => processOpeningStatement(
  getOpeningStatementText(props.features),
  formInputs,
  props.startVariables,
))
const suggestedQuestions = computed(() => processOpeningSuggestedQuestions(
  getSuggestedQuestions(props.features),
  formInputs,
  props.startVariables,
))
const hasUserMessage = computed(() => props.chatList.some(msg => msg.role === 'user'))
const showWelcome = computed(() => !hasUserMessage.value)
const showCitations = computed(() => isCitationEnabled(props.features))
const showTts = computed(() => isTextToSpeechEnabled(props.features) && Boolean(props.appId))
const showStt = computed(() => isSpeechToTextEnabled(props.features) && Boolean(props.appId))
const sttStatus = ref('idle') // idle | recording | converting
const sttError = ref('')
/** @type {MediaRecorder | null} */
let mediaRecorder = null
/** @type {MediaStream | null} */
let mediaStream = null
/** @type {Blob[]} */
let sttChunks = []
/** @type {ReturnType<typeof setTimeout> | null} */
let sttTimer = null
const fileUploadEnabled = computed(() => isFileUploadEnabled(props.features))
const showLocalAttach = computed(() => allowsFileUploadLocal(props.features))
const showRemoteAttach = computed(() => allowsFileUploadRemote(props.features))
const fileLimit = computed(() => getFileUploadNumberLimits(props.features))
const fileAccept = computed(() => getFileUploadAccept(props.features))
const canAttachMore = computed(() => pendingFiles.value.length < fileLimit.value)

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

watch(
  () => [props.chatList.length, props.chatList[props.chatList.length - 1]?.content, openingText.value],
  async () => {
    await nextTick()
    const el = messagesRef.value
    if (el) {
      el.scrollTop = el.scrollHeight
      await hydrateMermaidDiagrams(el)
    }
  },
)

watch(fileUploadEnabled, (enabled) => {
  if (!enabled) {
    pendingFiles.value = []
    remoteUrl.value = ''
  }
})

function openFilePicker() {
  fileInputRef.value?.click?.()
}

function removePendingFile(id) {
  pendingFiles.value = pendingFiles.value.filter(f => f.id !== id)
}

async function onPickFiles(event) {
  if (!showLocalAttach.value)
    return
  const picked = Array.from(event?.target?.files || [])
  if (fileInputRef.value)
    fileInputRef.value.value = ''
  if (!picked.length)
    return

  validationError.value = ''
  const room = Math.max(0, fileLimit.value - pendingFiles.value.length)
  const toUpload = picked.slice(0, room)
  if (!toUpload.length) {
    validationError.value = `最多上传 ${fileLimit.value} 个文件`
    return
  }

  uploading.value = true
  try {
    for (const file of toUpload) {
      let entity = createLocalHumanInputFileEntity(file)
      entity = { ...entity, progress: 30 }
      pendingFiles.value = [...pendingFiles.value, entity]
      try {
        const res = await uploadConsoleFile(file)
        entity = markHumanInputFileUploaded(entity, res)
      }
      catch (err) {
        entity = { ...entity, progress: -1, uploadedId: '' }
        validationError.value = err?.message || '文件上传失败'
      }
      pendingFiles.value = pendingFiles.value
        .map(f => (f.id === entity.id ? entity : f))
        .filter(f => f.progress !== -1)
    }
  }
  finally {
    uploading.value = false
  }
}

async function onRemoteAdd() {
  if (!showRemoteAttach.value)
    return
  const url = String(remoteUrl.value || '').trim()
  validationError.value = ''
  if (!isValidRemoteFileUrl(url)) {
    validationError.value = '请输入有效的 http(s) 链接'
    return
  }
  if (!canAttachMore.value) {
    validationError.value = `最多上传 ${fileLimit.value} 个文件`
    return
  }

  uploading.value = true
  let entity = createRemoteHumanInputFileEntity(url)
  entity = { ...entity, progress: 30 }
  pendingFiles.value = [...pendingFiles.value, entity]
  try {
    const res = await uploadRemoteFileInfo(url)
    entity = markHumanInputFileUploaded(entity, res)
    pendingFiles.value = pendingFiles.value.map(f => (f.id === entity.id ? entity : f))
    remoteUrl.value = ''
  }
  catch (err) {
    validationError.value = err?.message || '链接无效或无法拉取文件'
    pendingFiles.value = pendingFiles.value.filter(f => f.id !== entity.id)
  }
  finally {
    uploading.value = false
  }
}

function emitRun(query) {
  validationError.value = ''
  const missing = validateRequiredStartInputs(props.startVariables, formInputs)
  if (missing.length) {
    validationError.value = `请填写必填变量：${missing.join('、')}`
    return
  }
  const trimmed = String(query || '').trim()
  if (!trimmed) {
    validationError.value = '请输入调试消息'
    return
  }
  if (uploading.value || startUploadingVariables.size) {
    validationError.value = '请等待附件上传完成'
    return
  }
  const files = getProcessedHumanInputFiles(pendingFiles.value)
  if (pendingFiles.value.length && !files.length) {
    validationError.value = '附件尚未上传成功'
    return
  }
  const messageFiles = normalizeChatMessageFilesFromPending(pendingFiles.value)
  emit('submit-run', {
    inputs: getProcessedStartVariableInputs(props.startVariables, formInputs),
    query: trimmed,
    files,
    messageFiles,
  })
  formQuery.value = ''
  remoteUrl.value = ''
  pendingFiles.value = []
}

function handleStartUploading({ variable, uploading: isUploading }) {
  if (isUploading) startUploadingVariables.add(variable)
  else startUploadingVariables.delete(variable)
}

function handleSend() {
  emitRun(formQuery.value)
}

function useSuggestion(question) {
  emitRun(question)
}

async function playAssistantAudio(msg) {
  if (!props.appId || !msg?.content || ttsPlayingId.value)
    return
  validationError.value = ''
  if (ttsAudio.value) {
    ttsAudio.value.pause()
    ttsAudio.value = null
  }
  ttsPlayingId.value = msg.id
  try {
    const blob = await textToAudio(props.appId, {
      text: msg.content,
      voice: getTextToSpeechVoice(props.features),
      messageId: msg.messageId || '',
      streaming: false,
    })
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    ttsAudio.value = audio
    audio.onended = () => {
      URL.revokeObjectURL(url)
      ttsPlayingId.value = ''
      ttsAudio.value = null
    }
    audio.onerror = () => {
      URL.revokeObjectURL(url)
      ttsPlayingId.value = ''
      ttsAudio.value = null
      validationError.value = '语音播放失败'
    }
    await audio.play()
  }
  catch (err) {
    ttsPlayingId.value = ''
    validationError.value = err?.message || '文字转语音失败'
  }
}

const sttLabel = computed(() => {
  if (sttStatus.value === 'recording')
    return '停止录音'
  if (sttStatus.value === 'converting')
    return '识别中…'
  return '语音'
})

function clearSttTimer() {
  if (sttTimer) {
    clearTimeout(sttTimer)
    sttTimer = null
  }
}

function stopMediaTracks() {
  if (mediaStream) {
    mediaStream.getTracks().forEach(track => track.stop())
    mediaStream = null
  }
}

async function toggleStt() {
  if (sttStatus.value === 'recording') {
    await stopSttAndTranscribe()
    return
  }
  if (sttStatus.value !== 'idle')
    return
  await startStt()
}

async function startStt() {
  sttError.value = ''
  if (!navigator?.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    sttError.value = '当前浏览器不支持麦克风录音'
    return
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mimeType = pickRecorderMimeType()
    mediaRecorder = mimeType
      ? new MediaRecorder(mediaStream, { mimeType })
      : new MediaRecorder(mediaStream)
    sttChunks = []
    mediaRecorder.ondataavailable = (event) => {
      if (event.data?.size)
        sttChunks.push(event.data)
    }
    mediaRecorder.start(250)
    sttStatus.value = 'recording'
    clearSttTimer()
    sttTimer = setTimeout(() => {
      if (sttStatus.value === 'recording')
        stopSttAndTranscribe()
    }, STT_MAX_SECONDS * 1000)
  }
  catch (err) {
    stopMediaTracks()
    mediaRecorder = null
    sttStatus.value = 'idle'
    sttError.value = err?.message || '无法打开麦克风'
  }
}

async function stopSttAndTranscribe() {
  clearSttTimer()
  const recorder = mediaRecorder
  if (!recorder || sttStatus.value !== 'recording')
    return
  sttStatus.value = 'converting'
  const mimeType = recorder.mimeType || pickRecorderMimeType() || 'audio/webm'
  const blob = await new Promise((resolve) => {
    recorder.onstop = () => {
      resolve(buildRecordingBlob(sttChunks, mimeType))
    }
    try {
      recorder.stop()
    }
    catch {
      resolve(buildRecordingBlob(sttChunks, mimeType))
    }
  })
  stopMediaTracks()
  mediaRecorder = null
  sttChunks = []
  if (!blob || !blob.size) {
    sttStatus.value = 'idle'
    sttError.value = '未录到有效音频'
    return
  }
  try {
    const text = await audioToText(props.appId, blob)
    formQuery.value = mergeTranscriptIntoQuery(formQuery.value, text)
    if (!String(text || '').trim())
      sttError.value = '未识别到文字'
  }
  catch (err) {
    sttError.value = err?.message || '语音转文字失败'
  }
  finally {
    sttStatus.value = 'idle'
  }
}
</script>

<style scoped>
.chat-debug-panel {
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

.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.ghost {
  padding: 5px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #344054;
  font-size: 12px;
  cursor: pointer;
}

.ghost:hover:not(:disabled) {
  background: #f2f4f7;
}

.ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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

.start-vars {
  border-bottom: 1px solid #f2f4f7;
  background: #fafafa;
}

.start-vars summary {
  padding: 8px 14px;
  color: #667085;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  cursor: pointer;
  list-style: none;
}

.start-vars-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 14px 12px;
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
.composer textarea {
  padding: 7px 9px;
  border: 1px solid #d0d5dd;
  border-radius: 7px;
  font: inherit;
}

.messages {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 14px;
  background: #fff;
}

.empty {
  color: #98a2b3;
  font-size: 12px;
  line-height: 1.5;
  text-align: center;
  padding: 24px 8px;
}

.bubble-row {
  display: flex;
  margin-bottom: 10px;
}

.bubble-row.user {
  justify-content: flex-end;
}

.bubble-row.assistant {
  justify-content: flex-start;
}

.bubble {
  max-width: 88%;
  padding: 8px 10px;
  border-radius: 10px;
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble pre {
  margin: 0;
  font: inherit;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble.user {
  background: #0033ff;
  color: #fff;
  border-bottom-right-radius: 4px;
}

.bubble.assistant {
  background: #f2f4f7;
  color: #101828;
  border: 1px solid #eaecf0;
  border-bottom-left-radius: 4px;
  white-space: normal;
}

.bubble.assistant.markdown-body :deep(strong) {
  font-weight: 700;
}

.bubble.assistant.markdown-body :deep(.markdown-inline-code) {
  padding: 1px 4px;
  border-radius: 4px;
  background: rgb(16 24 40 / 8%);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 90%;
}

.bubble.assistant.markdown-body :deep(.markdown-code-block) {
  margin: 6px 0;
  padding: 8px;
  overflow: auto;
  border-radius: 6px;
  background: #101828;
  color: #f2f4f7;
  font: 11px/1.4 ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: pre;
}

.bubble.assistant.markdown-body :deep(.markdown-list) {
  margin: 4px 0;
  padding-left: 18px;
}

.bubble.assistant.markdown-body :deep(.markdown-link) {
  color: #155eef;
  text-decoration: underline;
}

.bubble.assistant.markdown-body :deep(.markdown-heading) {
  margin: 0.4em 0 0.2em;
  font-weight: 700;
}

.bubble.assistant.markdown-body :deep(.md-think) {
  margin: 6px 0;
  font-size: 12px;
}

.bubble.assistant.markdown-body :deep(.md-think-summary) {
  cursor: pointer;
  list-style: none;
  font-weight: 700;
  color: #667085;
  user-select: none;
}

.bubble.assistant.markdown-body :deep(.md-think-summary)::-webkit-details-marker {
  display: none;
}

.bubble.assistant.markdown-body :deep(.md-think-body) {
  margin: 6px 0 0 8px;
  padding: 8px 10px;
  border-left: 2px solid #d0d5dd;
  background: #f8fafc;
  color: #475467;
}

.bubble.opening {
  background: #eff4ff;
  color: #101828;
}

.bubble-actions {
  display: flex;
  margin-top: 8px;
}

.tts-btn {
  padding: 3px 8px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  background: #fff;
  color: #344054;
  font-size: 11px;
  cursor: pointer;
}

.tts-btn:hover:not(:disabled) {
  border-color: #84adff;
  color: #0033ff;
}

.tts-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 4px 0 12px;
}

.suggestions.after-answer {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #eaecf0;
}

.suggestion-chip {
  max-width: 100%;
  padding: 6px 10px;
  border: 1px solid #d0d5dd;
  border-radius: 999px;
  background: #fff;
  color: #344054;
  font-size: 11px;
  line-height: 1.3;
  text-align: left;
  cursor: pointer;
}

.suggestion-chip:hover:not(:disabled) {
  border-color: #84adff;
  background: #eff4ff;
  color: #0033ff;
}

.suggestion-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.waiting {
  color: #98a2b3;
}

.error-text {
  color: #b42318;
}

.validation-error {
  margin: 0 14px 8px;
  padding: 6px 8px;
  border-radius: 7px;
  background: #fef3f2;
  color: #b42318;
  font-size: 11px;
}

.composer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border-top: 1px solid #f2f4f7;
  background: #fff;
}

.composer textarea {
  resize: vertical;
  min-height: 56px;
}

.remote-row {
  display: flex;
  gap: 6px;
}

.remote-row input {
  flex: 1;
  min-width: 0;
  padding: 7px 9px;
  border: 1px solid #d0d5dd;
  border-radius: 7px;
  font: inherit;
  font-size: 12px;
}

.remote-btn {
  flex-shrink: 0;
  padding: 7px 10px;
  border: 0;
  border-radius: 7px;
  background: #f2f4f7;
  color: #344054;
  font-size: 12px;
  cursor: pointer;
}

.remote-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.composer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  align-items: center;
}

.composer-actions button {
  padding: 7px 12px;
  border: 0;
  border-radius: 7px;
  background: #f2f4f7;
  color: #344054;
  font-size: 12px;
  cursor: pointer;
}

.composer-actions .primary {
  background: #0033ff;
  color: #fff;
}

.composer-actions .primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.composer-actions .stop {
  border: 1px solid #fda29b;
  background: #fff;
  color: #b42318;
}

.composer-actions .attach {
  margin-right: auto;
}

.composer-actions .stt.recording {
  background: #fef3f2;
  color: #b42318;
}

.stt-error {
  margin: 0;
  color: #b42318;
  font-size: 11px;
}

.composer-actions .ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.hidden-file {
  display: none;
}

.pending-files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.pending-file {
  display: flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 4px 6px 4px 8px;
  border: 1px solid #d0d5dd;
  border-radius: 999px;
  background: #f9fafb;
  font-size: 11px;
  color: #344054;
}

.pending-file.uploading {
  opacity: 0.7;
}

.pending-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}

.pending-file .ghost.danger {
  padding: 0 4px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #b42318;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}
</style>
