<template>
  <div class="pipeline-editor" v-loading="loading">
    <div v-if="!loading && !pipelineId" class="conversion">
      <h2>转换为知识流水线</h2>
      <p>当前知识库尚未绑定 Pipeline。转换后可使用数据源 → 处理 → 写入知识库的流水线编辑器。</p>
      <el-button type="primary" :loading="converting" @click="doConvert">立即转换</el-button>
    </div>

    <div v-else-if="loadError" class="error-box">
      <p>{{ loadError }}</p>
      <el-button type="primary" @click="load">重试</el-button>
    </div>

    <div v-else-if="pipelineId" class="canvas-wrap">
      <WorkflowCanvas
        ref="canvasRef"
        :key="pipelineId"
        :app-id="pipelineId"
        flow-type="pipeline"
        workflow-mode="workflow"
        :nodes="[]"
        :edges="[]"
        :environment-variables="environmentVariables"
        :conversation-variables="conversationVariables"
        :rag-pipeline-variables="ragPipelineVariables"
        :publishing="publishing"
        :publish-status="publishStatus"
        :is-running="debugState.isRunning"
        :can-stop="debugCanStop"
        :run-status="debugState.runStatus"
        :result-text="debugState.resultText"
        :run-error="debugState.runError"
        :run-outputs="debugState.runOutputs"
        :conversation-id="debugState.conversationId"
        :task-id="debugState.taskId"
        :run-result="debugState.result"
        :tracing-items="debugState.tracing"
        :chat-list="debugChatList"
        :active-run-tab="debugActiveTab"
        :after-answer-suggestions="debugAfterAnswerSuggestions"
        height="100%"
        @back="goBack"
        @save-draft="handleSaveDraft"
        @publish="handlePublish"
        @run-workflow="handleRunWorkflow"
        @run-node="onRunUnsupported"
        @stop-run="handleStopRun"
        @restore-version="handleRestoreVersion"
        @update:active-run-tab="setDebugActiveTab"
        @sync-variables="handleSyncVariables"
      />
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import WorkflowCanvas from '@/features/workflow/canvas/WorkflowCanvas.vue'
import { useWorkflowDebugSession } from '@/features/workflow/model/useWorkflowDebugSession.js'
import { useWorkflowStore } from '@/features/workflow/state/useWorkflowStore.js'
import { fetchDatasetDetail } from '@/features/datasets/api/difyDatasetsApi.js'
import {
  getPublishedPipeline,
  isDraftWorkflowNotExistError,
  loadPipelineDraft,
  publishPipeline,
  restorePipelineVersion,
  runPipelineDraft,
  savePipelineDraft,
  stopPipelineRun,
  transformDatasetToPipeline,
} from '@/features/datasets/api/difyPipelineApi.js'
import { buildEmptyPipelineGraph } from '@/features/datasets/model/pipelineTemplates.js'
import { sanitizeEnvironmentVariables } from '@/features/workflow/api/difyWorkflowApi.js'

const route = useRoute()
const router = useRouter()
const store = useWorkflowStore()
const {
  state: debugState,
  activeTab: debugActiveTab,
  chatList: debugChatList,
  afterAnswerSuggestions: debugAfterAnswerSuggestions,
  canStop: debugCanStop,
  setActiveTab: setDebugActiveTab,
  startRun: startDebugRun,
  stopRun: stopDebugRun,
} = useWorkflowDebugSession({
  runDraftFn: runPipelineDraft,
  stopRunFn: stopPipelineRun,
})

const canvasRef = ref(null)
const loading = ref(true)
const loadError = ref('')
const converting = ref(false)
const publishing = ref(false)
const publishStatus = ref('')
const pipelineId = ref('')
const datasetName = ref('')
const workflowHash = ref(null)
const environmentVariables = ref([])
const conversationVariables = ref([])
const ragPipelineVariables = ref([])

function datasetId() {
  return route.params.datasetId
}

function goBack() {
  router.push(`/datasets/${datasetId()}/documents`)
}

function onRunUnsupported() {
  ElMessage.info('流水线单节点试运行暂不支持，请使用整条流水线调试。')
}

async function doConvert() {
  converting.value = true
  try {
    const res = await transformDatasetToPipeline(datasetId())
    ElMessage.success('已转换为知识流水线')
    pipelineId.value = res.pipeline_id || res.id || ''
    await load()
  }
  catch (e) {
    ElMessage.error(e.message || '转换失败')
  }
  finally {
    converting.value = false
  }
}

async function ensureDraft(pid) {
  try {
    return await loadPipelineDraft(pid, { silent: true })
  }
  catch (error) {
    if (!isDraftWorkflowNotExistError(error))
      throw error
    const graph = buildEmptyPipelineGraph()
    await savePipelineDraft(pid, {
      graph,
      environment_variables: [],
      conversation_variables: [],
      rag_pipeline_variables: [],
    })
    return loadPipelineDraft(pid, { silent: true })
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  let draft = null
  try {
    const ds = await fetchDatasetDetail(datasetId())
    datasetName.value = ds.name || '知识流水线'
    pipelineId.value = ds.pipeline_id || ''
    if (!pipelineId.value) {
      loading.value = false
      return
    }

    draft = await ensureDraft(pipelineId.value)
    environmentVariables.value = sanitizeEnvironmentVariables(draft.environment_variables || [])
    conversationVariables.value = draft.conversation_variables || []
    ragPipelineVariables.value = draft.rag_pipeline_variables || []
    workflowHash.value = draft.hash || null
    store.setRagPipelineVariables(ragPipelineVariables.value)

    try {
      const published = await getPublishedPipeline(pipelineId.value, { silent: true })
      publishStatus.value = published ? '已发布' : '未发布'
    }
    catch {
      publishStatus.value = '未发布'
    }
  }
  catch (e) {
    loadError.value = e.message || '流水线草稿加载失败'
  }
  finally {
    loading.value = false
    if (draft && pipelineId.value) {
      await nextTick()
      canvasRef.value?.initializeDraft?.({
        ...draft,
        name: datasetName.value,
        graph: draft.graph || { nodes: [], edges: [] },
      })
    }
  }
}

async function persistDraft(payload) {
  const body = {
    graph: payload.graph,
    environment_variables: payload.environmentVariables || environmentVariables.value || [],
    conversation_variables: payload.conversationVariables || conversationVariables.value || [],
    rag_pipeline_variables: store.ragPipelineVariables || ragPipelineVariables.value || [],
    hash: workflowHash.value,
  }
  try {
    return await savePipelineDraft(pipelineId.value, body)
  }
  catch (error) {
    if (error.response?.status !== 409)
      throw error
    const latest = await loadPipelineDraft(pipelineId.value, { silent: true })
    workflowHash.value = latest.hash || null
    return savePipelineDraft(pipelineId.value, { ...body, hash: workflowHash.value })
  }
}

async function handleSaveDraft(payload) {
  const silent = !!payload?.silent
  try {
    const result = await persistDraft(payload)
    workflowHash.value = result.hash || workflowHash.value
    environmentVariables.value = sanitizeEnvironmentVariables(payload.environmentVariables || [])
    conversationVariables.value = payload.conversationVariables || []
    // Keep local rag vars; do not bounce store → prop (avoids canvas prop watch loops).
    await nextTick()
    canvasRef.value?.markDraftSaved?.()
    if (!silent)
      ElMessage.success('流水线草稿已保存')
  }
  catch (error) {
    canvasRef.value?.markDraftSaveFailed?.()
    if (error.response?.status === 409)
      ElMessage.error('草稿已在其他窗口更新，请刷新后重试')
    else if (!silent)
      ElMessage.error(error.message || '保存失败')
    else
      ElMessage.error(error.message || '自动保存失败')
  }
}

async function handlePublish(payload) {
  publishing.value = true
  try {
    await persistDraft(payload)
    await publishPipeline(pipelineId.value, {
      marked_name: '',
      marked_comment: '',
    })
    publishStatus.value = '已发布'
    ElMessage.success('流水线已发布')
  }
  catch (e) {
    ElMessage.error(e.message || '发布失败')
  }
  finally {
    publishing.value = false
  }
}

async function syncDraftBeforeRun() {
  const payload = canvasRef.value?.buildDraftPayload?.() || {
    graph: canvasRef.value?.exportGraph?.() || { nodes: [], edges: [] },
    environmentVariables: environmentVariables.value,
    conversationVariables: conversationVariables.value,
  }
  const result = await persistDraft(payload)
  workflowHash.value = result.hash || workflowHash.value
  environmentVariables.value = sanitizeEnvironmentVariables(payload.environmentVariables || [])
  conversationVariables.value = payload.conversationVariables || []
  await nextTick()
  canvasRef.value?.markDraftSaved?.()
  return result
}

async function handleRunWorkflow(payload = {}) {
  if (!pipelineId.value || debugState.isRunning)
    return
  canvasRef.value?.openDebugPreview?.()
  try {
    await startDebugRun({
      appId: pipelineId.value,
      mode: 'workflow',
      inputs: payload.inputs || {},
      syncDraft: syncDraftBeforeRun,
      onCanvasEvent: (canvasEvent) => canvasRef.value?.applyNodeRunState?.(canvasEvent),
    })
  }
  catch (error) {
    if (error?.name === 'AbortError')
      return
    ElMessage.error(error?.response?.data?.message || error?.message || '流水线运行失败')
    return
  }
  if (debugState.runError)
    ElMessage.error(debugState.runError)
}

async function handleStopRun() {
  if (!pipelineId.value)
    return
  await stopDebugRun(pipelineId.value)
  ElMessage.success('已发送停止指令')
}

async function handleRestoreVersion(workflowId) {
  if (!pipelineId.value || !workflowId)
    return
  try {
    await restorePipelineVersion(pipelineId.value, workflowId)
    ElMessage.success('已恢复到草稿，正在重新加载…')
    await load()
  }
  catch (error) {
    ElMessage.error(error.response?.data?.message || error.message || '恢复版本失败')
    throw error
  }
}

function handleSyncVariables({ environmentVariables: env, conversationVariables: conv } = {}) {
  if (env)
    environmentVariables.value = sanitizeEnvironmentVariables(env)
  if (conv)
    conversationVariables.value = conv
}

onMounted(load)
watch(() => route.params.datasetId, load)
</script>

<style scoped>
.pipeline-editor {
  height: 100%;
  min-height: 560px;
  position: relative;
  background: #f8fafc;
}
.canvas-wrap {
  height: 100%;
  min-height: 560px;
}
.conversion, .error-box {
  max-width: 520px;
  margin: 64px auto;
  text-align: center;
  padding: 24px;
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 12px;
}
.conversion h2, .error-box p {
  margin: 0 0 10px;
  color: #101828;
}
.conversion p {
  margin: 0 0 16px;
  color: #667085;
  font-size: 13px;
}
</style>
