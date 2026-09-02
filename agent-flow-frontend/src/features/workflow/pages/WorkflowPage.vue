<template>
  <div class="page-container" :class="{ 'is-editing': !!appId && !loading && !loadError }">
    <div v-if="!appId" class="home-panel" @dragenter.prevent="onDslDragEnter" @dragover.prevent="onDslDragOver" @dragleave.prevent="onDslDragLeave" @drop.prevent="onDslDrop">
      <div v-if="dslDragging" class="dsl-drop-overlay" aria-hidden="true" />

      <header class="page-header">
        <h1>工作流编排</h1>
        <p>创建和管理 Workflow、Chatflow 与 Agent 应用。</p>
      </header>

      <div class="studio-toolbar">
        <div class="toolbar-filters">
          <el-select v-model="listCategory" class="filter-select" placeholder="类型" @change="loadApps">
            <el-option v-for="item in categoryOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <div class="sort-wrap">
            <span class="sort-prefix">排序方式</span>
            <el-select v-model="listSortBy" class="sort-select" @change="loadApps">
              <el-option
                v-for="item in sortOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </div>
          <el-input
            v-model="listKeywords"
            class="search-input"
            clearable
            placeholder="搜索"
            :prefix-icon="Search"
            @input="onSearchInput"
            @clear="loadApps"
          />
        </div>
        <div class="toolbar-actions">
          <el-dropdown trigger="click" @command="onCreateCommand">
            <el-button type="primary">
              + 创建
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="blank">从空白创建</el-dropdown-item>
                <el-dropdown-item command="dsl">导入 DSL</el-dropdown-item>
                <el-dropdown-item command="template" disabled>从模板创建（即将支持）</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>

      <input
        ref="dslFileInput"
        class="visually-hidden"
        type="file"
        accept=".yml,.yaml,.json,text/yaml,application/json"
        aria-label="导入 DSL 文件"
        @change="onDslFilePicked"
      />

      <div v-if="appsLoading" class="state-card inline">
        <el-icon class="is-loading"><Loading /></el-icon>
        <p>正在加载应用列表…</p>
      </div>

      <div v-else-if="appsError" class="state-card inline error-card">
        <h2>加载失败</h2>
        <p>{{ appsError }}</p>
        <el-button @click="loadApps">重试</el-button>
      </div>

      <div v-else-if="apps.length === 0" class="state-card inline">
        <h2>还没有应用</h2>
        <p>点击右上角「创建」，从空白创建工作流 / Chatflow，或导入 DSL。</p>
      </div>

      <ul v-else class="app-grid">
        <li v-for="app in apps" :key="app.id">
          <div class="app-card-wrap">
            <button
              type="button"
              class="app-card"
              :disabled="!canOpenInStudio(app.mode)"
              :title="canOpenInStudio(app.mode) ? app.name : `${appModeLabel(app.mode)} 暂不支持在本工作室编辑`"
              @click="openAppCard(app)"
            >
              <div class="card-top">
                <span
                  class="app-icon"
                  :style="{ background: resolveAppCardIcon(app).background }"
                >
                  <img
                    v-if="resolveAppCardIcon(app).type === 'image'"
                    :src="resolveAppCardIcon(app).src"
                    alt=""
                  >
                  <template v-else>{{ resolveAppCardIcon(app).value }}</template>
                </span>
                <div class="card-title-block">
                  <strong>{{ app.name }}</strong>
                  <span class="mode-tag" :data-mode="app.mode">{{ appModeLabel(app.mode) }}</span>
                </div>
              </div>
              <p class="card-desc">{{ app.description || '暂无描述' }}</p>
              <div class="card-tags">
                <span class="tag-placeholder">添加标签</span>
              </div>
              <div class="card-footer">
                <span>{{ app.author_name || app.created_by_name || 'Dify' }}</span>
                <span>· 编辑于 {{ formatUpdatedAt(app.updated_at) }}</span>
              </div>
            </button>
            <el-dropdown
              class="card-more"
              trigger="click"
              @command="(cmd) => onAppCardCommand(cmd, app)"
            >
              <button type="button" class="more-btn" title="更多操作" @click.stop>
                ⋯
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-if="canOpenInStudio(app.mode)"
                    command="open"
                  >
                    打开
                  </el-dropdown-item>
                  <el-dropdown-item command="delete" divided class="danger-item">
                    删除
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </li>
      </ul>

      <el-dialog
        v-model="deleteDialogOpen"
        title="确认删除应用？"
        width="480px"
        append-to-body
        destroy-on-close
        @closed="resetDeleteDialog"
      >
        <p class="delete-copy">
          删除应用将无法撤销。用户将不能访问你的应用，所有 Prompt 编排配置和日志均将一并被删除。
        </p>
        <p class="delete-label">
          请在下方输入框中输入
          <strong>{{ deleteTarget?.name }}</strong>
          以确认：
        </p>
        <el-input
          v-model="deleteConfirmName"
          placeholder="输入应用名称…"
          autocomplete="off"
          @keydown.enter.prevent="confirmDeleteApp"
        />
        <template #footer>
          <el-button :disabled="deleting" @click="deleteDialogOpen = false">取消</el-button>
          <el-button
            type="danger"
            :loading="deleting"
            :disabled="!canConfirmDelete"
            @click="confirmDeleteApp"
          >
            确认
          </el-button>
        </template>
      </el-dialog>

      <div class="dsl-hint" role="note">
        <span aria-hidden="true">⇩</span>
        拖放 DSL 文件到此处创建应用
      </div>

      <CreateAppDialog
        v-model="createDialogOpen"
        :loading="creating"
        @create="handleCreateApp"
      />
    </div>

    <div v-else-if="loading" class="state-card">
      <el-icon class="is-loading"><Loading /></el-icon>
      <p>正在加载 Dify 草稿…</p>
    </div>

    <div v-else-if="loadError" class="state-card error-card">
      <h2>草稿加载失败</h2>
      <p>{{ loadError }}</p>
      <div class="actions">
        <el-button @click="backToHome">返回列表</el-button>
        <el-button type="primary" @click="loadWorkflow">重试</el-button>
      </div>
    </div>

    <div v-else class="canvas-wrapper">
      <WorkflowCanvas
        ref="canvasRef"
        :key="appId"
        :app-id="appId"
        :workflow-mode="workflowMode"
        :draft-hash="workflowHash"
        :nodes="projectNodes"
        :edges="projectEdges"
        :environment-variables="environmentVariables"
        :conversation-variables="conversationVariables"
        :rag-pipeline-variables="ragPipelineVariables"
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
        :workflow-features="workflowFeatures"
        :features-saving="featuresSaving"
        :features-error="featuresError"
        :human-input-forms="debugState.humanInputFormDataList"
        :submit-human-input="submitHumanInput"
        :after-answer-suggestions="debugAfterAnswerSuggestions"
        :active-run-tab="debugActiveTab"
        :publishing="publishing"
        :publish-status="publishStatusLabel"
        height="100%"
        :sync-draft-if-dirty="syncDraftBeforeRun"
        @back="backToHome"
        @save-draft="handleSaveDraft"
        @publish="handlePublish"
        @run-workflow="handleRunWorkflow"
        @run-node="handleRunNode"
        @stop-run="handleStopRun"
        @new-conversation="handleNewConversation"
        @update:active-run-tab="setDebugActiveTab"
        @sync-variables="handleSyncVariables"
        @restore-version="handleRestoreVersion"
        @save-features="handleSaveFeatures"
        @assist-applied="handleWorkflowAssistApplied"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Loading, Search } from '@element-plus/icons-vue'
import WorkflowCanvas from '../canvas/WorkflowCanvas.vue'
import CreateAppDialog from '../ui/CreateAppDialog.vue'
import { graphToFlow } from '../model/dsl'
import { resolveDraftSaveAppId } from '../model/draftFlush.js'
import { resolveAppCardIcon } from '../model/appCardIcon.js'
import { useWorkflowDebugSession } from '../model/useWorkflowDebugSession.js'
import {
  AppListCategory,
  AppListSortBy,
  AppMode,
  appModeLabel,
  isChatflowMode,
  isWorkflowStudioMode,
} from '../model/appModes.js'
import {
  confirmAppDslImport,
  createApp,
  deleteApp,
  ensureDraft,
  importAppDsl,
  listApps,
  listPublishedWorkflows,
  loadAppDetail,
  loadDraft,
  normalizeWorkflowFeatures,
  publishWorkflow,
  restoreWorkflowVersion,
  runNode,
  sanitizeEnvironmentVariables,
  saveDraft,
  updateAppDetail,
  updateConversationVariables,
  updateEnvironmentVariables,
  updateFeatures,
} from '@/features/workflow/api/difyWorkflowApi.js'

const route = useRoute()
const router = useRouter()
const canvasRef = ref(null)
const loading = ref(false)
const loadError = ref('')
const projectNodes = ref([])
const projectEdges = ref([])
const environmentVariables = ref([])
const conversationVariables = ref([])
const ragPipelineVariables = ref([])
const workflowHash = ref(null)
const workflowFeatures = ref({})
const featuresSaving = ref(false)
const featuresError = ref('')
const workflowMode = ref(AppMode.WORKFLOW)
const appDetail = ref(null)
const publishing = ref(false)
const hasPublishedVersion = ref(false)
const {
  state: debugState,
  activeTab: debugActiveTab,
  chatList: debugChatList,
  afterAnswerSuggestions: debugAfterAnswerSuggestions,
  canStop: debugCanStop,
  setActiveTab: setDebugActiveTab,
  startRun: startDebugRun,
  stopRun: stopDebugRun,
  submitHumanInput,
  clearConversation,
  abortLocal,
} = useWorkflowDebugSession()

const apps = ref([])
const appsLoading = ref(false)
const appsError = ref('')
const creating = ref(false)
const createDialogOpen = ref(false)
const listCategory = ref(AppListCategory.ALL)
const listSortBy = ref(AppListSortBy.LAST_MODIFIED)
const listKeywords = ref('')
const dslFileInput = ref(null)
const dslDragging = ref(false)
const dslImporting = ref(false)
const deleteDialogOpen = ref(false)
const deleteTarget = ref(null)
const deleteConfirmName = ref('')
const deleting = ref(false)
let searchTimer = null
let dslDragDepth = 0

const canConfirmDelete = computed(() => (
  !!deleteTarget.value
  && deleteConfirmName.value.trim() === String(deleteTarget.value.name || '').trim()
  && !deleting.value
))

const categoryOptions = [
  { value: AppListCategory.ALL, label: '全部' },
  { value: AppListCategory.WORKFLOW, label: '工作流' },
  { value: AppListCategory.CHATFLOW, label: 'Chatflow' },
  { value: AppListCategory.AGENT, label: 'Agent' },
]

const sortOptions = [
  { value: AppListSortBy.LAST_MODIFIED, label: '最近修改' },
  { value: AppListSortBy.RECENTLY_CREATED, label: '最近创建' },
  { value: AppListSortBy.EARLIEST_CREATED, label: '最早创建' },
]

const appId = computed(() => String(route.query.appId || '').trim())
const publishStatusLabel = computed(() => (hasPublishedVersion.value ? '已发布' : '未发布'))

function openAppById(id) {
  router.replace({ path: '/', query: { appId: id } })
}

function backToHome() {
  // Flush while canvas + route still hold appId (query clear unmounts canvas).
  canvasRef.value?.flushDraftIfNeeded?.()
  abortLocal()
  router.replace({ path: '/' })
}

onBeforeRouteLeave((_to, _from, next) => {
  canvasRef.value?.flushDraftIfNeeded?.()
  next()
})

function canOpenInStudio(mode) {
  return isWorkflowStudioMode(mode)
}

function openAppCard(app) {
  if (!canOpenInStudio(app?.mode)) {
    ElMessage.warning(`${appModeLabel(app?.mode)} 暂不支持在本工作室编辑`)
    return
  }
  openAppById(app.id)
}

function onAppCardCommand(command, app) {
  if (command === 'open') {
    openAppCard(app)
    return
  }
  if (command === 'delete')
    openDeleteDialog(app)
}

function openDeleteDialog(app) {
  deleteTarget.value = app
  deleteConfirmName.value = ''
  deleteDialogOpen.value = true
}

function resetDeleteDialog() {
  deleteTarget.value = null
  deleteConfirmName.value = ''
  deleting.value = false
}

async function confirmDeleteApp() {
  if (!canConfirmDelete.value || !deleteTarget.value)
    return
  deleting.value = true
  const target = deleteTarget.value
  try {
    await deleteApp(target.id)
    deleteDialogOpen.value = false
    ElMessage.success('应用已删除')
    if (String(route.query.appId || '') === String(target.id))
      backToHome()
    else
      await loadApps()
  }
  catch (error) {
    ElMessage.error(error.response?.data?.message || error.message || '删除失败')
  }
  finally {
    deleting.value = false
  }
}

function onCreateCommand(command) {
  if (command === 'blank') {
    createDialogOpen.value = true
    return
  }
  if (command === 'dsl') {
    dslFileInput.value?.click()
    return
  }
  if (command === 'template')
    ElMessage.info('模板市场即将支持')
}

function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    loadApps()
  }, 300)
}

function formatUpdatedAt(value) {
  if (!value) return '刚刚创建'
  const ts = typeof value === 'number' ? value * (value < 1e12 ? 1000 : 1) : Date.parse(value)
  if (!Number.isFinite(ts)) return ''
  const d = new Date(ts)
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${yyyy}/${mm}/${dd} ${hh}:${mi}`
}

function onDslDragEnter() {
  dslDragDepth += 1
  dslDragging.value = true
}

function onDslDragOver() {
  dslDragging.value = true
}

function onDslDragLeave() {
  dslDragDepth = Math.max(0, dslDragDepth - 1)
  if (dslDragDepth === 0)
    dslDragging.value = false
}

function onDslDrop(event) {
  dslDragDepth = 0
  dslDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file)
    void importDslFile(file)
}

function onDslFilePicked(event) {
  const file = event.target?.files?.[0]
  event.target.value = ''
  if (file)
    void importDslFile(file)
}

async function importDslFile(file) {
  if (dslImporting.value)
    return
  dslImporting.value = true
  try {
    const yaml_content = await file.text()
    let response = await importAppDsl({ mode: 'yaml-content', yaml_content })
    if (response?.status === 'pending' && response?.id) {
      await ElMessageBox.confirm(
        [
          '检测到 DSL 版本差异，强制导入应用可能无法正常运行。',
          response.imported_dsl_version ? `当前应用 DSL 版本：${response.imported_dsl_version}` : '',
          response.current_dsl_version ? `系统支持 DSL 版本：${response.current_dsl_version}` : '',
          '是否继续？',
        ].filter(Boolean).join('\n'),
        '版本不兼容',
        { type: 'warning', confirmButtonText: '继续导入', cancelButtonText: '取消' },
      )
      response = await confirmAppDslImport(response.id)
    }
    const status = response?.status
    const appIdImported = response?.app_id
    if (!appIdImported || (status !== 'completed' && status !== 'completed-with-warnings'))
      throw new Error(response?.error || 'DSL 导入失败')
    if (status === 'completed-with-warnings')
      ElMessage.warning('应用已导入，但 DSL 版本差异可能影响部分功能')
    else
      ElMessage.success('应用已创建')
    await loadApps()
    if (canOpenInStudio(response.app_mode))
      openAppById(appIdImported)
  }
  catch (error) {
    if (error === 'cancel' || error === 'close')
      return
    ElMessage.error(error.response?.data?.message || error.message || 'DSL 导入失败')
  }
  finally {
    dslImporting.value = false
  }
}

async function refreshPublishStatus() {
  if (!appId.value) {
    hasPublishedVersion.value = false
    return
  }
  try {
    const response = await listPublishedWorkflows(appId.value, { page: 1, limit: 1 })
    const items = response.items || response.data || []
    hasPublishedVersion.value = items.length > 0
  } catch {
    hasPublishedVersion.value = !!appDetail.value?.workflow_id
  }
}

async function loadApps() {
  appsLoading.value = true
  appsError.value = ''
  try {
    // Contrasts Dify apps/list.tsx: All omits mode; otherwise pass single mode.
    const mode = listCategory.value === AppListCategory.ALL ? undefined : listCategory.value
    const response = await listApps({
      page: 1,
      limit: 50,
      mode,
      name: listKeywords.value.trim() || undefined,
      sort_by: listSortBy.value,
    })
    apps.value = response.data || response.items || []
  } catch (error) {
    appsError.value = error.response?.data?.message || error.message || '无法加载应用列表'
  } finally {
    appsLoading.value = false
  }
}

async function handleCreateApp(payload) {
  creating.value = true
  try {
    const mode = payload.mode || AppMode.ADVANCED_CHAT
    const app = await createApp({
      name: payload.name,
      mode,
      description: payload.description || '',
      icon_type: payload.icon_type || 'emoji',
      icon: payload.icon || '🤖',
      icon_background: payload.icon_type === 'image' ? undefined : (payload.icon_background || '#FFEAD5'),
    })
    await ensureDraft(app.id, { mode })
    createDialogOpen.value = false
    ElMessage.success(isChatflowMode(mode) ? 'Chatflow 已创建' : '工作流已创建')
    openAppById(app.id)
  } catch (error) {
    ElMessage.error(error.response?.data?.message || error.message || '创建失败')
  } finally {
    creating.value = false
  }
}

async function loadWorkflow() {
  if (!appId.value)
    return
  loading.value = true
  loadError.value = ''
  let loadedDraft = null
  try {
    const app = await loadAppDetail(appId.value)
    const mode = app.mode === AppMode.ADVANCED_CHAT ? AppMode.ADVANCED_CHAT : AppMode.WORKFLOW
    const draft = await ensureDraft(appId.value, { mode })
    const safeEnvironmentVariables = sanitizeEnvironmentVariables(draft.environment_variables)
    loadedDraft = { ...draft, name: app.name, environment_variables: safeEnvironmentVariables }
    appDetail.value = app
    const flow = graphToFlow(draft.graph || { nodes: [], edges: [] })
    projectNodes.value = flow.nodes
    projectEdges.value = flow.edges
    environmentVariables.value = safeEnvironmentVariables
    conversationVariables.value = draft.conversation_variables || []
    ragPipelineVariables.value = draft.rag_pipeline_variables || []
    workflowHash.value = draft.hash || null
    workflowFeatures.value = normalizeWorkflowFeatures(draft.features)
    workflowMode.value = mode
    await refreshPublishStatus()
  } catch (error) {
    loadError.value = error.response?.data?.message || error.message || '无法加载工作流草稿'
  } finally {
    loading.value = false
    if (loadedDraft) {
      await nextTick()
      canvasRef.value?.initializeDraft?.(loadedDraft)
    }
  }
}

async function persistDraftGraph(payload, saveAppId = appId.value) {
  const targetAppId = resolveDraftSaveAppId({
    payloadAppId: saveAppId,
    routeAppId: appId.value,
  })
  if (!targetAppId)
    throw new Error('缺少 appId，无法保存草稿')
  const body = {
    graph: payload.graph,
    features: normalizeWorkflowFeatures(workflowFeatures.value),
    environment_variables: payload.environmentVariables || [],
    conversation_variables: payload.conversationVariables || [],
    hash: workflowHash.value,
  }
  try {
    return await saveDraft(targetAppId, body)
  } catch (error) {
    if (error.response?.status !== 409)
      throw error
    const latest = await loadDraft(targetAppId, { silent: true })
    workflowHash.value = latest.hash || null
    workflowFeatures.value = normalizeWorkflowFeatures(latest.features || workflowFeatures.value)
    return saveDraft(targetAppId, { ...body, hash: workflowHash.value })
  }
}

async function handleSaveDraft(payload) {
  const silent = !!payload?.silent
  const saveAppId = resolveDraftSaveAppId({
    payloadAppId: payload?.appId,
    routeAppId: appId.value,
  })
  if (!saveAppId) {
    canvasRef.value?.markDraftSaveFailed?.()
    if (!silent)
      ElMessage.error('缺少 appId，无法保存草稿')
    return
  }
  try {
    const result = await persistDraftGraph(payload, saveAppId)
    workflowHash.value = result.hash || workflowHash.value
    if (result.features)
      workflowFeatures.value = normalizeWorkflowFeatures(result.features)

    if (payload.name && payload.name !== appDetail.value?.name && appDetail.value) {
      try {
        appDetail.value = await updateAppDetail(saveAppId, {
          name: payload.name,
          icon_type: appDetail.value.icon_type,
          icon: appDetail.value.icon,
          icon_background: appDetail.value.icon_background,
          description: appDetail.value.description || '',
          use_icon_as_answer_icon: appDetail.value.use_icon_as_answer_icon,
          max_active_requests: appDetail.value.max_active_requests,
        })
      } catch {
        if (!silent)
          ElMessage.warning('草稿已保存，但重命名失败')
      }
    }

    environmentVariables.value = sanitizeEnvironmentVariables(payload.environmentVariables)
    conversationVariables.value = payload.conversationVariables || []
    await nextTick()
    canvasRef.value?.markDraftSaved?.()
    if (!silent)
      ElMessage.success('草稿已保存到 Dify')
  } catch (error) {
    canvasRef.value?.markDraftSaveFailed?.()
    if (error.response?.status === 409)
      ElMessage.error('草稿已在其他窗口更新，请刷新后重试')
    else if (!silent)
      ElMessage.error(error.response?.data?.message || error.message || '保存失败')
    else
      ElMessage.error(error.response?.data?.message || error.message || '自动保存失败')
  }
}

async function handlePublish(payload) {
  if (publishing.value) return
  publishing.value = true
  try {
    if (payload?.graph)
      await persistDraftGraph(payload)
    await publishWorkflow(appId.value, {
      marked_name: payload?.markedName || '',
      marked_comment: payload?.releaseNotes || '',
    })
    hasPublishedVersion.value = true
    canvasRef.value?.markDraftSaved?.()
    canvasRef.value?.refreshVersionHistory?.()
    ElMessage.success('工作流已发布')
  } catch (error) {
    ElMessage.error(error.response?.data?.message || error.message || '发布失败')
  } finally {
    publishing.value = false
  }
}

async function handleSyncVariables({ environmentVariables: envVars, conversationVariables: convVars }) {
  try {
    await updateEnvironmentVariables(appId.value, sanitizeEnvironmentVariables(envVars || []))
    await updateConversationVariables(appId.value, convVars || [])
    environmentVariables.value = sanitizeEnvironmentVariables(envVars || [])
    conversationVariables.value = convVars || []
    ElMessage.success('变量已同步到 Dify')
  } catch (error) {
    try {
      await persistDraftGraph({
        graph: canvasRef.value?.exportGraph?.() || { nodes: [], edges: [] },
        environmentVariables: envVars,
        conversationVariables: convVars,
      })
      environmentVariables.value = sanitizeEnvironmentVariables(envVars || [])
      conversationVariables.value = convVars || []
      ElMessage.warning('专用变量接口失败，已回退写入草稿')
    } catch (fallbackError) {
      ElMessage.error(fallbackError.response?.data?.message || fallbackError.message || error.message || '变量同步失败')
    }
  }
}

async function handleRestoreVersion(workflowId) {
  try {
    await restoreWorkflowVersion(appId.value, workflowId)
    ElMessage.success('已恢复到草稿，正在重新加载…')
    await loadWorkflow()
  } catch (error) {
    ElMessage.error(error.response?.data?.message || error.message || '恢复版本失败')
    throw error
  }
}

function handleNewConversation() {
  clearConversation()
  ElMessage.success('已开始新对话')
}

async function handleSaveFeatures(nextFeatures) {
  if (!appId.value)
    return
  featuresSaving.value = true
  featuresError.value = ''
  const normalized = normalizeWorkflowFeatures(nextFeatures)
  try {
    await updateFeatures(appId.value, normalized)
    workflowFeatures.value = normalized
    ElMessage.success('功能已保存')
  }
  catch (error) {
    // Fallback: persist via full draft save (same fields Dify draft POST accepts).
    try {
      workflowFeatures.value = normalized
      const result = await persistDraftGraph({
        graph: canvasRef.value?.exportGraph?.() || { nodes: [], edges: [] },
        environmentVariables: environmentVariables.value,
        conversationVariables: conversationVariables.value,
      })
      workflowHash.value = result.hash || workflowHash.value
      if (result.features)
        workflowFeatures.value = normalizeWorkflowFeatures(result.features)
      ElMessage.success('功能已写入草稿')
    }
    catch (fallbackError) {
      featuresError.value = fallbackError.response?.data?.message
        || error.response?.data?.message
        || fallbackError.message
        || error.message
        || '保存功能失败'
      ElMessage.error(featuresError.value)
    }
  }
  finally {
    featuresSaving.value = false
  }
}

async function syncDraftBeforeRun() {
  const payload = canvasRef.value?.buildDraftPayload?.() || {
    graph: canvasRef.value?.exportGraph?.() || { nodes: [], edges: [] },
    environmentVariables: environmentVariables.value,
    conversationVariables: conversationVariables.value,
  }
  const result = await persistDraftGraph(payload)
  workflowHash.value = result.hash || workflowHash.value
  if (result.features)
    workflowFeatures.value = normalizeWorkflowFeatures(result.features)
  environmentVariables.value = sanitizeEnvironmentVariables(payload.environmentVariables || [])
  conversationVariables.value = payload.conversationVariables || []
  await nextTick()
  canvasRef.value?.markDraftSaved?.()
  return result
}

function handleWorkflowAssistApplied(payload) {
  if (payload?.hash)
    workflowHash.value = payload.hash
}

async function handleRunWorkflow(payload = {}) {
  if (debugState.isRunning)
    return
  canvasRef.value?.openDebugPreview?.()
  try {
    await startDebugRun({
      appId: appId.value,
      mode: workflowMode.value,
      inputs: payload.inputs || {},
      query: payload.query || '',
      files: Array.isArray(payload.files) ? payload.files : [],
      messageFiles: Array.isArray(payload.messageFiles) ? payload.messageFiles : [],
      features: workflowFeatures.value,
      syncDraft: syncDraftBeforeRun,
      onCanvasEvent: (canvasEvent) => canvasRef.value?.applyNodeRunState?.(canvasEvent),
    })
  }
  catch (error) {
    if (error?.name === 'AbortError')
      return
  }
  if (debugState.runError)
    ElMessage.error(debugState.runError)
}

async function handleRunNode(payload) {
  const nodeId = typeof payload === 'string' ? payload : payload?.nodeId
  const inputs = typeof payload === 'string' ? {} : (payload?.inputs || {})
  if (!nodeId)
    return
  try {
    await syncDraftBeforeRun()
    // Contrasts Dify singleNodeRun: sync POST, body { inputs }
    const result = await runNode(appId.value, nodeId, {
      inputs,
      query: payload?.query || '',
      files: payload?.files || [],
    })
    canvasRef.value?.applySingleNodeRunResult?.(nodeId, result)
  }
  catch (error) {
    canvasRef.value?.applySingleNodeRunResult?.(nodeId, {
      status: 'failed',
      error: error.response?.data?.message || error.message,
      inputs,
    })
    ElMessage.error(error.response?.data?.message || error.message || '节点运行失败')
  }
}

async function handleStopRun() {
  await stopDebugRun(appId.value)
  ElMessage.success('已发送停止指令')
}

watch(appId, (id) => {
  abortLocal()
  clearConversation()
  if (id)
    loadWorkflow()
  else
    loadApps()
}, { immediate: true })
</script>

<style scoped>
.page-container { width:100%; height:100%; position:relative; overflow:hidden; display:flex; align-items:stretch; justify-content:stretch; background:#f8fafc; }
.page-container.is-editing { display:block; background:#f4f5f7; }
.canvas-wrapper { width:100%; height:100%; position:relative; overflow:hidden; }
.home-panel {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: auto;
  padding: 28px 32px 40px;
  box-sizing: border-box;
  background: var(--af-page);
}
.page-header {
  max-width: 1440px;
  margin: 0 auto 24px;
}
.page-header h1 {
  margin: 0;
  color: var(--af-text-primary);
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.025em;
}
.page-header p {
  margin: 7px 0 0;
  color: var(--af-text-muted);
  font-size: 14px;
  line-height: 1.5;
}
.dsl-drop-overlay {
  position: absolute;
  inset: 4px;
  z-index: 20;
  border: 2px dashed var(--af-brand);
  border-radius: 16px;
  background: rgb(83 104 169 / 14%);
  pointer-events: none;
}
.studio-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  max-width: 1440px;
  margin: 0 auto 20px;
}
.toolbar-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.toolbar-actions { margin-left: auto; }
.filter-select { width: 120px; }
.sort-wrap {
  display: inline-flex;
  align-items: center;
  height: 32px;
  padding: 0 4px 0 10px;
  border-radius: 8px;
  border: 1px solid var(--af-border);
  background: var(--af-surface);
}
.sort-prefix {
  color: #98a2b3;
  font-size: 13px;
  white-space: nowrap;
}
.sort-select { width: 118px; }
.sort-select :deep(.el-select__wrapper) {
  box-shadow: none !important;
  background: transparent;
}
.search-input { width: 200px; max-width: 100%; }
.filter-chip { height: 32px; }
.app-grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 14px;
  max-width: 1440px;
  margin-right: auto;
  margin-left: auto;
}
.app-card-wrap {
  position: relative;
}
.app-card {
  width: 100%;
  min-height: 176px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  border: 1px solid var(--af-border);
  border-radius: var(--af-radius-lg);
  background: var(--af-surface);
  cursor: pointer;
  text-align: left;
  box-shadow: var(--af-shadow-sm);
  transition: border-color var(--af-transition), box-shadow var(--af-transition), transform var(--af-transition);
}
.app-card:hover:not(:disabled) { border-color: var(--af-brand-border); box-shadow: 0 6px 18px rgb(24 30 42 / 8%); transform: translateY(-2px); }
.app-card:active:not(:disabled) { transform: translateY(0) scale(.985); }
.app-card:disabled { opacity: 0.72; cursor: not-allowed; }
.card-more {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 2;
}
.more-btn {
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #667085;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}
.more-btn:hover {
  background: #f2f4f7;
  color: #101828;
}
.delete-copy,
.delete-label {
  margin: 0 0 12px;
  color: #667085;
  font-size: 14px;
  line-height: 1.6;
}
.delete-label strong {
  color: #101828;
}
.card-top { display: flex; align-items: flex-start; gap: 12px; }
.app-icon {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--af-text-primary);
  font-size: 20px;
  font-weight: 650;
  flex-shrink: 0;
  overflow: hidden;
}
.app-icon img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}
.card-title-block { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.card-title-block strong {
  color: var(--af-text-primary);
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mode-tag {
  width: fit-content;
  color: var(--af-text-muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}
.mode-tag[data-mode='advanced-chat'] { color: var(--af-brand-strong); }
.mode-tag[data-mode='workflow'] { color: #397d64; }
.card-desc {
  margin: 0;
  min-height: 36px;
  color: var(--af-text-muted);
  font-size: 12px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-tags { margin-top: auto; }
.tag-placeholder {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 8px;
  border: 1px dashed #d0d5dd;
  border-radius: 6px;
  color: #98a2b3;
  font-size: 12px;
}
.card-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  color: #98a2b3;
  font-size: 12px;
}
.dsl-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 28px;
  color: #98a2b3;
  font-size: 13px;
}
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}
.state-card {
  width: min(440px, calc(100% - 48px));
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 24px;
  border: 1px solid var(--af-border);
  border-radius: var(--af-radius-lg);
  background: var(--af-surface);
  box-shadow: var(--af-shadow-sm);
}
.state-card.inline { width: min(1440px, 100%); box-shadow: none; margin: 12px auto 0; }
.state-card .el-icon { align-self: center; font-size: 28px; color: var(--af-brand); }
.state-card h2, .state-card p { margin: 0; }
.state-card p { color: #667085; line-height: 1.6; }
.actions { display: flex; gap: 8px; }
.error-card h2 { color: #b42318; }
</style>

<style>
.danger-item {
  color: #d92d20 !important;
}
</style>
