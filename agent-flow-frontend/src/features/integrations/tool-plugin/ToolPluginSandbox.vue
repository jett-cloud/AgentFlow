<template>
  <section class="sandbox">
    <div class="sandbox-header">
      <div>
        <h2>验证并发布</h2>
        <p>测试会真实调用外部 API，可能消耗额度；成功后才会发布当前草稿。</p>
      </div>
      <span class="local-badge">本地预览</span>
    </div>

    <div class="sandbox-content">
      <div class="node-preview">
        <div class="tool-node">
          <div class="node-header">
            <span class="node-icon">⌘</span>
            <span class="node-title">{{ nodeData.title }}</span>
          </div>
          <div class="node-body">
            <div class="tool-meta-row">
              <span class="tool-label">TOOL</span>
              <span class="tool-provider">
                {{ nodeData.provider_name || nodeData.provider_id || 'plugin' }}
              </span>
            </div>
            <div class="tool-name">{{ nodeData.tool_label || nodeData.tool_name }}</div>
          </div>
        </div>
      </div>

      <div class="parameter-panel">
        <div class="parameter-header">
          <h3>测试参数</h3>
          <button type="button" :disabled="!canRunTest || testing || uploading" @click="handleTest">
            {{ testing ? '验证并发布中…' : uploading ? '上传中…' : '真实测试并发布' }}
          </button>
        </div>

        <div v-if="nodeData.credentials_schema?.length" class="creds-block">
          <h4>凭证</h4>
          <p class="creds-hint">填写后仅用于本次发布请求，不会保存到会话、日志或 Agent 历史。</p>
          <div class="params-list">
            <label
              v-for="field in nodeData.credentials_schema"
              :key="field.name"
              class="param-row"
            >
              <span class="param-label">
                {{ parameterLabel(field) }}
                <em v-if="field.required !== false">必填</em>
              </span>
              <input
                :type="isSecretCredential(field) ? 'password' : 'text'"
                :value="credentialValue(field.name)"
                :placeholder="parameterPlaceholder(field) || field.name"
                autocomplete="off"
                @input="updateCredential(field.name, $event.target.value)"
              >
              <small>{{ field.type || 'secret-input' }}</small>
            </label>
          </div>
        </div>

        <div v-if="nodeData.parameters_schema.length" class="params-list">
          <div
            v-for="parameter in nodeData.parameters_schema"
            :key="parameter.name"
            class="param-row"
          >
            <span class="param-label">
              {{ parameterLabel(parameter) }}
              <em v-if="parameter.required">必填</em>
            </span>

            <template v-if="widgetKind(parameter) === 'file' || widgetKind(parameter) === 'files'">
              <div class="file-controls" :class="{ busy: uploading || testing }">
                <el-upload
                  drag
                  :multiple="widgetKind(parameter) === 'files'"
                  :auto-upload="false"
                  :show-file-list="false"
                  :disabled="uploading || testing"
                  class="sandbox-upload"
                  @change="(uploadFile) => onLocalUploadChange(parameter, uploadFile)"
                >
                  <div class="upload-inner">
                    <p class="upload-title">
                      {{ uploading ? '上传中…' : '拖拽文件到此处，或点击选择' }}
                    </p>
                    <p class="upload-hint">
                      {{ widgetKind(parameter) === 'files' ? '支持多文件' : '支持本地图片 / 文档' }}
                    </p>
                  </div>
                </el-upload>
                <div class="remote-row">
                  <input
                    v-model="remoteUrls[parameter.name]"
                    type="url"
                    placeholder="或粘贴远程文件 URL"
                    :disabled="uploading || testing"
                    @keyup.enter="onRemoteFileAdd(parameter)"
                  >
                  <button
                    type="button"
                    class="secondary-btn"
                    :disabled="uploading || testing || !remoteUrls[parameter.name]?.trim()"
                    @click="onRemoteFileAdd(parameter)"
                  >
                    拉取
                  </button>
                </div>
                <ul v-if="fileListFor(parameter).length" class="file-list">
                  <li v-for="(file, index) in fileListFor(parameter)" :key="`${file.upload_file_id}-${index}`">
                    <span class="file-name">{{ file.name || file.upload_file_id }}</span>
                    <button type="button" class="link-btn" @click="removeFile(parameter, index)">移除</button>
                  </li>
                </ul>
              </div>
            </template>

            <el-select
              v-else-if="widgetKind(parameter) === 'select'"
              :model-value="String(parameterValue(parameter.name) ?? '')"
              clearable
              filterable
              class="w-full"
              :placeholder="parameterPlaceholder(parameter) || '请选择'"
              :disabled="testing"
              @update:model-value="(val) => updateParameter(parameter.name, val ?? '')"
            >
              <el-option
                v-for="option in parameterOptions(parameter)"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>

            <el-switch
              v-else-if="widgetKind(parameter) === 'boolean'"
              :model-value="Boolean(parameterValue(parameter.name))"
              :disabled="testing"
              @update:model-value="(val) => updateParameter(parameter.name, val)"
            />

            <input
              v-else-if="widgetKind(parameter) === 'number'"
              type="number"
              :value="parameterValue(parameter.name)"
              :placeholder="parameterPlaceholder(parameter)"
              :disabled="testing"
              @input="updateParameter(parameter.name, $event.target.value)"
            >

            <input
              v-else-if="widgetKind(parameter) === 'secret' || widgetKind(parameter) === 'text'"
              :type="widgetKind(parameter) === 'secret' ? 'password' : 'text'"
              :value="parameterValue(parameter.name)"
              :placeholder="parameterPlaceholder(parameter)"
              :disabled="testing"
              autocomplete="off"
              @input="updateParameter(parameter.name, $event.target.value)"
            >

            <textarea
              v-else
              :value="parameterValue(parameter.name)"
              :placeholder="parameterPlaceholder(parameter)"
              rows="2"
              :disabled="testing"
              @input="updateParameter(parameter.name, $event.target.value)"
            />

            <small>{{ parameter.type || 'string' }}</small>
          </div>
        </div>
        <p v-else class="empty-parameters">此工具没有可配置参数。</p>
        <p v-if="!canPublish" class="test-hint">请先生成并保存插件草稿。</p>
        <p v-else-if="missingRequiredParameters.length" class="test-hint warn">
          请先填写必填参数：{{ missingRequiredLabels }}
        </p>
        <p v-else-if="missingRequiredCredentials" class="test-hint warn">
          请先填写必填凭据：凭据只用于本次验证，不会保存。
        </p>
        <p v-if="uploadError" class="test-hint warn">{{ uploadError }}</p>
        <div v-if="testResult" class="test-result" :class="{ error: !testResult.ok }">
          <div class="test-result-header">
            <strong>{{ testResult.ok ? '发布成功' : '发布失败' }}</strong>
            <span>{{ testResult.elapsed_ms }} ms</span>
          </div>
          <p v-if="testResult.plugin_unique_identifier" class="test-package">
            实际运行包：{{ testResult.plugin_unique_identifier }}
          </p>
          <pre>{{ testResult.ok ? (testResult.output_text || '（无输出）') : (testResult.diagnostic?.message || testResult.error || '（无错误详情）') }}</pre>
        </div>
        <p v-if="unauthorized" class="authorization-error">
          当前账号无权测试工具。<RouterLink to="/integrations?tab=tools">前往工具授权</RouterLink>
        </p>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { uploadConsoleFile, uploadRemoteFileInfo } from '@/shared/media/difyFilesApi.js'
import {
  authorizeToolPluginTest,
  publishToolPluginSession,
} from '@/features/integrations/api/difyToolPluginGeneratorApi.js'
import { isAuthorizationError } from './pluginInstallHelpers.js'
import { toSandboxNodeData } from './previewToolNodeData.js'
import {
  buildSandboxFilePayload,
  buildSandboxTestParameters,
  localizedParameterText,
  missingRequiredSandboxParameters,
  normalizeParameterOptions,
  parameterWidgetKind,
} from './sandboxParameterHelpers.js'

const props = defineProps({
  previewTool: { type: Object, required: true },
  canPublish: { type: Boolean, default: false },
  sessionId: { type: String, required: true },
  expectedRevision: { type: Number, required: true },
})

const emit = defineEmits(['publish-start', 'publish-result', 'publish-end'])

const nodeData = ref(toSandboxNodeData(props.previewTool))
const testing = ref(false)
const uploading = ref(false)
const uploadError = ref('')
const testResult = ref(null)
const unauthorized = ref(false)
const remoteUrls = reactive({})

watch(
  () => props.previewTool,
  (previewTool) => {
    const previousCredentials = { ...(nodeData.value.credentials || {}) }
    const previousParameters = { ...(nodeData.value.tool_parameters || {}) }
    nodeData.value = toSandboxNodeData(previewTool)
    for (const field of nodeData.value.credentials_schema || []) {
      if (field?.name && previousCredentials[field.name])
        nodeData.value.credentials[field.name] = previousCredentials[field.name]
    }
    for (const parameter of nodeData.value.parameters_schema || []) {
      if (!parameter?.name)
        continue
      const previous = previousParameters[parameter.name]
      if (previous && previous.value !== undefined && previous.value !== null && previous.value !== '')
        nodeData.value.tool_parameters[parameter.name] = previous
      remoteUrls[parameter.name] = remoteUrls[parameter.name] || ''
    }
    testResult.value = null
    unauthorized.value = false
    uploadError.value = ''
  },
)

const missingRequiredCredentials = computed(() => {
  const schema = nodeData.value.credentials_schema || []
  return schema.some((field) => {
    if (field.required === false)
      return false
    return !String(nodeData.value.credentials?.[field.name] ?? '').trim()
  })
})

const missingRequiredParameters = computed(() => {
  return missingRequiredSandboxParameters(
    nodeData.value.parameters_schema,
    nodeData.value.tool_parameters,
  )
})

const missingRequiredLabels = computed(() => {
  const schema = nodeData.value.parameters_schema || []
  return missingRequiredParameters.value
    .map((name) => {
      const parameter = schema.find(item => item.name === name)
      return parameter ? parameterLabel(parameter) : name
    })
    .join('、')
})

const canRunTest = computed(() => {
  return props.canPublish
    && !missingRequiredParameters.value.length
    && !missingRequiredCredentials.value
})

function parameterLabel(parameter) {
  return localizedParameterText(parameter.label) || parameter.name
}

function parameterPlaceholder(parameter) {
  return localizedParameterText(parameter.human_description)
    || localizedParameterText(parameter.help)
    || parameter.name
}

function widgetKind(parameter) {
  return parameterWidgetKind(parameter)
}

function parameterOptions(parameter) {
  return normalizeParameterOptions(parameter)
}

function parameterValue(name) {
  return nodeData.value.tool_parameters[name]?.value
}

function updateParameter(name, value) {
  nodeData.value.tool_parameters[name] = { type: 'constant', value }
}

function credentialValue(name) {
  return nodeData.value.credentials?.[name] ?? ''
}

function updateCredential(name, value) {
  nodeData.value.credentials = {
    ...(nodeData.value.credentials || {}),
    [name]: value,
  }
}

function isSecretCredential(field) {
  const type = String(field?.type || '').toLowerCase()
  const name = String(field?.name || '').toLowerCase()
  return type.includes('secret') || /key|token|secret|password/.test(name)
}

function fileListFor(parameter) {
  const value = parameterValue(parameter.name)
  const kind = widgetKind(parameter)
  if (kind === 'files')
    return Array.isArray(value) ? value : []
  return value ? [value] : []
}

function setFileValue(parameter, files) {
  const kind = widgetKind(parameter)
  if (kind === 'files')
    updateParameter(parameter.name, files)
  else
    updateParameter(parameter.name, files[0] || null)
}

function removeFile(parameter, index) {
  const files = [...fileListFor(parameter)]
  files.splice(index, 1)
  setFileValue(parameter, files)
}

async function onLocalUploadChange(parameter, uploadFile) {
  const file = uploadFile?.raw
  if (!file)
    return

  uploadError.value = ''
  uploading.value = true
  try {
    const res = await uploadConsoleFile(file)
    const payload = buildSandboxFilePayload({
      uploadFileId: res?.id || res?.upload_file_id,
      transferMethod: 'local_file',
      url: res?.url || '',
      name: res?.name || file.name,
      mimeType: res?.mime_type || file.type,
      size: res?.size ?? file.size,
    })
    if (!payload)
      throw new Error('文件上传失败，未返回文件 ID。')

    if (widgetKind(parameter) === 'files')
      setFileValue(parameter, [...fileListFor(parameter), payload])
    else
      setFileValue(parameter, [payload])
  }
  catch (error) {
    uploadError.value = error.response?.data?.message || error.message || '文件上传失败。'
  }
  finally {
    uploading.value = false
  }
}

async function onRemoteFileAdd(parameter) {
  const url = String(remoteUrls[parameter.name] || '').trim()
  if (!url)
    return
  if (!/^https?:\/\//i.test(url)) {
    uploadError.value = '请输入有效的 http(s) 链接。'
    return
  }

  uploadError.value = ''
  uploading.value = true
  try {
    const res = await uploadRemoteFileInfo(url)
    const payload = buildSandboxFilePayload({
      uploadFileId: res?.id || res?.upload_file_id,
      transferMethod: 'remote_url',
      url: res?.url || url,
      name: res?.name || url.split('/').pop() || 'remote-file',
      mimeType: res?.mime_type || '',
      size: res?.size ?? 0,
    })
    if (!payload)
      throw new Error('远程文件拉取失败，未返回文件 ID。')

    if (widgetKind(parameter) === 'files')
      setFileValue(parameter, [...fileListFor(parameter), payload])
    else
      setFileValue(parameter, [payload])
    remoteUrls[parameter.name] = ''
  }
  catch (error) {
    uploadError.value = error.response?.data?.message || error.message || '远程文件拉取失败。'
  }
  finally {
    uploading.value = false
  }
}

function currentCredentials() {
  return Object.fromEntries(
    Object.entries(nodeData.value.credentials || {})
      .filter(([, value]) => String(value ?? '').trim() !== ''),
  )
}

async function handleTest() {
  if (!canRunTest.value)
    return

  testing.value = true
  testResult.value = null
  unauthorized.value = false
  uploadError.value = ''
  emit('publish-start')
  try {
    const payload = {
      expected_revision: props.expectedRevision,
      tool_name: nodeData.value.tool_name,
      parameters: buildSandboxTestParameters(
        nodeData.value.parameters_schema,
        nodeData.value.tool_parameters,
      ),
      credentials: currentCredentials(),
    }
    await ElMessageBox.confirm(
      `这会最多真实调用 1 次外部 API（${nodeData.value.provider_name || nodeData.value.provider_id || '当前工具'}），可能消耗 API 或模型额度；当前会使用 ${Object.keys(currentCredentials()).length} 个凭证。成功后将发布当前草稿。`,
      '确认真实测试',
      {
        type: 'warning',
        confirmButtonText: '运行一次',
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
      },
    )
    const authorization = await authorizeToolPluginTest(props.sessionId, payload)
    const result = await publishToolPluginSession(props.sessionId, {
      ...payload,
      authorization_token: authorization.token,
    })
    testResult.value = result
    emit('publish-result', result)
    unauthorized.value = !result?.ok && isAuthorizationError(result?.error)
  }
  catch (error) {
    if (error === 'cancel' || error === 'close' || error?.action === 'cancel' || error?.action === 'close')
      return
    if (isAuthorizationError(error)) {
      unauthorized.value = true
      testResult.value = {
        ok: false,
        diagnostic: { message: error.response?.data?.message || '当前账号无权发布工具。' },
        elapsed_ms: 0,
      }
      return
    }
    const failure = error.response?.data?.diagnostic
      ? error.response.data
      : {
          ok: false,
          diagnostic: {
            error_type: error.response?.status === 409 ? 'session_conflict' : 'publish_request_error',
            message: error.response?.data?.message || error.message || '插件发布失败。',
          },
          elapsed_ms: 0,
        }
    testResult.value = failure
    emit('publish-result', failure)
  }
  finally {
    for (const key of Object.keys(nodeData.value.credentials || {}))
      nodeData.value.credentials[key] = ''
    testing.value = false
    emit('publish-end')
  }
}
</script>

<style scoped>
.sandbox {
  border-top: 1px solid #eaecf0;
  background: #f9fafb;
}
.sandbox-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid #eaecf0;
}
.sandbox-header h2 { margin: 0; font-size: 14px; }
.sandbox-header p { margin: 4px 0 0; color: #667085; font-size: 12px; }
.local-badge {
  flex: none;
  border: 1px solid #c7d7fe;
  border-radius: 999px;
  background: #eef4ff;
  padding: 3px 8px;
  color: #3538cd;
  font-size: 11px;
}
.sandbox-content {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(300px, 1fr);
  gap: 16px;
  padding: 16px;
}
.node-preview {
  display: grid;
  min-height: 220px;
  place-items: center;
  border: 1px dashed #d0d5dd;
  border-radius: 12px;
  background: #f2f4f7;
}
.tool-node {
  box-sizing: border-box;
  width: 240px;
  overflow: hidden;
  border: 1px solid var(--af-brand);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 8px 20px rgb(16 24 40 / 12%);
}
.node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 8px 12px;
  border-bottom: 1px solid #f2f4f7;
}
.node-icon { color: var(--af-brand-strong); font-weight: 700; }
.node-title {
  overflow: hidden;
  color: #101828;
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}
.node-body { padding: 10px 12px 12px; }
.tool-meta-row { display: flex; align-items: center; gap: 6px; }
.tool-label { color: #667085; font-size: 10px; font-weight: 700; }
.tool-provider {
  overflow: hidden;
  border: 1px solid #c7d2fe;
  border-radius: 4px;
  background: #eef2ff;
  padding: 1px 6px;
  color: #4338ca;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-name {
  overflow: hidden;
  margin-top: 6px;
  border-radius: 6px;
  background: #f8fafc;
  padding: 5px 7px;
  color: #344054;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.parameter-panel {
  border: 1px solid #eaecf0;
  border-radius: 12px;
  background: #fff;
  padding: 14px;
}
.parameter-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.parameter-panel h3 { margin: 0; color: #344054; font-size: 13px; }
.parameter-header button {
  border: 1px solid var(--af-brand);
  border-radius: 8px;
  background: var(--af-brand);
  padding: 7px 10px;
  color: #fff;
  cursor: pointer;
  font-size: 12px;
}
.parameter-header button:disabled { cursor: not-allowed; opacity: .55; }
.creds-block {
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f2f4f7;
}
.creds-block h4 {
  margin: 0 0 4px;
  color: #344054;
  font-size: 12px;
}
.creds-hint {
  margin: 0 0 10px;
  color: #98a2b3;
  font-size: 11px;
  line-height: 1.4;
}
.params-list { display: flex; flex-direction: column; gap: 10px; }
.param-row { display: flex; flex-direction: column; gap: 5px; color: #475467; font-size: 12px; }
.param-label { display: flex; align-items: center; gap: 6px; }
.param-label em { color: #b42318; font-size: 10px; font-style: normal; }
.param-row textarea,
.param-row input,
.file-controls input[type='url'] {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  padding: 8px 10px;
  color: #101828;
  font: inherit;
  background: #fff;
}
.param-row textarea { resize: vertical; }
.param-row textarea:focus,
.param-row input:focus,
.file-controls input:focus { border-color: var(--af-brand); outline: 2px solid var(--af-focus-ring); }
.param-row small { color: #98a2b3; font-size: 10px; }
.w-full { width: 100%; }
.file-controls { display: flex; flex-direction: column; gap: 8px; }
.file-controls.busy { opacity: .85; }
.sandbox-upload { width: 100%; }
.sandbox-upload :deep(.el-upload) { width: 100%; }
.sandbox-upload :deep(.el-upload-dragger) {
  width: 100%;
  padding: 16px 12px;
  border: 1px dashed #c7d7fe;
  border-radius: 10px;
  background: #f8fafc;
  transition: border-color .15s ease, background .15s ease;
}
.sandbox-upload :deep(.el-upload-dragger:hover) {
  border-color: var(--af-brand);
  background: #eef4ff;
}
.sandbox-upload :deep(.el-upload.is-disabled .el-upload-dragger) {
  cursor: not-allowed;
  opacity: .7;
}
.upload-inner { text-align: center; }
.upload-title {
  margin: 0;
  color: #344054;
  font-size: 12px;
  font-weight: 600;
}
.upload-hint {
  margin: 4px 0 0;
  color: #98a2b3;
  font-size: 11px;
}
.remote-row { display: flex; gap: 8px; }
.remote-row input { flex: 1; }
.secondary-btn,
.link-btn {
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #fff;
  padding: 7px 10px;
  color: #344054;
  cursor: pointer;
  font-size: 12px;
}
.secondary-btn:disabled { cursor: not-allowed; opacity: .55; }
.link-btn {
  border: none;
  padding: 0;
  color: var(--af-brand-strong);
  background: transparent;
}
.file-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.file-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 1px solid #eaecf0;
  border-radius: 8px;
  background: #f9fafb;
  padding: 6px 8px;
  color: #344054;
  font-size: 11px;
}
.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.empty-parameters { margin: 0; color: #98a2b3; font-size: 12px; }
.test-hint { margin: 12px 0 0; color: #667085; font-size: 11px; }
.test-hint.warn { color: #b54708; }
.test-result {
  margin-top: 12px;
  border: 1px solid #abefc6;
  border-radius: 8px;
  background: #ecfdf3;
  padding: 10px;
}
.test-result.error { border-color: #fecdca; background: #fef3f2; }
.test-result-header { display: flex; justify-content: space-between; gap: 12px; color: #027a48; font-size: 11px; }
.test-result.error .test-result-header { color: #b42318; }
.test-package {
  margin: 8px 0 0;
  color: #475467;
  font-size: 11px;
  word-break: break-all;
}
.test-result pre {
  overflow: auto;
  max-height: 220px;
  margin: 8px 0 0;
  color: #344054;
  font-family: Consolas, Monaco, monospace;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
}
.authorization-error { margin: 12px 0 0; color: #b42318; font-size: 12px; }
.authorization-error a { color: var(--af-brand-strong); }
@media (max-width: 760px) {
  .sandbox-content { grid-template-columns: 1fr; }
}
</style>
