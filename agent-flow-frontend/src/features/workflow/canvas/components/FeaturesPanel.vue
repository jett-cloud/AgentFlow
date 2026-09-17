<template>
  <!-- Contrasts Dify NewFeaturePanel conversation-opener + follow-up settings. -->
  <aside class="features-panel" aria-label="功能">
    <header>
      <div>
        <h2>功能</h2>
        <p>对话开场白、建议问题、引用与文件上传（Chatflow）</p>
      </div>
      <button type="button" aria-label="关闭功能面板" @click="$emit('close')">×</button>
    </header>

    <div class="body">
      <label class="toggle-row">
        <input v-model="enabled" type="checkbox" :disabled="readOnly" />
        <span>对话开场白</span>
      </label>

      <template v-if="enabled">
        <label class="field">
          <span>开场白</span>
          <textarea
            v-model="openingStatement"
            rows="4"
            :disabled="readOnly"
            placeholder="例如：你好，我是助手，有什么可以帮你？"
          />
        </label>

        <div class="field">
          <div class="field-head">
            <span>建议问题</span>
            <button type="button" class="ghost" :disabled="readOnly" @click="addQuestion">
              添加
            </button>
          </div>
          <div
            v-for="(question, index) in suggestedQuestions"
            :key="index"
            class="question-row"
          >
            <input
              v-model="suggestedQuestions[index]"
              type="text"
              :disabled="readOnly"
              :placeholder="`问题 ${index + 1}`"
            />
            <button
              type="button"
              class="ghost danger"
              :disabled="readOnly"
              aria-label="删除建议问题"
              @click="removeQuestion(index)"
            >
              ×
            </button>
          </div>
          <p v-if="!suggestedQuestions.length" class="hint">可添加点击即发送的建议问题。</p>
        </div>
      </template>
      <p v-else class="hint">开启后，调试预览空会话会显示开场白与建议问题。</p>

      <label class="toggle-row follow-up">
        <input v-model="followUpEnabled" type="checkbox" :disabled="readOnly" />
        <span>回答后建议问题</span>
      </label>
      <p class="hint">开启后，每轮助手回复结束会请求并展示下一轮建议问题。</p>
      <div v-if="followUpEnabled" class="follow-up-summary">
        <span>模型：{{ followUpSummary }}</span>
        <button type="button" class="ghost" :disabled="readOnly" @click="showFollowUpModal = true">
          设置
        </button>
      </div>

      <label class="toggle-row follow-up">
        <input v-model="citationEnabled" type="checkbox" :disabled="readOnly" />
        <span>引用与归属</span>
      </label>
      <p class="hint">开启后，知识检索命中会在助手回复下方展示引用来源。</p>

      <label class="toggle-row follow-up">
        <input v-model="fileUploadEnabled" type="checkbox" :disabled="readOnly" />
        <span>文件上传</span>
      </label>
      <p class="hint">开启后，调试对话可按设置上传附件或粘贴链接。</p>
      <div v-if="fileUploadEnabled" class="follow-up-summary">
        <span>{{ fileUploadSummary }}</span>
        <button type="button" class="ghost" :disabled="readOnly" @click="showFileUploadModal = true">
          设置
        </button>
      </div>

      <label class="toggle-row follow-up">
        <input v-model="textToSpeechEnabled" type="checkbox" :disabled="readOnly" />
        <span>文字转语音</span>
      </label>
      <p class="hint">开启后，助手回复下方可点击播放语音。</p>
      <div v-if="textToSpeechEnabled" class="tts-fields">
        <label class="field">
          <span>语言代码</span>
          <input v-model="textToSpeechLanguage" type="text" :disabled="readOnly" placeholder="例如 zh-Hans" />
        </label>
        <label class="field">
          <span>音色 voice</span>
          <input v-model="textToSpeechVoice" type="text" :disabled="readOnly" placeholder="留空使用默认音色" />
        </label>
        <label class="toggle-row">
          <input v-model="textToSpeechAutoPlay" type="checkbox" :disabled="readOnly" />
          <span>自动播放（配置写入草稿；流式自动播后续接入）</span>
        </label>
      </div>

      <label class="toggle-row follow-up">
        <input v-model="speechToTextEnabled" type="checkbox" :disabled="readOnly" />
        <span>语音转文字</span>
      </label>
      <p class="hint">开启后，调试输入框显示麦克风按钮，录音后自动转写为文字。</p>

      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <div class="footer">
        <button type="button" class="primary" :disabled="readOnly || saving" @click="handleSave">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>

    <FollowUpSettingModal
      v-if="showFollowUpModal"
      :model-value="followUpModel"
      :prompt-value="followUpPrompt"
      :read-only="readOnly"
      @cancel="showFollowUpModal = false"
      @save="onFollowUpSettingsSave"
    />
    <FileUploadSettingModal
      v-if="showFileUploadModal"
      :types="fileUploadTypes"
      :methods="fileUploadMethods"
      :number-limits="fileUploadNumberLimits"
      :read-only="readOnly"
      @cancel="showFileUploadModal = false"
      @save="onFileUploadSettingsSave"
    />
  </aside>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import FollowUpSettingModal from './FollowUpSettingModal.vue'
import FileUploadSettingModal from './FileUploadSettingModal.vue'
import {
  buildOpeningFeaturesPayload,
  featuresToOpeningForm,
  getFileUploadSummary,
  getFollowUpModelSummary,
} from '../../model/workflowFeatures.js'

const props = defineProps({
  features: { type: Object, default: () => ({}) },
  readOnly: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const emit = defineEmits(['close', 'save'])

const enabled = ref(false)
const openingStatement = ref('')
const suggestedQuestions = ref([])
const followUpEnabled = ref(false)
const followUpModel = ref(null)
const followUpPrompt = ref('')
const citationEnabled = ref(true)
const fileUploadEnabled = ref(false)
const fileUploadTypes = ref(['image'])
const fileUploadMethods = ref(['local_file', 'remote_url'])
const fileUploadNumberLimits = ref(3)
const textToSpeechEnabled = ref(false)
const textToSpeechLanguage = ref('')
const textToSpeechVoice = ref('')
const textToSpeechAutoPlay = ref(false)
const speechToTextEnabled = ref(false)
const showFollowUpModal = ref(false)
const showFileUploadModal = ref(false)

const followUpSummary = computed(() => getFollowUpModelSummary({
  model: followUpModel.value,
}))
const fileUploadSummary = computed(() => getFileUploadSummary({
  enabled: true,
  allowed_file_types: fileUploadTypes.value,
  allowed_file_upload_methods: fileUploadMethods.value,
  number_limits: fileUploadNumberLimits.value,
}))

function syncFromProps() {
  const form = featuresToOpeningForm(props.features)
  enabled.value = form.enabled
  openingStatement.value = form.openingStatement
  suggestedQuestions.value = form.suggestedQuestions.length
    ? [...form.suggestedQuestions]
    : (form.enabled ? [''] : [])
  followUpEnabled.value = form.followUpEnabled
  followUpModel.value = form.followUpModel
  followUpPrompt.value = form.followUpPrompt
  citationEnabled.value = form.citationEnabled
  fileUploadEnabled.value = form.fileUploadEnabled
  fileUploadTypes.value = [...form.fileUploadTypes]
  fileUploadMethods.value = [...form.fileUploadMethods]
  fileUploadNumberLimits.value = form.fileUploadNumberLimits
  textToSpeechEnabled.value = form.textToSpeechEnabled
  textToSpeechLanguage.value = form.textToSpeechLanguage || ''
  textToSpeechVoice.value = form.textToSpeechVoice || ''
  textToSpeechAutoPlay.value = Boolean(form.textToSpeechAutoPlay)
  speechToTextEnabled.value = form.speechToTextEnabled
}

watch(() => props.features, syncFromProps, { immediate: true, deep: true })

function addQuestion() {
  suggestedQuestions.value.push('')
}

function removeQuestion(index) {
  suggestedQuestions.value.splice(index, 1)
}

function onFollowUpSettingsSave({ model, prompt }) {
  followUpModel.value = model
  followUpPrompt.value = prompt || ''
  followUpEnabled.value = true
  showFollowUpModal.value = false
}

function onFileUploadSettingsSave({ types, methods, numberLimits }) {
  fileUploadTypes.value = [...types]
  fileUploadMethods.value = [...methods]
  fileUploadNumberLimits.value = numberLimits
  fileUploadEnabled.value = true
  showFileUploadModal.value = false
}

function handleSave() {
  emit('save', buildOpeningFeaturesPayload({
    enabled: enabled.value,
    openingStatement: openingStatement.value,
    suggestedQuestions: suggestedQuestions.value,
    followUpEnabled: followUpEnabled.value,
    followUpModel: followUpModel.value,
    followUpPrompt: followUpPrompt.value,
    citationEnabled: citationEnabled.value,
    fileUploadEnabled: fileUploadEnabled.value,
    fileUploadTypes: fileUploadTypes.value,
    fileUploadMethods: fileUploadMethods.value,
    fileUploadNumberLimits: fileUploadNumberLimits.value,
    textToSpeechEnabled: textToSpeechEnabled.value,
    textToSpeechLanguage: textToSpeechLanguage.value,
    textToSpeechVoice: textToSpeechVoice.value,
    textToSpeechAutoPlay: textToSpeechAutoPlay.value,
    speechToTextEnabled: speechToTextEnabled.value,
  }, props.features))
}
</script>

<style scoped>
.features-panel {
  position: absolute;
  top: 56px;
  right: 12px;
  z-index: 55;
  display: flex;
  width: min(360px, calc(100% - 24px));
  max-height: calc(100% - 72px);
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 12px 32px rgb(16 24 40 / 12%);
}

header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid #f2f4f7;
}

header h2,
header p {
  margin: 0;
}

header h2 {
  color: #101828;
  font-size: 14px;
}

header p {
  margin-top: 2px;
  color: #667085;
  font-size: 11px;
}

header button {
  padding: 2px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #667085;
  font-size: 18px;
  cursor: pointer;
}

.body {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  gap: 12px;
  overflow: auto;
  padding: 12px 14px 14px;
}

.toggle-row {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #101828;
  font-size: 13px;
  font-weight: 600;
}

.toggle-row.follow-up {
  margin-top: 4px;
  padding-top: 10px;
  border-top: 1px solid #f2f4f7;
}

.follow-up-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid #eaecf0;
  border-radius: 8px;
  background: #f9fafb;
  color: #344054;
  font-size: 12px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #344054;
  font-size: 12px;
}

.field-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.field textarea,
.field input,
.question-row input {
  padding: 7px 9px;
  border: 1px solid #d0d5dd;
  border-radius: 7px;
  font: inherit;
}

.tts-fields {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
  border: 1px solid #eaecf0;
  border-radius: 8px;
  background: #f9fafb;
}

.question-row {
  display: flex;
  gap: 6px;
}

.question-row input {
  flex: 1;
}

.ghost {
  padding: 4px 8px;
  border: 0;
  border-radius: 6px;
  background: #f2f4f7;
  color: #344054;
  font-size: 12px;
  cursor: pointer;
}

.ghost.danger {
  background: transparent;
  color: #b42318;
}

.hint {
  margin: 0;
  color: #98a2b3;
  font-size: 11px;
  line-height: 1.4;
}

.error {
  margin: 0;
  padding: 6px 8px;
  border-radius: 7px;
  background: #fef3f2;
  color: #b42318;
  font-size: 11px;
}

.footer {
  display: flex;
  justify-content: flex-end;
}

.primary {
  padding: 7px 14px;
  border: 0;
  border-radius: 7px;
  background: #0033ff;
  color: #fff;
  font-size: 12px;
  cursor: pointer;
}

.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
