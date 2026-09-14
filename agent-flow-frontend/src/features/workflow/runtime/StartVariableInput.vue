<template>
  <input
    v-if="normalizedType === 'text-input' || normalizedType === 'url'"
    :value="modelValue ?? ''"
    type="text"
    :name="variable.variable"
    :disabled="disabled"
    :placeholder="variable.variable"
    @input="$emit('update:modelValue', $event.target.value)"
  >
  <input
    v-else-if="normalizedType === 'number'"
    :value="modelValue ?? ''"
    type="number"
    :name="variable.variable"
    :disabled="disabled"
    :placeholder="variable.variable"
    @input="$emit('update:modelValue', $event.target.value)"
  >
  <textarea
    v-else-if="normalizedType === 'paragraph' || normalizedType === 'json_object'"
    :value="modelValue ?? ''"
    rows="3"
    :name="variable.variable"
    :disabled="disabled"
    :placeholder="variable.variable"
    @input="$emit('update:modelValue', $event.target.value)"
  />
  <label v-else-if="normalizedType === 'checkbox'" class="checkbox-field">
    <input
      type="checkbox"
      :name="variable.variable"
      :checked="Boolean(modelValue)"
      :disabled="disabled"
      @change="$emit('update:modelValue', $event.target.checked)"
    >
    <span>启用</span>
  </label>
  <select
    v-else-if="normalizedType === 'select'"
    :value="modelValue ?? ''"
    :name="variable.variable"
    :disabled="disabled"
    @change="$emit('update:modelValue', $event.target.value)"
  >
    <option value="">请选择</option>
    <option v-for="option in variable.options || []" :key="option" :value="option">{{ option }}</option>
  </select>
  <div v-else-if="isFile" class="file-field">
    <div
      v-if="allowsLocalHumanInputUpload(fileVariable)"
      class="upload-card"
      :class="{ 'is-disabled': disabled || uploading }"
    >
      <input
        ref="fileInputRef"
        class="visually-hidden"
        type="file"
        :multiple="isMultiFile"
        :accept="acceptAttr"
        :disabled="disabled || uploading"
        :aria-label="isMultiFile ? '选择多个文件' : '选择文件'"
        @change="onFilePick"
      >
      <span class="upload-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none">
          <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14.5v3A2.5 2.5 0 0 0 7.5 20h9a2.5 2.5 0 0 0 2.5-2.5v-3" />
        </svg>
      </span>
      <div class="upload-copy">
        <strong>{{ uploading ? '正在上传…' : '上传文件' }}</strong>
        <span>{{ localUploadHint }}</span>
      </div>
      <button
        type="button"
        class="choose-file-button"
        :disabled="disabled || uploading"
        @click="openFilePicker"
      >
        选择文件
      </button>
    </div>
    <div
      v-if="allowsLocalHumanInputUpload(fileVariable) && allowsRemoteHumanInputUpload(fileVariable)"
      class="upload-divider"
      aria-hidden="true"
    >
      <span>或</span>
    </div>
    <div v-if="allowsRemoteHumanInputUpload(fileVariable)" class="remote-upload">
      <span class="link-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none">
          <path d="M10 13a5 5 0 0 0 7.54.54l2-2a5 5 0 0 0-7.07-7.07l-1.15 1.15M14 11a5 5 0 0 0-7.54-.54l-2 2a5 5 0 0 0 7.07 7.07l1.14-1.14" />
        </svg>
      </span>
      <input
        v-model="remoteUrl"
        type="url"
        :disabled="disabled || uploading"
        placeholder="输入文件 URL"
      >
      <button
        type="button"
        class="add-link-button"
        :disabled="disabled || uploading || !remoteUrl.trim()"
        @click="onRemoteAdd"
      >
        添加
      </button>
    </div>
    <ul v-if="fileList.length" class="file-chips">
      <li v-for="file in fileList" :key="file.id" class="file-item">
        <span class="file-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none">
            <path d="M7 3.75h6.5L18 8.25v12H7v-16.5Z" />
            <path d="M13 3.75v5h5" />
          </svg>
        </span>
        <span class="file-info">
          <strong :title="file.name">{{ file.name }}</strong>
          <span class="file-status" :data-state="fileStatus(file)">{{ fileStatus(file) }}</span>
        </span>
        <button
          type="button"
          class="remove-file-button"
          :disabled="disabled || uploading"
          :aria-label="`移除 ${file.name}`"
          @click="removeFile(file.id)"
        >
          ×
        </button>
      </li>
    </ul>
  </div>
  <input
    v-else
    :value="modelValue ?? ''"
    type="text"
    :name="variable.variable"
    :disabled="disabled"
    :placeholder="variable.variable"
    @input="$emit('update:modelValue', $event.target.value)"
  >
  <p v-if="errorMessage" class="file-error" role="alert">{{ errorMessage }}</p>
</template>

<script setup>
import { computed, ref } from 'vue'
import { uploadConsoleFile, uploadRemoteFileInfo } from '@/shared/media/difyFilesApi.js'
import {
  allowsLocalHumanInputUpload,
  allowsRemoteHumanInputUpload,
  createLocalHumanInputFileEntity,
  createRemoteHumanInputFileEntity,
  getHumanInputFileNumberLimit,
  isHumanInputFileUploaded,
  isValidRemoteFileUrl,
  markHumanInputFileUploaded,
} from './humanInputFormUtils.js'
import { normalizeStartVariableType } from './startVariableUtils.js'

const props = defineProps({
  variable: { type: Object, required: true },
  modelValue: { type: [String, Number, Boolean, Object, Array], default: null },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'uploading'])
const uploading = ref(false)
const remoteUrl = ref('')
const errorMessage = ref('')
const fileInputRef = ref(null)

const normalizedType = computed(() => normalizeStartVariableType(props.variable.type))
const isFile = computed(() => normalizedType.value === 'file' || normalizedType.value === 'file-list')
const isMultiFile = computed(() => normalizedType.value === 'file-list')
const fileVariable = computed(() => ({
  ...props.variable,
  type: normalizedType.value,
  number_limits: props.variable.number_limits || props.variable.max_length,
}))
const fileList = computed(() => {
  if (isMultiFile.value)
    return Array.isArray(props.modelValue) ? props.modelValue : []
  return props.modelValue && typeof props.modelValue === 'object' ? [props.modelValue] : []
})
const acceptAttr = computed(() => {
  const extensions = Array.isArray(props.variable.allowed_file_extensions)
    ? props.variable.allowed_file_extensions.filter(Boolean)
    : []
  return extensions.length
    ? extensions.map(ext => String(ext).startsWith('.') ? ext : `.${ext}`).join(',')
    : undefined
})
const localUploadHint = computed(() => {
  const limit = getHumanInputFileNumberLimit(fileVariable.value)
  return isMultiFile.value ? `支持本地上传，最多 ${limit} 个文件` : '支持本地上传，单个文件'
})

function openFilePicker() {
  if (!props.disabled && !uploading.value)
    fileInputRef.value?.click()
}

function setUploading(value) {
  uploading.value = value
  emit('uploading', { variable: props.variable.variable, uploading: value })
}

function setValue(files) {
  emit('update:modelValue', isMultiFile.value ? files : (files[0] || null))
}

function fileStatus(file) {
  if (isHumanInputFileUploaded(file)) return '已上传'
  if (file?.progress === -1) return '失败'
  return '上传中'
}

function removeFile(id) {
  setValue(fileList.value.filter(file => file.id !== id))
}

async function onFilePick(event) {
  const input = event?.target
  const picked = Array.from(input?.files || [])
  if (input) input.value = ''
  if (!picked.length) return
  if (!allowsLocalHumanInputUpload(fileVariable.value)) {
    errorMessage.value = '该变量不允许本地上传'
    return
  }

  const limit = getHumanInputFileNumberLimit(fileVariable.value)
  const existing = fileList.value
  const room = Math.max(0, limit - existing.length)
  const toUpload = isMultiFile.value ? picked.slice(0, room) : picked.slice(0, 1)
  if (!toUpload.length) {
    errorMessage.value = `最多上传 ${limit} 个文件`
    return
  }

  errorMessage.value = ''
  setUploading(true)
  try {
    let next = isMultiFile.value ? [...existing] : []
    for (const file of toUpload) {
      let entity = createLocalHumanInputFileEntity(file)
      next = isMultiFile.value ? [...next, entity] : [entity]
      setValue(next)
      try {
        entity = markHumanInputFileUploaded(entity, await uploadConsoleFile(file))
      }
      catch (error) {
        errorMessage.value = error?.message || '文件上传失败'
        next = next.filter(item => item.id !== entity.id)
        setValue(next)
        continue
      }
      next = next.map(item => item.id === entity.id ? entity : item)
      setValue(next)
    }
  }
  finally {
    setUploading(false)
  }
}

async function onRemoteAdd() {
  const url = remoteUrl.value.trim()
  if (!isValidRemoteFileUrl(url)) {
    errorMessage.value = '请输入有效的 http(s) 文件链接'
    return
  }
  if (!allowsRemoteHumanInputUpload(fileVariable.value)) {
    errorMessage.value = '该变量不允许远程链接'
    return
  }
  const limit = getHumanInputFileNumberLimit(fileVariable.value)
  if (fileList.value.length >= limit) {
    errorMessage.value = `最多上传 ${limit} 个文件`
    return
  }

  errorMessage.value = ''
  setUploading(true)
  let entity = createRemoteHumanInputFileEntity(url)
  const next = isMultiFile.value ? [...fileList.value, entity] : [entity]
  setValue(next)
  try {
    entity = markHumanInputFileUploaded(entity, await uploadRemoteFileInfo(url))
    setValue(isMultiFile.value
      ? next.map(item => item.id === entity.id ? entity : item)
      : [entity])
    remoteUrl.value = ''
  }
  catch (error) {
    errorMessage.value = error?.message || '远程文件获取失败'
    setValue(fileList.value.filter(item => item.id !== entity.id))
  }
  finally {
    setUploading(false)
  }
}
</script>

<style scoped>
.file-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.upload-card {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 68px;
  padding: 12px;
  border: 1px dashed #b9c2d0;
  border-radius: 10px;
  background: #f9fafb;
  transition: border-color 160ms ease, background 160ms ease, box-shadow 160ms ease;
}

.upload-card:hover {
  border-color: #8098f9;
  background: #f5f7ff;
  box-shadow: 0 0 0 3px rgb(53 86 255 / 6%);
}

.upload-card.is-disabled {
  opacity: 0.62;
}

.upload-icon,
.file-icon {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1px solid #d9e0ff;
  border-radius: 9px;
  background: #eef2ff;
  color: #335cff;
}

.upload-icon svg,
.file-icon svg,
.link-icon svg {
  width: 18px;
  height: 18px;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.upload-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.upload-copy strong {
  color: #344054;
  font-size: 12px;
  font-weight: 600;
}

.upload-copy span {
  color: #98a2b3;
  font-size: 11px;
  line-height: 16px;
}

.choose-file-button,
.add-link-button,
.remove-file-button {
  border: 0;
  font: inherit;
  cursor: pointer;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease;
}

.choose-file-button {
  flex: 0 0 auto;
  padding: 7px 10px;
  border-radius: 7px;
  background: #3157f6;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  box-shadow: 0 1px 2px rgb(16 24 40 / 10%);
}

.choose-file-button:hover:not(:disabled) {
  background: #2447db;
}

.upload-divider {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #98a2b3;
  font-size: 10px;
}

.upload-divider::before,
.upload-divider::after {
  height: 1px;
  flex: 1;
  background: #eaecf0;
  content: '';
}

.remote-upload {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 4px 4px 4px 9px;
  border: 1px solid #d0d5dd;
  border-radius: 9px;
  background: #fff;
  box-shadow: 0 1px 2px rgb(16 24 40 / 4%);
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.remote-upload:focus-within {
  border-color: #8098f9;
  box-shadow: 0 0 0 3px rgb(53 86 255 / 8%);
}

.link-icon {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  color: #667085;
}

.remote-upload input {
  min-width: 0;
  height: 30px;
  flex: 1;
  padding: 0;
  border: 0;
  outline: none;
  background: transparent;
  color: #344054;
  font: inherit;
  font-size: 12px;
}

.remote-upload input::placeholder {
  color: #98a2b3;
}

.add-link-button {
  min-width: 48px;
  padding: 7px 9px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  background: #fff;
  color: #344054;
  font-size: 11px;
  font-weight: 600;
}

.add-link-button:hover:not(:disabled) {
  border-color: #8098f9;
  color: #3157f6;
}

.file-chips {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 9px;
  border: 1px solid #e4e7ec;
  border-radius: 9px;
  background: #fff;
  box-shadow: 0 1px 2px rgb(16 24 40 / 3%);
}

.file-icon {
  width: 30px;
  height: 30px;
  border-color: #e4e7ec;
  background: #f9fafb;
  color: #667085;
}

.file-info {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 1px;
}

.file-info strong {
  overflow: hidden;
  color: #344054;
  font-size: 11px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-status {
  color: #667085;
  font-size: 10px;
}

.file-status[data-state='已上传'] {
  color: #039855;
}

.remove-file-button {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: transparent;
  color: #98a2b3;
  font-size: 18px;
  line-height: 1;
}

.remove-file-button:hover:not(:disabled) {
  background: #f2f4f7;
  color: #344054;
}

.choose-file-button:disabled,
.add-link-button:disabled,
.remove-file-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  border: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.file-error {
  margin: 0;
  color: #d92d20;
  font-size: 11px;
}

.checkbox-field {
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
