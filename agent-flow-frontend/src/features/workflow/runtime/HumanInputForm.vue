<template>
  <form class="human-input-form" @submit.prevent>
    <header v-if="formData.node_title || formData.form_content" class="form-header">
      <strong v-if="formData.node_title">{{ formData.node_title }}</strong>
      <pre v-if="formContentText" class="form-content">{{ formContentText }}</pre>
    </header>

    <label
      v-for="field in fields"
      :key="field.output_variable_name"
      class="field"
    >
      <span>
        {{ fieldLabel(field) }}
        <em v-if="field.required">*</em>
      </span>
      <textarea
        v-if="field.type === 'paragraph' || field.type === 'text'"
        v-model="values[field.output_variable_name]"
        rows="3"
        :disabled="submitting"
        :name="field.output_variable_name"
      />
      <select
        v-else-if="field.type === 'select'"
        v-model="values[field.output_variable_name]"
        :disabled="submitting"
        :name="field.output_variable_name"
      >
        <option value="">请选择</option>
        <option
          v-for="option in getHumanInputSelectOptions(field)"
          :key="option"
          :value="option"
        >
          {{ option }}
        </option>
      </select>
      <div
        v-else-if="field.type === 'file' || field.type === 'file-list'"
        class="file-field"
      >
        <input
          v-if="allowsLocalHumanInputUpload(field)"
          type="file"
          :disabled="submitting || uploading"
          :multiple="field.type === 'file-list'"
          :accept="acceptAttr(field)"
          @change="onFilePick(field, $event)"
        >
        <div v-if="allowsRemoteHumanInputUpload(field)" class="remote-row">
          <input
            v-model="remoteUrls[field.output_variable_name]"
            type="url"
            :disabled="submitting || uploading"
            placeholder="粘贴文件链接 (https://…)"
          >
          <button
            type="button"
            class="remote-btn"
            :disabled="submitting || uploading"
            @click="onRemoteAdd(field)"
          >
            添加链接
          </button>
        </div>
        <ul v-if="fileListFor(field).length" class="file-chips">
          <li v-for="file in fileListFor(field)" :key="file.id">
            <span>{{ file.name }}</span>
            <span class="file-meta">
              {{ fileStatus(file) }}
            </span>
            <button
              type="button"
              class="remove-file"
              :disabled="submitting || uploading"
              @click="removeFile(field, file.id)"
            >
              移除
            </button>
          </li>
        </ul>
      </div>
    </label>

    <p v-if="localError" class="error" role="alert">{{ localError }}</p>

    <div class="actions">
      <button
        v-for="action in actions"
        :key="action.id"
        type="button"
        class="action-btn"
        :class="action.button_style || 'default'"
        :disabled="submitting || uploading || !formData.form_token"
        @click="handleAction(action.id)"
      >
        {{ action.title || action.id }}
      </button>
    </div>
  </form>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { uploadConsoleFile, uploadRemoteFileInfo } from '@/shared/media/difyFilesApi.js'
import {
  allowsLocalHumanInputUpload,
  allowsRemoteHumanInputUpload,
  createLocalHumanInputFileEntity,
  createRemoteHumanInputFileEntity,
  getHumanInputFileNumberLimit,
  getHumanInputSelectOptions,
  getProcessedHumanInputFormInputs,
  getRenderableHumanInputFields,
  initializeHumanInputValues,
  isFileHumanInputField,
  isFileListHumanInputField,
  isHumanInputFileUploaded,
  isValidRemoteFileUrl,
  markHumanInputFileUploaded,
  validateHumanInputValues,
} from './humanInputFormUtils.js'

const props = defineProps({
  formData: { type: Object, required: true },
  submitForm: { type: Function, required: true },
})

const values = reactive({})
const remoteUrls = reactive({})
const submitting = ref(false)
const uploading = ref(false)
const localError = ref('')

const fields = computed(() => getRenderableHumanInputFields(props.formData))
const actions = computed(() => (
  Array.isArray(props.formData?.actions) && props.formData.actions.length
    ? props.formData.actions
    : (Array.isArray(props.formData?.user_actions) ? props.formData.user_actions : [])
))
const formContentText = computed(() => {
  const raw = String(props.formData?.form_content || '').trim()
  if (!raw)
    return ''
  return raw.replace(/\{\{#[^#]+#\}\}/g, '').trim()
})

function syncValues() {
  const next = initializeHumanInputValues(props.formData)
  Object.keys(values).forEach((key) => {
    if (!(key in next))
      delete values[key]
  })
  Object.assign(values, next)
  for (const field of getRenderableHumanInputFields(props.formData)) {
    const name = field.output_variable_name
    if (name && remoteUrls[name] === undefined)
      remoteUrls[name] = ''
  }
}

watch(() => props.formData, syncValues, { immediate: true, deep: true })

function fieldLabel(field) {
  return field.label || field.output_variable_name || '字段'
}

function acceptAttr(field) {
  const exts = Array.isArray(field.allowed_file_extensions)
    ? field.allowed_file_extensions.filter(Boolean)
    : []
  if (exts.length)
    return exts.map(ext => (String(ext).startsWith('.') ? ext : `.${ext}`)).join(',')
  return undefined
}

function fileListFor(field) {
  const name = field.output_variable_name
  const value = values[name]
  if (isFileListHumanInputField(field))
    return Array.isArray(value) ? value : []
  if (value && typeof value === 'object')
    return [value]
  return []
}

function fileStatus(file) {
  if (isHumanInputFileUploaded(file))
    return '已上传'
  if (file.progress === -1)
    return '失败'
  if (file.progress > 0 && file.progress < 100)
    return `上传中 ${file.progress}%`
  return '待上传'
}

function setFieldFiles(field, nextList) {
  const name = field.output_variable_name
  if (isFileListHumanInputField(field))
    values[name] = nextList
  else
    values[name] = nextList[0] || null
}

function removeFile(field, fileId) {
  const next = fileListFor(field).filter(f => f.id !== fileId)
  setFieldFiles(field, next)
}

async function onFilePick(field, event) {
  const input = event?.target
  const picked = Array.from(input?.files || [])
  if (input)
    input.value = ''
  if (!picked.length)
    return
  if (!allowsLocalHumanInputUpload(field)) {
    localError.value = '该字段不允许本地上传'
    return
  }

  localError.value = ''
  const limit = getHumanInputFileNumberLimit(field)
  const existing = fileListFor(field)
  const room = Math.max(0, limit - existing.length)
  const toUpload = isFileHumanInputField(field)
    ? picked.slice(0, 1)
    : picked.slice(0, room)

  if (!toUpload.length) {
    localError.value = `最多上传 ${limit} 个文件`
    return
  }

  uploading.value = true
  try {
    const uploaded = []
    for (const file of toUpload) {
      let entity = createLocalHumanInputFileEntity(file)
      entity = { ...entity, progress: 30 }
      if (isFileHumanInputField(field))
        setFieldFiles(field, [entity])
      else
        setFieldFiles(field, [...fileListFor(field), entity])

      try {
        const res = await uploadConsoleFile(file)
        entity = markHumanInputFileUploaded(entity, res)
      }
      catch (err) {
        entity = { ...entity, progress: -1, uploadedId: '' }
        localError.value = err?.message || '文件上传失败'
      }

      if (isFileHumanInputField(field)) {
        setFieldFiles(field, entity.progress === -1 ? [] : [entity])
      }
      else {
        const list = fileListFor(field).map(f => (f.id === entity.id ? entity : f))
          .filter(f => f.progress !== -1)
        setFieldFiles(field, list)
      }
      if (entity.progress !== -1)
        uploaded.push(entity)
    }
    if (!uploaded.length && !localError.value)
      localError.value = '文件上传失败'
  }
  finally {
    uploading.value = false
  }
}

async function onRemoteAdd(field) {
  if (!allowsRemoteHumanInputUpload(field)) {
    localError.value = '该字段不允许粘贴链接'
    return
  }
  const name = field.output_variable_name
  const url = String(remoteUrls[name] || '').trim()
  localError.value = ''
  if (!isValidRemoteFileUrl(url)) {
    localError.value = '请输入有效的 http(s) 链接'
    return
  }

  const limit = getHumanInputFileNumberLimit(field)
  const existing = fileListFor(field)
  if (isFileHumanInputField(field)) {
    // replace
  }
  else if (existing.length >= limit) {
    localError.value = `最多上传 ${limit} 个文件`
    return
  }

  uploading.value = true
  let entity = createRemoteHumanInputFileEntity(url)
  entity = { ...entity, progress: 30 }
  if (isFileHumanInputField(field))
    setFieldFiles(field, [entity])
  else
    setFieldFiles(field, [...existing, entity])

  try {
    const res = await uploadRemoteFileInfo(url)
    entity = markHumanInputFileUploaded(entity, res)
    if (isFileHumanInputField(field))
      setFieldFiles(field, [entity])
    else {
      setFieldFiles(field, fileListFor(field).map(f => (f.id === entity.id ? entity : f)))
    }
    remoteUrls[name] = ''
  }
  catch (err) {
    localError.value = err?.message || '链接无效或无法拉取文件'
    if (isFileHumanInputField(field))
      setFieldFiles(field, [])
    else
      setFieldFiles(field, fileListFor(field).filter(f => f.id !== entity.id))
  }
  finally {
    uploading.value = false
  }
}

async function handleAction(actionId) {
  localError.value = ''
  if (!props.formData?.form_token) {
    localError.value = '缺少 form_token，无法提交'
    return
  }
  const validationError = validateHumanInputValues(fields.value, values)
  if (validationError) {
    localError.value = validationError
    return
  }
  submitting.value = true
  try {
    await props.submitForm(props.formData.form_token, {
      inputs: getProcessedHumanInputFormInputs(fields.value, { ...values }),
      action: actionId,
    })
  }
  catch (error) {
    localError.value = error?.response?.data?.message || error?.message || '提交失败'
  }
  finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.human-input-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
  border: 1px solid #fecd08;
  border-radius: 10px;
  background: #fffcf0;
}

.form-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-header strong {
  color: #101828;
  font-size: 12px;
}

.form-content {
  margin: 0;
  color: #344054;
  font: 12px/1.45 inherit;
  white-space: pre-wrap;
  word-break: break-word;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #344054;
  font-size: 12px;
}

.field em {
  color: #d92d20;
  font-style: normal;
}

.field textarea,
.field select {
  padding: 7px 9px;
  border: 1px solid #d0d5dd;
  border-radius: 7px;
  font: inherit;
  background: #fff;
}

.file-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.remote-row {
  display: flex;
  gap: 6px;
}

.remote-row input {
  flex: 1;
  padding: 7px 9px;
  border: 1px solid #d0d5dd;
  border-radius: 7px;
  font: inherit;
  background: #fff;
}

.remote-btn {
  padding: 7px 10px;
  border: 0;
  border-radius: 7px;
  background: #f2f4f7;
  color: #344054;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.remote-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.file-chips {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.file-chips li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 7px;
  background: #fff;
  border: 1px solid #eaecf0;
  font-size: 11px;
}

.file-meta {
  color: #667085;
  margin-left: auto;
}

.remove-file {
  border: 0;
  background: transparent;
  color: #d92d20;
  cursor: pointer;
  font-size: 11px;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.action-btn {
  padding: 7px 12px;
  border: 0;
  border-radius: 7px;
  background: #f2f4f7;
  color: #344054;
  font-size: 12px;
  cursor: pointer;
}

.action-btn.primary {
  background: #0033ff;
  color: #fff;
}

.action-btn.danger {
  background: #d92d20;
  color: #fff;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error {
  margin: 0;
  padding: 6px 8px;
  border-radius: 7px;
  background: #fef3f2;
  color: #b42318;
  font-size: 11px;
}
</style>
