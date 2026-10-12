<template>
  <section class="sandbox">
    <div class="sandbox-header">
      <div>
        <h2>发布插件</h2>
        <p>直接发布不会调用外部 API；测试发布会真实调用外部 API，可能消耗额度。</p>
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
          <h3>发布方式</h3>
          <div class="publish-actions">
            <button
              type="button"
              class="secondary-publish"
              :disabled="!canRunTest || testing || uploading"
              @click="handleTest"
            >
              {{ testing && activePublishMode === 'test' ? '测试并发布中…' : '真实测试并发布' }}
            </button>
            <button
              type="button"
              class="direct-publish"
              :disabled="!canPublish || testing || uploading"
              @click="handleDirectPublish"
            >
              {{ testing && activePublishMode === 'direct' ? '直接发布中…' : uploading ? '上传中…' : '直接发布（不调用 API）' }}
            </button>
          </div>
        </div>

        <p class="direct-publish-hint">两种方式都会先用隔离的影子候选完成依赖安装、导入和启动；直接发布只跳过外部 API 调用。</p>

        <h3 class="test-parameters-title">真实测试参数（可选）</h3>

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
          如需真实测试，请先填写必填参数：{{ missingRequiredLabels }}
        </p>
        <p v-else-if="missingRequiredCredentials" class="test-hint warn">
          如需真实测试，请先填写必填凭据：凭据只用于本次验证，不会保存。
        </p>
        <p v-if="uploadError" class="test-hint warn">{{ uploadError }}</p>
        <div v-if="publishJob && !terminalPublishJob" class="publish-progress">
          <div class="test-result-header">
            <strong>{{ currentPublishStageLabel }}</strong>
            <span>{{ publishElapsedMs }} ms</span>
          </div>
          <p>后台任务：{{ publishJob.id }}</p>
          <p v-if="externalCallSummary">{{ externalCallSummary }}</p>
          <ol v-if="publishStages.length" class="publish-stage-list">
            <li v-for="stage in publishStages" :key="`${stage.stage}-${stage.started_at}`">
              {{ stageLabel(stage.stage) }} · {{ stage.duration_ms }} ms
            </li>
          </ol>
          <button
            v-if="publishJob.can_cancel"
            type="button"
            class="secondary-btn"
            @click="cancelCurrentPublish"
          >
            取消发布
          </button>
        </div>
        <div v-if="testResult" class="test-result" :class="{ error: !testResult.ok }">
          <div class="test-result-header">
            <strong>{{ publishResultTitle }}</strong>
            <span>{{ testResult.elapsed_ms }} ms</span>
          </div>
          <p v-if="testResult.plugin_unique_identifier" class="test-package">
            实际运行包：{{ testResult.plugin_unique_identifier }}
          </p>
          <p v-if="testResult.build_trace?.canonical_digest" class="test-package">
            构建指纹：{{ testResult.build_trace.canonical_digest.slice(0, 16) }}
          </p>
          <p v-if="publishFailureStage" class="test-package">失败阶段：{{ publishFailureStage }}</p>
          <pre>{{ testResult.ok ? (testResult.output_text || '（无输出）') : (testResult.diagnostic?.message || testResult.error || '（无错误详情）') }}</pre>
          <ul v-if="publishDiagnostics.length" class="diagnostic-list">
            <li v-for="(item, index) in publishDiagnostics" :key="`${item.code || item.stage}-${index}`">
              <strong>{{ item.code || item.stage }}</strong>
              <span v-if="item.path">{{ item.path }}<template v-if="item.line">:{{ item.line }}</template></span>
              <p>{{ item.message }}</p>
              <small v-if="item.suggestion">建议：{{ item.suggestion }}</small>
            </li>
          </ul>
        </div>
        <p v-if="unauthorized" class="authorization-error">
          当前账号无权测试工具。<RouterLink to="/integrations?tab=tools">前往工具授权</RouterLink>
        </p>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { uploadConsoleFile, uploadRemoteFileInfo } from '@/shared/media/difyFilesApi.js'
import {
  authorizeToolPluginTest,
  cancelToolPluginPublishJob,
  getToolPluginPublishJob,
  publishToolPluginSession,
} from '@/features/integrations/api/difyToolPluginGeneratorApi.js'
import { isAuthorizationError } from './pluginInstallHelpers.js'
import { toSandboxNodeData } from './previewToolNodeData.js'
import {
  buildDirectPublishPayload,
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
const activePublishMode = ref('')
const uploading = ref(false)
const uploadError = ref('')
const testResult = ref(null)
const unauthorized = ref(false)
const publishJob = ref(null)
let publishPollGeneration = 0
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

const publishResultTitle = computed(() => {
  if (!testResult.value?.ok)
    return '发布失败'
  return activePublishMode.value === 'direct' ? '发布成功（未测试）' : '测试并发布成功'
})

const publishDiagnostics = computed(() => {
  return testResult.value?.diagnostic?.details?.diagnostics || []
})

const publishFailureStage = computed(() => {
  const stage = testResult.value?.diagnostic?.stage
  return {
    validate: '发布前预检',
    stage_cleanup: '清理遗留影子候选',
    stage_install: '安装并启动影子候选',
    stage_test: '调用影子候选',
    install: '切换正式插件',
    test: '正式插件测试',
    persist: '保存发布状态',
  }[stage] || stage || ''
})

const terminalPublishJob = computed(() => ['published', 'publish_failed', 'rollback_failed', 'cancelled'].includes(publishJob.value?.status))
const publishStages = computed(() => publishJob.value?.trace?.stages || [])
const publishElapsedMs = computed(() => publishStages.value.reduce((total, stage) => total + Number(stage.duration_ms || 0), 0))
const currentPublishStageLabel = computed(() => {
  if (publishJob.value?.status === 'queued')
    return '等待后台 worker'
  return stageLabel(publishJob.value?.trace?.state || 'preparing')
})
const externalCallSummary = computed(() => {
  if (activePublishMode.value === 'direct')
    return '外部 API 调用：0（直接发布模式）'
  const called = publishStages.value.some(stage => ['stage_verify', 'test'].includes(stage.stage))
  return `外部 API 调用：${called ? '已进入真实测试阶段（最多 1 次）' : '尚未调用'}`
})

const STAGE_LABELS = {
  preparing: '准备发布',
  preflight: '校验文件与依赖',
  stage_cleanup: '清理旧影子候选',
  stage_install: '安装影子候选',
  stage_verify: '验证影子候选',
  commit_install: '安装正式插件',
  persist: '保存发布状态',
  cleanup: '清理候选',
  published: '发布完成',
  failed: '发布失败',
  rollback_failed: '回滚失败',
}

function stageLabel(stage) {
  return STAGE_LABELS[stage] || stage || '等待开始'
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function waitForPublishJob(initialJob) {
  const generation = ++publishPollGeneration
  let transientFailures = 0
  publishJob.value = initialJob
  while (!terminalPublishJob.value && generation === publishPollGeneration) {
    await sleep(1000)
    try {
      publishJob.value = await getToolPluginPublishJob(initialJob.id)
      transientFailures = 0
    }
    catch (error) {
      const status = error?.response?.status
      if ((status && status < 500) || ++transientFailures > 30)
        throw error
      await sleep(Math.min(5000, transientFailures * 500))
    }
  }
  if (generation !== publishPollGeneration)
    throw new Error('发布状态轮询已停止。')
  if (publishJob.value.status === 'cancelled') {
    return {
      ok: false,
      status: 'cancelled',
      elapsed_ms: publishElapsedMs.value,
      diagnostic: { stage: publishJob.value.trace?.state, message: '发布已安全取消。' },
      build_trace: publishJob.value.trace,
    }
  }
  return publishJob.value.result || {
    ok: false,
    status: publishJob.value.status,
    elapsed_ms: publishElapsedMs.value,
    diagnostic: publishJob.value.diagnostic,
    build_trace: publishJob.value.trace,
  }
}

async function cancelCurrentPublish() {
  if (!publishJob.value?.id)
    return
  publishJob.value = await cancelToolPluginPublishJob(publishJob.value.id)
}

onBeforeUnmount(() => {
  publishPollGeneration += 1
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
  activePublishMode.value = 'test'
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
    const job = await publishToolPluginSession(props.sessionId, {
      ...payload,
      publish_mode: 'test',
      authorization_token: authorization.token,
    })
    for (const key of Object.keys(nodeData.value.credentials || {}))
      nodeData.value.credentials[key] = ''
    const result = await waitForPublishJob(job)
    testResult.value = result
    emit('publish-result', { ...result, publish_mode: 'test' })
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

async function handleDirectPublish() {
  if (!props.canPublish)
    return

  testing.value = true
  activePublishMode.value = 'direct'
  testResult.value = null
  unauthorized.value = false
  uploadError.value = ''
  emit('publish-start')
  try {
    await ElMessageBox.confirm(
      '将执行完整预检，并用隔离的影子候选验证依赖安装、Python 导入和启动；不会调用外部 API，也不会消耗 API 调用次数。影子验证通过后才会切换正式插件。',
      '确认直接发布',
      {
        type: 'warning',
        confirmButtonText: '直接发布',
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
      },
    )
    const job = await publishToolPluginSession(
      props.sessionId,
      buildDirectPublishPayload({
        expectedRevision: props.expectedRevision,
        toolName: nodeData.value.tool_name,
      }),
    )
    const result = await waitForPublishJob(job)
    testResult.value = result
    emit('publish-result', { ...result, publish_mode: 'direct' })
  }
  catch (error) {
    if (error === 'cancel' || error === 'close' || error?.action === 'cancel' || error?.action === 'close')
      return
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
    emit('publish-result', { ...failure, publish_mode: 'direct' })
  }
  finally {
    testing.value = false
    emit('publish-end')
  }
}
</script>

<style scoped>
.sandbox {
  display: flex;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  flex-direction: column;
  border-top: 1px solid #eaecf0;
  background: #f9fafb;
}
.sandbox-header {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid #eaecf0;
}
.sandbox-header h2 { margin: 0; font-size: 14px; }
.sandbox-header p { margin: 4px 0 0; color: #667085; font-size: 12px; }
.publish-progress {
  margin-top: 12px;
  border: 1px solid #c7d7fe;
  border-radius: 10px;
  background: #f5f8ff;
  padding: 12px;
  color: #344054;
  font-size: 12px;
}
.publish-progress p { margin: 6px 0; overflow-wrap: anywhere; }
.publish-stage-list { margin: 8px 0; padding-left: 20px; }
.publish-stage-list li { margin: 4px 0; }
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
  flex: 1;
  gap: 16px;
  min-height: 0;
  overflow: hidden;
  padding: 16px;
}
.node-preview {
  display: grid;
  min-height: 0;
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
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  background: #fff;
  padding: 14px;
}
.parameter-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.parameter-panel h3 { margin: 0; color: #344054; font-size: 13px; }
.publish-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.parameter-header button {
  border: 1px solid var(--af-brand);
  border-radius: 8px;
  background: var(--af-brand);
  padding: 7px 10px;
  color: #fff;
  cursor: pointer;
  font-size: 12px;
}
.parameter-header .secondary-publish {
  border-color: #c7d7fe;
  background: #fff;
  color: var(--af-brand-strong);
}
.parameter-header button:disabled { cursor: not-allowed; opacity: .55; }
.direct-publish-hint {
  margin: -2px 0 14px;
  color: #475467;
  font-size: 11px;
  line-height: 1.5;
}
.test-parameters-title { margin-bottom: 12px !important; }
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
.diagnostic-list {
  display: grid;
  gap: 8px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}
.diagnostic-list li {
  border-top: 1px solid #fecdca;
  padding-top: 8px;
  color: #344054;
  font-size: 11px;
}
.diagnostic-list li > span { margin-left: 8px; color: #667085; font-family: Consolas, Monaco, monospace; }
.diagnostic-list li > p { margin: 4px 0; }
.diagnostic-list li > small { color: #667085; }
.authorization-error { margin: 12px 0 0; color: #b42318; font-size: 12px; }
.authorization-error a { color: var(--af-brand-strong); }
@media (max-width: 760px) {
  .sandbox-content {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }
  .node-preview { min-height: 220px; }
  .parameter-panel { overflow: visible; }
}
</style>
