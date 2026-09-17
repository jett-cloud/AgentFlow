<template>
  <!-- Contrasts Dify CreateAppDialogShell + create-app-modal (full-bleed dual pane) -->
  <el-dialog
    :model-value="modelValue"
    fullscreen
    append-to-body
    destroy-on-close
    :show-close="false"
    class="create-app-shell"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div class="create-shell">
      <button type="button" class="close-btn" aria-label="关闭" @click="close">✕</button>

      <div class="create-layout">
        <section class="create-form-pane">
          <div class="form-spacer" />
          <h2 class="form-title">创建空白应用</h2>

          <p class="section-label">选择应用类型</p>
          <div class="type-row">
            <button
              v-for="item in primaryTypes"
              :key="item.mode"
              type="button"
              class="type-card"
              :class="{ active: mode === item.mode }"
              @click="mode = item.mode"
            >
              <span class="type-icon" :data-tone="item.tone">{{ item.glyph }}</span>
              <strong>{{ item.title }}</strong>
              <span>{{ item.short }}</span>
            </button>
          </div>

          <div class="divider" />

          <div class="name-row">
            <label class="field grow">
              <span>应用名称</span>
              <el-input
                v-model="name"
                maxlength="40"
                show-word-limit
                placeholder="给你的应用起个名字"
                @keydown.ctrl.enter.prevent="submit"
                @keydown.meta.enter.prevent="submit"
              />
            </label>
            <div class="icon-picker-wrap">
              <button
                type="button"
                class="icon-btn"
                :class="{ 'has-image': uploadedIcon }"
                title="上传应用图片"
                @click="imageFileInput?.click()"
              >
                <img v-if="uploadedIcon" :src="uploadedIcon.url" alt="" class="uploaded-icon-preview" />
                <template v-else>{{ fallbackIcon }}</template>
              </button>
              <span class="icon-upload-hint">{{ iconUploading ? '上传中…' : '上传图片' }}</span>
              <input
                ref="imageFileInput"
                class="visually-hidden"
                type="file"
                accept="image/png,image/jpeg,image/webp,image/svg+xml,.svg"
                @change="onImageFilePicked"
              />
            </div>
          </div>

          <label class="field">
            <span>描述 <small>（可选）</small></span>
            <el-input
              v-model="description"
              type="textarea"
              :rows="3"
              resize="none"
              placeholder="输入应用的描述"
            />
          </label>

          <footer class="form-footer">
            <button type="button" class="template-link" @click="onTemplateClick">
              没有想法？试试我们的模板 <span>→</span>
            </button>
            <div class="footer-actions">
              <el-button @click="close">取消</el-button>
              <el-button
                type="primary"
                :loading="loading"
                :disabled="!canSubmit"
                @click="submit"
              >
                创建
                <kbd class="hotkey">Ctrl ↵</kbd>
              </el-button>
            </div>
          </footer>
        </section>

        <section class="create-preview-pane" aria-label="应用预览">
          <div class="preview-spacer" />
          <div class="preview-copy">
            <h3>{{ previewMeta.title }}</h3>
            <p>{{ previewMeta.description }}</p>
          </div>
          <div class="preview-stage">
            <div class="preview-mock" :data-mode="mode">
              <div class="mock-chrome">
                <span /><span /><span />
              </div>
              <div class="mock-body">
                <div class="mock-nodes">
                  <div class="mock-node">START</div>
                  <div class="mock-line" />
                  <div class="mock-node accent">LLM</div>
                  <div class="mock-line" />
                  <div class="mock-node">{{ isChatflow ? 'ANSWER' : 'END' }}</div>
                </div>
                <div v-if="isChatflow" class="mock-chat">
                  <div class="mock-bubble user">今天天气怎么样？</div>
                  <div class="mock-bubble bot">今天晴，气温 24°C。</div>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  </el-dialog>

  <ImageCropDialog
    v-model="cropDialogOpen"
    :file="cropFile"
    @cancel="cropFile = null"
    @confirm="onCropConfirmed"
  />
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { AppMode, isChatflowMode } from '../model/appModes.js'
import { validateAppIconFile } from '../model/svgAppIcon.js'
import { uploadConsoleFile } from '@/shared/media/difyFilesApi.js'
import ImageCropDialog from './ImageCropDialog.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  defaultMode: { type: String, default: AppMode.ADVANCED_CHAT },
})

const emit = defineEmits(['update:modelValue', 'create'])

const mode = ref(props.defaultMode)
const name = ref('')
const description = ref('')
const iconUploading = ref(false)
const imageFileInput = ref(null)
const uploadedIcon = ref(null)
const cropDialogOpen = ref(false)
const cropFile = ref(null)

const primaryTypes = [
  {
    mode: AppMode.WORKFLOW,
    title: '工作流',
    short: '面向单轮自动化任务的编排工作流',
    glyph: 'W',
    tone: 'indigo',
  },
  {
    mode: AppMode.ADVANCED_CHAT,
    title: 'Chatflow',
    short: '支持记忆的复杂多轮对话工作流',
    glyph: 'C',
    tone: 'blue',
  },
]

const beginnerTypes = [
  {
    mode: 'chat',
    title: '聊天助手',
    short: '简单配置即可构建基于 LLM 的对话机器人',
    glyph: '🤖',
    tone: 'sky',
  },
  {
    mode: 'agent-chat',
    title: 'Agent',
    short: '具备推理与自主工具调用的智能助手',
    glyph: '⚡',
    tone: 'violet',
  },
  {
    mode: 'completion',
    title: '文本生成应用',
    short: '用于文本生成任务的 AI 助手',
    glyph: '✦',
    tone: 'teal',
  },
]

const previewByMode = {
  [AppMode.WORKFLOW]: {
    title: '工作流',
    description: '基于工作流编排，适用于自动化、批处理等单轮生成类任务的场景。',
  },
  [AppMode.ADVANCED_CHAT]: {
    title: 'CHATFLOW',
    description: '基于工作流编排，适用于定义等复杂流程的多轮对话场景，具有记忆功能。',
  },
}

const isChatflow = computed(() => isChatflowMode(mode.value))
const previewMeta = computed(() => previewByMode[mode.value] || previewByMode[AppMode.WORKFLOW])
const canSubmit = computed(() => !!name.value.trim() && !props.loading)
const fallbackIcon = computed(() => name.value.trim().slice(0, 1).toUpperCase() || 'A')
const iconSelection = computed(() => uploadedIcon.value
  ? { type: 'image', icon: uploadedIcon.value.fileId }
  : { type: 'emoji', icon: fallbackIcon.value, background: '#5368A9' })

watch(() => props.modelValue, (open) => {
  if (!open)
    return
  mode.value = props.defaultMode || AppMode.ADVANCED_CHAT
  name.value = ''
  description.value = ''
  clearUploadedIcon()
  iconUploading.value = false
  cropDialogOpen.value = false
  cropFile.value = null
})

function close() {
  emit('update:modelValue', false)
}

function onImageFilePicked(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file)
    return

  try {
    validateAppIconFile(file)
    cropFile.value = file
    cropDialogOpen.value = true
  }
  catch (error) {
    ElMessage.error(error.message || '无法选择这张图片')
  }
}

async function onCropConfirmed(pngFile) {
  iconUploading.value = true
  try {
    const uploaded = await uploadConsoleFile(pngFile, { source: 'app-icon' })
    const fileId = uploaded?.id || uploaded?.upload_file_id
    if (!fileId)
      throw new Error('图标上传结果缺少文件 ID')
    clearUploadedIcon()
    uploadedIcon.value = { fileId, url: URL.createObjectURL(pngFile) }
    cropDialogOpen.value = false
    cropFile.value = null
  }
  catch (error) {
    ElMessage.error(error.response?.data?.message || error.message || 'SVG 图标上传失败')
  }
  finally {
    iconUploading.value = false
  }
}

function onTemplateClick() {
  ElMessage.info('模板市场即将支持，可先从空白创建或导入 DSL')
}

function submit() {
  if (!canSubmit.value)
    return
  emit('create', {
    name: name.value.trim(),
    mode: mode.value,
    description: description.value.trim(),
    icon: iconSelection.value.icon,
    icon_type: iconSelection.value.type,
    icon_background: iconSelection.value.type === 'emoji' ? iconSelection.value.background : undefined,
  })
}

function clearUploadedIcon() {
  if (uploadedIcon.value?.url)
    URL.revokeObjectURL(uploadedIcon.value.url)
  uploadedIcon.value = null
}

onBeforeUnmount(() => {
  clearUploadedIcon()
})
</script>

<style scoped>
.create-shell {
  position: relative;
  height: calc(100vh - 32px);
  margin: 16px;
  overflow: hidden;
  border: 1px solid var(--af-border);
  border-radius: 16px;
  background: #f9fafb;
}
.close-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 5;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 10px;
  background: #f2f4f7;
  color: #344054;
  cursor: pointer;
}
.create-layout {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(420px, 1fr);
  height: 100%;
}
.create-form-pane {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 0 40px 40px;
  overflow: auto;
}
.form-spacer,
.preview-spacer {
  height: 48px;
  flex-shrink: 0;
}
.form-title {
  margin: 0 0 8px;
  color: #101828;
  font-size: 28px;
  font-weight: 700;
}
.section-label {
  margin: 0;
  color: #344054;
  font-size: 13px;
  font-weight: 600;
}
.type-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.type-card {
  box-sizing: border-box;
  width: 200px;
  min-height: 96px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  box-shadow: 0 1px 2px rgb(16 24 40 / 4%);
}
.type-card strong {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #344054;
  font-size: 13px;
}
.type-card span:last-child {
  color: #667085;
  font-size: 12px;
  line-height: 1.4;
}
.type-card.active {
  outline: 1.5px solid var(--af-brand);
  border-color: transparent;
  box-shadow: 0 4px 12px rgb(21 94 239 / 12%);
}
.type-card.is-disabled {
  opacity: 0.72;
  cursor: not-allowed;
  background: #f9fafb;
}
.type-icon {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: #fff;
  font-size: 12px;
}
.type-icon[data-tone='indigo'] { background: var(--af-brand); }
.type-icon[data-tone='blue'] { background: #397d64; }
.type-icon[data-tone='sky'] { background: #0ba5ec; }
.type-icon[data-tone='violet'] { background: #875bf7; }
.type-icon[data-tone='teal'] { background: #15b79e; }
.soon-badge {
  padding: 1px 6px;
  border-radius: 999px;
  background: #f2f4f7;
  color: #667085;
  font-size: 10px;
  font-style: normal;
  font-weight: 600;
}
.beginner-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  width: fit-content;
  padding: 0;
  border: 0;
  background: transparent;
  color: #98a2b3;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  cursor: pointer;
}
.beginner-toggle span {
  display: inline-block;
  transition: transform 0.15s ease;
}
.beginner-toggle span.open {
  transform: rotate(90deg);
}
.divider {
  height: 1px;
  background: #eaecf0;
}
.name-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #344054;
  font-size: 13px;
  font-weight: 600;
}
.field.grow {
  flex: 1;
  min-width: 0;
}
.field small {
  color: #98a2b3;
  font-weight: 400;
}
.icon-picker-wrap {
  position: relative;
  flex-shrink: 0;
}
.icon-btn {
  width: 64px;
  height: 64px;
  border: 1px dashed var(--af-border-strong);
  border-radius: 16px;
  background: var(--af-brand);
  color: #fff;
  font-size: 22px;
  font-weight: 650;
  cursor: pointer;
  overflow: hidden;
}
.icon-btn:hover { border-color: var(--af-brand); box-shadow: 0 0 0 3px var(--af-focus-ring); }
.icon-btn:focus-visible { outline: 3px solid var(--af-focus-ring); outline-offset: 2px; }
.icon-btn.has-image { border-style: solid; background: #fff; }
.icon-upload-hint { display: block; margin-top: 6px; color: var(--af-text-muted); font-size: 11px; text-align: center; }
.uploaded-icon-preview {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.icon-popover {
  position: absolute;
  right: 0;
  bottom: calc(100% + 8px);
  z-index: 6;
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 6px;
  width: 240px;
  padding: 10px;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 8px 24px rgb(16 24 40 / 12%);
}
.emoji-option {
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 8px;
  background: #f9fafb;
  cursor: pointer;
}
.bg-row {
  grid-column: 1 / -1;
  display: flex;
  gap: 6px;
  margin-top: 4px;
}
.bg-swatch {
  width: 22px;
  height: 22px;
  border: 1px solid #eaecf0;
  border-radius: 999px;
  cursor: pointer;
}
.bg-swatch.active {
  outline: 2px solid #155eef;
}
.upload-divider {
  grid-column: 1 / -1;
  height: 1px;
  margin: 3px 0 1px;
  background: #eaecf0;
}
.svg-upload-button {
  grid-column: 1 / -1;
  height: 34px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #fff;
  color: #344054;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 160ms ease, color 160ms ease, background-color 160ms ease;
}
.svg-upload-button:hover:not(:disabled) {
  border-color: #84adff;
  background: #eff4ff;
  color: #155eef;
}
.svg-upload-button:disabled {
  cursor: wait;
  opacity: 0.65;
}
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.form-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: auto;
  padding-top: 12px;
}
.template-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #667085;
  font-size: 12px;
  cursor: pointer;
}
.footer-actions {
  display: flex;
  gap: 8px;
}
.hotkey {
  margin-left: 6px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgb(255 255 255 / 18%);
  font-size: 11px;
}
.create-preview-pane {
  position: relative;
  border-left: 1px solid var(--af-border);
  overflow: hidden;
}
.preview-copy {
  padding: 0 32px 16px;
}
.preview-copy h3 {
  margin: 0;
  color: #344054;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.preview-copy p {
  margin: 8px 0 0;
  max-width: 420px;
  color: #667085;
  font-size: 12px;
  line-height: 1.55;
}
.preview-stage {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 420px;
  margin: 0 24px;
  border-top: 1px solid #eaecf0;
  border-bottom: 1px solid #eaecf0;
  background: repeating-linear-gradient(
    135deg,
    transparent,
    transparent 2px,
    rgba(16, 24, 40, 0.035) 4px,
    transparent 3px,
    transparent 6px
  );
}
.preview-mock {
  width: min(560px, 92%);
  border: 1px solid #eaecf0;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 12px 32px rgb(16 24 40 / 10%);
  overflow: hidden;
}
.mock-chrome {
  display: flex;
  gap: 6px;
  padding: 10px 12px;
  background: #f2f4f7;
  border-bottom: 1px solid #eaecf0;
}
.mock-chrome span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d0d5dd;
}
.mock-body {
  display: flex;
  gap: 16px;
  padding: 20px;
  min-height: 220px;
}
.mock-nodes {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
  flex: 1;
}
.mock-node {
  padding: 8px 14px;
  border: 1px solid #eaecf0;
  border-radius: 8px;
  background: #f9fafb;
  color: #344054;
  font-size: 11px;
  font-weight: 700;
}
.mock-node.accent {
  border-color: var(--af-brand-border);
  background: var(--af-brand-soft);
  color: var(--af-brand-strong);
}
.mock-line {
  width: 2px;
  height: 18px;
  background: #d0d5dd;
}
.mock-chat {
  width: 180px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid #eaecf0;
  border-radius: 10px;
  background: #f8fafc;
}
.mock-bubble {
  max-width: 100%;
  padding: 8px 10px;
  border-radius: 10px;
  font-size: 11px;
  line-height: 1.4;
}
.mock-bubble.user {
  align-self: flex-end;
  background: var(--af-brand);
  color: #fff;
}
.mock-bubble.bot {
  align-self: flex-start;
  background: #fff;
  color: #344054;
  border: 1px solid #eaecf0;
}
@media (max-width: 960px) {
  .create-layout {
    grid-template-columns: 1fr;
  }
  .create-preview-pane {
    display: none;
  }
}
</style>

<style>
/* el-dialog fullscreen chrome reset for create shell */
.create-app-shell.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}
.create-app-shell .el-dialog__header {
  display: none;
}
.create-app-shell .el-dialog__body {
  padding: 0 !important;
  height: 100%;
}
</style>
