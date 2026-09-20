<template>
  <div class="studio-page">
    <header class="page-header">
      <div>
        <RouterLink class="back-link" to="/integrations?tab=tools">← 返回工具授权</RouterLink>
        <h1>AI 工具插件生成器</h1>
        <p>会话持久化；同名插件可开多个独立对话；续聊时插件名锁定，可新增工具。</p>
      </div>
      <span v-if="status" class="status" :class="{ error: statusError }">{{ status }}</span>
    </header>

    <main class="studio-shell" :class="{ 'rail-collapsed': sessionRailCollapsed }">
      <SessionHistoryRail
        :sessions="sessions"
        :active-id="sessionId"
        :collapsed="sessionRailCollapsed"
        :disabled="agentRunning"
        @new="handleNewSession"
        @fork-pick="handleForkPick"
        @open="openSession"
        @rename="handleRenameSession"
        @delete="handleDeleteSession"
        @update:collapsed="sessionRailCollapsed = $event; localStorage.setItem('ai-tool-plugin-rail-collapsed', $event ? '1' : '0')"
      />

      <div class="split-main" :style="{ '--chat-ratio': `${chatRatio}%` }">
        <section class="panel chat-panel">
          <AgentChatPanel
            :form="form"
            :selected-model="selectedModel"
            :messages="chatMessages"
            :input="chatInput"
            :running="agentRunning"
            :plugin-locked="pluginLocked"
            :tool-names="toolNames"
            :identity-ready="identityReady"
            @update:selected-model="selectedModel = $event"
            @update:input="chatInput = $event"
            @patch-form="onPatchForm"
            @send="handleAgentTurn"
            @stop="handleStopAgent"
            @add-tool="handleAddToolMode"
          />
        </section>

        <div class="split-resizer" title="拖拽调整比例" @mousedown="startResize" />

        <section class="panel workspace-panel">
          <div class="workspace-toolbar">
            <div>
              <h2>插件文件</h2>
              <p>{{ filePaths.length ? `${filePaths.length} 个文件` : '生成或对话后可在此编辑' }}</p>
            </div>
            <div class="actions">
              <button type="button" class="secondary" :disabled="!filePaths.length || validating" @click="handleValidate">
                {{ validating ? '校验中…' : '校验文件' }}
              </button>
              <button
                type="button"
                class="primary"
                :disabled="!canPublishPlugin || publishing"
                @click="openPublishDialog"
              >
                {{ publishing ? '发布中…' : '发布插件' }}
              </button>
              <button
                v-if="canAskAgentToRepair"
                type="button"
                class="secondary"
                :disabled="agentRunning"
                @click="handleAskAgentToRepair"
              >
                让 Agent 修复
              </button>
              <button type="button" class="primary" :disabled="!filePaths.length || downloading" @click="handleDownload">
                {{ downloading ? '准备中…' : '下载 ZIP' }}
              </button>
            </div>
          </div>
          <p v-if="installedIdentifier" class="installed-identifier">
            已发布：{{ installedIdentifier }}
            <span v-if="installationId">（{{ installationId }}）</span>
          </p>
          <div v-if="toolNames.length" class="tool-bar">
            <button
              v-for="name in toolNames"
              :key="name"
              type="button"
              class="tool-chip"
              :class="{ active: name === form.toolName }"
              @click="switchActiveTool(name)"
            >
              {{ name }}
            </button>
          </div>

          <div v-if="filePaths.length" class="editor-layout">
            <nav class="file-tree" aria-label="插件文件">
              <button
                v-for="path in filePaths"
                :key="path"
                type="button"
                :class="{ active: selectedPath === path }"
                @click="selectedPath = path"
              >
                {{ path }}
              </button>
            </nav>
            <div class="editor">
              <div class="editor-title">{{ selectedPath }}</div>
              <textarea v-model="selectedContent" aria-label="文件内容" spellcheck="false" />
            </div>
          </div>
          <div v-else class="empty-state">填写左侧元数据后直接对话，Agent 会创建脚手架并迭代修改。</div>
        </section>
      </div>
    </main>

    <el-dialog
      v-model="sandboxOpen"
      title="发布插件"
      width="860px"
      destroy-on-close
      append-to-body
    >
      <ToolPluginSandbox
        v-if="sandboxPreviewTool"
        :preview-tool="sandboxPreviewTool"
        :can-publish="canPublishPlugin"
        :session-id="sessionId"
        :expected-revision="sessionRevision"
        @publish-start="publishing = true"
        @publish-result="handlePublishResult"
        @publish-end="publishing = false"
      />
      <p v-else class="empty-state">生成或修改后将显示工具沙箱预览。</p>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  agentTurnToolPluginStream,
  createToolPluginSession,
  deleteToolPluginSession,
  downloadToolPluginZip,
  forkToolPluginSession,
  getToolPluginSession,
  listToolPluginSessions,
  updateToolPluginSession,
  validateToolPlugin,
} from '@/features/integrations/api/difyToolPluginGeneratorApi.js'
import { useToolStore } from '@/features/integrations/state/useToolStore.js'
import { filesArrayToMap, filesMapToArray } from '../tool-plugin/fileTreeHelpers.js'
import {
  finishThinkingEvents,
  mergePersistedMessagesWithThinking,
  normalizeAgentMessagesForDisplay,
  upsertThinkingEvent,
  upsertToolEventMessage,
} from '../tool-plugin/agentEventHelpers.js'
import {
  isValidPluginIdentityName,
  isValidToolIdentityName,
  PLUGIN_IDENTITY_NAME_HINT,
  TOOL_IDENTITY_NAME_HINT,
} from '../tool-plugin/pluginIdentityHelpers.js'
import { enrichPreviewToolFromFiles } from '../tool-plugin/previewFromFiles.js'
import AgentChatPanel from '../tool-plugin/AgentChatPanel.vue'
import SessionHistoryRail from '../tool-plugin/SessionHistoryRail.vue'
import ToolPluginSandbox from '../tool-plugin/ToolPluginSandbox.vue'

const route = useRoute()
const router = useRouter()
const toolStore = useToolStore()
const form = reactive({
  author: '',
  pluginName: '',
  toolName: '',
  userPrompt: '',
  apiDoc: '',
})
const selectedModel = ref({
  provider: '',
  name: '',
  mode: 'chat',
  completion_params: {},
})
const files = ref({})
const previewTool = ref(null)
const selectedPath = ref('')
const status = ref('')
const statusError = ref(false)
const pluginStatus = ref('idle')
const installedIdentifier = ref('')
const installationId = ref('')
const validating = ref(false)
const publishing = ref(false)
const downloading = ref(false)
const agentRunning = ref(false)
const chatInput = ref('')
const chatMessages = ref([])
const sessions = ref([])
const sessionId = ref('')
const sessionRevision = ref(0)
const lastPublishDiagnostic = ref(null)
const sessionTitle = ref('')
const phase = ref('creating')
const toolNames = ref([])
const sandboxOpen = ref(false)
const pendingIntent = ref('')
const sessionRailCollapsed = ref(localStorage.getItem('ai-tool-plugin-rail-collapsed') === '1')
const chatRatio = ref(Number(localStorage.getItem('ai-tool-plugin-chat-ratio') || 38))
let abortController = null
let saveTimer = null
let resizing = false

const filePaths = computed(() => Object.keys(files.value))
const pluginLocked = computed(() => phase.value === 'editing')
const identityReady = computed(() => (
  isValidPluginIdentityName(form.author)
  && isValidPluginIdentityName(form.pluginName)
  && isValidToolIdentityName(form.toolName)
))
const canPublishPlugin = computed(() => (
  filePaths.value.length > 0
  && pluginStatus.value !== 'agent_running'
  && identityReady.value
  && Boolean(sessionId.value)
))
const canAskAgentToRepair = computed(() => (
  lastPublishDiagnostic.value?.error_type === 'plugin_runtime_error'
))
/** Always rebuild credentials/parameters from workspace files so sandbox is not stuck on stale preview_tool. */
const sandboxPreviewTool = computed(() =>
  enrichPreviewToolFromFiles(previewTool.value, files.value, { toolName: form.toolName }),
)
const selectedContent = computed({
  get: () => files.value[selectedPath.value] ?? '',
  set: (content) => {
    if (selectedPath.value) {
      files.value[selectedPath.value] = content
      pluginStatus.value = 'draft_ready'
      scheduleSave()
    }
  },
})

function onPatchForm({ key, value }) {
  if (pluginLocked.value && (key === 'author' || key === 'pluginName'))
    return
  form[key] = value
  if (key === 'toolName')
    refreshPreviewForTool(value)
  scheduleSave()
}

function selectedModelPayload() {
  const provider = selectedModel.value?.provider?.trim()
  const model = selectedModel.value?.name?.trim()
  if (!provider || !model)
    return {}
  return {
    model_provider: provider,
    model,
  }
}

function ensureIdentityFields() {
  if (!form.author?.trim() || !form.pluginName?.trim() || !form.toolName?.trim()) {
    status.value = '请填写作者、插件名称和工具名称。'
    statusError.value = true
    return false
  }
  if (!isValidPluginIdentityName(form.author) || !isValidPluginIdentityName(form.pluginName)) {
    status.value = `作者、插件名称${PLUGIN_IDENTITY_NAME_HINT}，请修正后再保存或对话。`
    statusError.value = true
    return false
  }
  if (!isValidToolIdentityName(form.toolName)) {
    status.value = `工具名称${TOOL_IDENTITY_NAME_HINT}，请修正后再保存或对话。`
    statusError.value = true
    return false
  }
  return true
}

function truncateTitle(text) {
  const cleaned = String(text || '').replace(/\s+/g, ' ').trim()
  if (!cleaned)
    return ''
  return cleaned.length > 40 ? `${cleaned.slice(0, 40)}…` : cleaned
}

function identityFieldsSavable() {
  const author = String(form.author || '').trim()
  const pluginName = String(form.pluginName || '').trim()
  const toolName = String(form.toolName || '').trim()
  if (!author && !pluginName && !toolName)
    return true
  if (author && !isValidPluginIdentityName(author))
    return false
  if (pluginName && !isValidPluginIdentityName(pluginName))
    return false
  if (toolName && !isValidToolIdentityName(toolName))
    return false
  return true
}

function filesPayload() {
  return { files: filesMapToArray(files.value) }
}

function isDraftName(name) {
  return /^__draft__/i.test(String(name || ''))
}

async function refreshSessions() {
  const result = await listToolPluginSessions({ includeHidden: true })
  sessions.value = result?.data || result || []
}

async function resetToBlankOrNext() {
  sessionId.value = ''
  sessionRevision.value = 0
  lastPublishDiagnostic.value = null
  sessionTitle.value = ''
  phase.value = 'creating'
  chatMessages.value = []
  files.value = {}
  previewTool.value = null
  selectedPath.value = ''
  toolNames.value = []
  pluginStatus.value = 'idle'
  installedIdentifier.value = ''
  installationId.value = ''
  await refreshSessions()
  const next = sessions.value[0]
  if (next)
    await openSession(next.id)
}

async function handleRenameSession(item) {
  try {
    const { value } = await ElMessageBox.prompt('请输入新的对话名称', '重命名对话', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: item.display_name || item.title || item.plugin_name || '',
      inputPlaceholder: '对话名称',
      inputAttrs: { maxlength: 80 },
      inputValidator: (input) => {
        const title = String(input || '').trim()
        if (!title)
          return '名称不能为空'
        if (title.length > 80)
          return '名称不能超过 80 个字符'
        return true
      },
    })
    const nextTitle = String(value || '').trim()
    const detail = await updateToolPluginSession(item.id, {
      expected_revision: item.revision,
      title: nextTitle,
    })
    if (item.id === sessionId.value) {
      sessionTitle.value = detail.title || nextTitle
      sessionRevision.value = detail.revision ?? sessionRevision.value
    }
    await refreshSessions()
    ElMessage.success('对话已重命名')
  }
  catch (error) {
    if (error === 'cancel' || error === 'close')
      return
    ElMessage.error(error.response?.data?.message || error.message || '重命名失败')
  }
}

async function handleDeleteSession(id) {
  try {
    await ElMessageBox.confirm('删除后无法恢复该对话与草稿文件，确定删除？', '删除对话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  }
  catch {
    return
  }
  try {
    await deleteToolPluginSession(id)
    ElMessage.success('已删除会话')
    if (id === sessionId.value)
      await resetToBlankOrNext()
    else
      await refreshSessions()
  }
  catch (error) {
    ElMessage.error(error.response?.data?.message || error.message || '删除失败')
  }
}

function applySessionDetail(detail) {
  sessionId.value = detail.id
  sessionRevision.value = detail.revision ?? 0
  lastPublishDiagnostic.value = detail.last_publish_diagnostic || null
  sessionTitle.value = detail.title || ''
  phase.value = detail.phase || 'creating'
  form.author = detail.author || ''
  form.pluginName = isDraftName(detail.plugin_name)
    ? ''
    : (detail.plugin_name || '')
  form.toolName = detail.active_tool_name || detail.tool_names?.[0] || ''
  toolNames.value = (detail.tool_names || []).filter(Boolean)
  chatMessages.value = normalizeAgentMessagesForDisplay(detail.messages)
  files.value = filesArrayToMap(detail.files || [])
  previewTool.value = enrichPreviewToolFromFiles(
    detail.preview_tool || null,
    files.value,
    { toolName: form.toolName },
  )
  selectedPath.value = Object.keys(files.value)[0] || ''
  installedIdentifier.value = detail.plugin_unique_identifier || ''
  installationId.value = detail.installation_id || ''
  pluginStatus.value = detail.plugin_status || (filePaths.value.length ? 'draft_ready' : 'idle')
  if (detail.model_provider && detail.model_name) {
    selectedModel.value = {
      ...selectedModel.value,
      provider: detail.model_provider,
      name: detail.model_name,
    }
  }
}

async function openSession(id) {
  const detail = await getToolPluginSession(id)
  applySessionDetail(detail)
  status.value = '已打开会话。'
  statusError.value = false
}

async function handleNewSession() {
  try {
    const detail = await createToolPluginSession({
      author: form.author || '',
      plugin_name: null,
    })
    await refreshSessions()
    applySessionDetail(detail)
    form.pluginName = ''
    form.toolName = ''
    sessionTitle.value = ''
    chatMessages.value = []
    files.value = {}
    previewTool.value = null
    phase.value = 'creating'
    status.value = '已新建对话（可填写插件名；同名插件可并存多个对话）。'
    statusError.value = false
  }
  catch (error) {
    status.value = error.response?.data?.message || error.message || '创建会话失败。'
    statusError.value = true
  }
}

function forkCandidates() {
  return sessions.value.filter(item => (
    !item.is_hidden
    && item.has_files
    && item.plugin_name
    && !isDraftName(item.plugin_name)
  ))
}

async function forkSessionFromSource(sourceId, { intent = '', title } = {}) {
  const detail = await forkToolPluginSession({
    source_session_id: sourceId,
    title: title || undefined,
  })
  await refreshSessions()
  applySessionDetail(detail)
  status.value = intent === 'add_tool'
    ? '已从已有插件复制源码，进入新增工具模式。'
    : '已从已有插件复制源码，可继续对话。'
  statusError.value = false
  if (intent === 'add_tool')
    handleAddToolMode()
  return detail
}

async function handleForkPick() {
  const candidates = forkCandidates()
  if (!candidates.length) {
    ElMessage.warning('暂无带草稿文件的插件会话，可先空白新建并生成插件。')
    return
  }
  // Prefer one row per plugin_name (latest)
  const byPlugin = new Map()
  for (const item of candidates) {
    if (!byPlugin.has(item.plugin_name))
      byPlugin.set(item.plugin_name, item)
  }
  const options = [...byPlugin.values()]
  const labels = options.map(item => `${item.plugin_name}（${item.display_name || item.title || item.id}）`)
  try {
    const { value } = await ElMessageBox.prompt(
      `选择要复制源码的插件（输入序号 1-${options.length}）：\n${labels.map((label, index) => `${index + 1}. ${label}`).join('\n')}`,
      '从已有插件开新对话',
      {
        inputPattern: new RegExp(`^[1-${options.length}]$`),
        inputErrorMessage: `请输入 1-${options.length}`,
        confirmButtonText: '复制并打开',
        cancelButtonText: '取消',
      },
    )
    const picked = options[Number(value) - 1]
    if (!picked)
      return
    await forkSessionFromSource(picked.id)
  }
  catch {
    // cancelled
  }
}

async function clearBootstrapQuery() {
  const nextQuery = { ...route.query }
  delete nextQuery.session
  delete nextQuery.fork
  delete nextQuery.intent
  delete nextQuery.author
  delete nextQuery.plugin
  await router.replace({ path: route.path, query: nextQuery })
}

async function applyBootstrapQuery() {
  const sessionQuery = String(route.query.session || '').trim()
  const forkQuery = String(route.query.fork || '').trim()
  const intentQuery = String(route.query.intent || '').trim()
  const authorQuery = String(route.query.author || '').trim()
  const pluginQuery = String(route.query.plugin || '').trim()

  if (sessionQuery) {
    await openSession(sessionQuery)
    await clearBootstrapQuery()
    return true
  }
  if (forkQuery) {
    await forkSessionFromSource(forkQuery, { intent: intentQuery })
    await clearBootstrapQuery()
    return true
  }
  if (authorQuery || pluginQuery) {
    await handleNewSession()
    if (authorQuery)
      form.author = authorQuery
    if (pluginQuery)
      form.pluginName = pluginQuery
    status.value = '已预填插件身份。当前无 Studio 草稿源码，请对话生成或从其它带草稿会话 fork。'
    statusError.value = false
    await clearBootstrapQuery()
    return true
  }
  return false
}

function scheduleSave() {
  if (!sessionId.value)
    return
  if (agentRunning.value)
    return
  if (!identityFieldsSavable())
    return
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    saveSession().catch(() => {})
  }, 800)
}

async function saveSession(extra = {}) {
  if (!sessionId.value)
    return null
  if (!identityFieldsSavable())
    return null
  clearTimeout(saveTimer)
  saveTimer = null
  const payload = {
    expected_revision: sessionRevision.value,
    author: form.author,
    plugin_name: form.pluginName || undefined,
    active_tool_name: form.toolName,
    tool_names: toolNames.value,
    files: filesMapToArray(files.value),
    preview_tool: previewTool.value,
    model_provider: selectedModel.value?.provider || undefined,
    model_name: selectedModel.value?.name || undefined,
    title: sessionTitle.value || undefined,
    ...extra,
  }
  try {
    const detail = await updateToolPluginSession(sessionId.value, payload)
    sessionRevision.value = detail.revision ?? sessionRevision.value
    phase.value = detail.phase || phase.value
    toolNames.value = detail.tool_names || toolNames.value
    if (detail.title)
      sessionTitle.value = detail.title
    await refreshSessions()
    return detail
  }
  catch (error) {
    const message = error.response?.status === 409
      ? '该会话已在其他标签页更新，请重新打开后再编辑。'
      : (error.response?.data?.message || error.message || '保存会话失败')
    ElMessage.error(message)
    throw error
  }
}

function refreshPreviewForTool(toolName) {
  if (!previewTool.value)
    return
  previewTool.value = {
    ...previewTool.value,
    tool_name: toolName,
  }
}

async function switchActiveTool(name) {
  form.toolName = name
  refreshPreviewForTool(name)
  scheduleSave()
}

function handleAddToolMode() {
  form.toolName = ''
  pendingIntent.value = 'add_tool'
  status.value = '已进入新增工具模式：插件名锁定，请填写新工具名后让 Agent 创建。'
  statusError.value = false
}

function applyFilesFromEvent(fileList) {
  if (!fileList?.length)
    return
  files.value = filesArrayToMap(fileList)
  if (!selectedPath.value || !(selectedPath.value in files.value))
    selectedPath.value = Object.keys(files.value)[0] || ''
  toolNames.value = Object.keys(files.value)
    .filter(path => path.startsWith('tools/') && (path.endsWith('.yaml') || path.endsWith('.yml')))
    .map(path => path.replace(/^tools\//, '').replace(/\.ya?ml$/, ''))
    .filter(Boolean)
  previewTool.value = enrichPreviewToolFromFiles(previewTool.value, files.value, {
    toolName: form.toolName || toolNames.value[0] || '',
  })
}

function appendAssistant(content) {
  const last = chatMessages.value[chatMessages.value.length - 1]
  if (last?.role === 'assistant' && !last.tool_calls?.length) {
    last.content = content
    return
  }
  chatMessages.value.push({ role: 'assistant', content })
}

function handleStreamEvent(event) {
  if (!event?.event)
    return
  if (Number.isInteger(event.revision))
    sessionRevision.value = event.revision
  if (event.event === 'status') {
    if (event.phase === 'thinking')
      status.value = 'Agent 思考中…'
    else if (event.phase === 'tool')
      status.value = `正在执行工具：${event.tool || ''}`.trim()
    return
  }
  if (event.event === 'thinking') {
    upsertThinkingEvent(chatMessages.value, event)
    return
  }
  if (event.event === 'assistant' && event.content)
    appendAssistant(event.content)
  if (event.event === 'tool_call') {
    upsertToolEventMessage(chatMessages.value, event)
  }
  if (event.event === 'tool_result') {
    finishThinkingEvents(chatMessages.value, event.call_id)
    upsertToolEventMessage(chatMessages.value, event)
  }
  if (event.event === 'files') {
    applyFilesFromEvent(event.files)
    if (event.preview_tool)
      previewTool.value = event.preview_tool
    pluginStatus.value = 'draft_ready'
    phase.value = 'editing'
  }
  if (event.event === 'cancelled') {
    finishThinkingEvents(chatMessages.value)
    applyFilesFromEvent(event.files)
    if (event.preview_tool)
      previewTool.value = event.preview_tool
    chatMessages.value.push({ role: 'system', content: '已停止本轮 Agent。' })
    status.value = '已停止。'
  }
  if (event.event === 'error') {
    finishThinkingEvents(chatMessages.value)
    status.value = event.message || 'Agent 执行失败。'
    statusError.value = true
    chatMessages.value.push({ role: 'system', content: status.value })
  }
}

async function ensureSession() {
  if (sessionId.value)
    return true
  await handleNewSession()
  return Boolean(sessionId.value)
}

function handleStopAgent() {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
}

async function handleAgentTurn() {
  if (!ensureIdentityFields() || !chatInput.value.trim())
    return
  const model = selectedModelPayload()
  if (!model.model_provider || !model.model) {
    status.value = '请选择支持 Function Calling 的模型。'
    statusError.value = true
    return
  }
  if (!await ensureSession())
    return
  const message = chatInput.value.trim()
  if (!sessionTitle.value)
    sessionTitle.value = truncateTitle(message)
  try {
    const saved = await saveSession({
      plugin_name: form.pluginName,
      author: form.author,
      title: sessionTitle.value || undefined,
    })
    if (!saved)
      return
    agentRunning.value = true
    pluginStatus.value = 'agent_running'
    status.value = 'Agent 正在处理草稿…'
    statusError.value = false
    chatMessages.value.push({ role: 'user', content: message })
    chatInput.value = ''
    abortController = new AbortController()
    const payload = {
      message,
      session_id: sessionId.value,
      expected_revision: sessionRevision.value,
      ...model,
    }
    if (pendingIntent.value) {
      payload.intent = pendingIntent.value
      pendingIntent.value = ''
    }

    const done = await agentTurnToolPluginStream(payload, {
      signal: abortController.signal,
      onEvent: handleStreamEvent,
    })

    if (done?.files)
      applyFilesFromEvent(done.files)
    if (done?.preview_tool)
      previewTool.value = done.preview_tool
    if (done?.messages) {
      finishThinkingEvents(chatMessages.value)
      chatMessages.value = mergePersistedMessagesWithThinking(
        [...(saved.messages || []), ...done.messages],
        chatMessages.value,
      )
    }
    if (Number.isInteger(done?.revision))
      sessionRevision.value = done.revision

    if (done?.cancelled) {
      pluginStatus.value = filePaths.value.length ? 'draft_ready' : 'idle'
      return
    }
    if (done?.validation_errors?.length) {
      pluginStatus.value = filePaths.value.length ? 'draft_ready' : 'idle'
      status.value = done.validation_errors.join('；')
      statusError.value = true
    }
    else {
      pluginStatus.value = filePaths.value.length ? 'draft_ready' : 'idle'
      if (!statusError.value)
        status.value = 'Agent 已更新草稿，请点击「发布插件」。'
    }
    phase.value = filePaths.value.length ? 'editing' : phase.value
    await refreshSessions()
  }
  catch (error) {
    finishThinkingEvents(chatMessages.value)
    if (error?.name === 'AbortError') {
      pluginStatus.value = filePaths.value.length ? 'draft_ready' : 'idle'
      status.value = '已停止。'
      return
    }
    pluginStatus.value = filePaths.value.length ? 'draft_ready' : 'idle'
    const messageText = error.data?.message || error.message || 'Agent 执行失败。'
    status.value = /timeout/i.test(messageText)
      ? 'Agent 执行超时。可缩短需求后重试，或点停止后继续对话。'
      : messageText
    statusError.value = true
    chatMessages.value.push({ role: 'system', content: status.value })
  }
  finally {
    agentRunning.value = false
    abortController = null
  }
}

async function validateFiles({ notify = true } = {}) {
  validating.value = true
  try {
    const result = await validateToolPlugin(filesPayload())
    if (!result.valid) {
      status.value = (result.errors || []).join('；') || '插件文件校验失败。'
      statusError.value = true
      return false
    }
    status.value = '插件文件校验通过。'
    statusError.value = false
    if (notify)
      ElMessage.success('插件文件校验通过')
    return true
  }
  catch (error) {
    status.value = error.message || '插件文件校验失败。'
    statusError.value = true
    return false
  }
  finally {
    validating.value = false
  }
}

async function handleValidate() {
  await validateFiles()
}

async function handlePublishResult(result) {
  if (Number.isInteger(result?.revision))
    sessionRevision.value = result.revision
  if (result && 'plugin_unique_identifier' in result)
    installedIdentifier.value = result.plugin_unique_identifier || ''
  if (result && 'installation_id' in result)
    installationId.value = result.installation_id || ''
  lastPublishDiagnostic.value = result?.diagnostic || null
  if (result?.ok) {
    pluginStatus.value = 'published'
    const direct = result.publish_mode === 'direct'
    status.value = direct ? '当前草稿已直接发布（未执行真实 API 测试）。' : '当前草稿已测试并发布。'
    statusError.value = false
    await toolStore.fetchTools(true)
    await refreshSessions()
    ElMessage.success(direct ? '插件已直接发布' : '插件已测试并发布')
    return
  }

  pluginStatus.value = 'draft_ready'
  status.value = result?.diagnostic?.message || '发布失败，草稿已保留。'
  statusError.value = true
  if (result?.status === 'rollback_failed')
    ElMessage.error('发布失败且旧版本未能恢复，请先检查插件状态再重试。')
  else if (result?.diagnostic?.error_type === 'session_conflict')
    ElMessage.error('该会话已在其他标签页更新，请重新打开后再发布。')
  else if (result?.diagnostic?.error_type === 'credential_error')
    ElMessage.warning('凭据无效或缺失，请修正凭据后重新发布。')
  else if (result?.diagnostic?.error_type === 'parameter_error')
    ElMessage.warning('测试参数无效，请修正参数后重新发布。')
  else
    ElMessage.warning('发布失败，草稿已保留，可让 Agent 根据脱敏诊断修复。')
  await refreshSessions()
}

async function openPublishDialog() {
  if (!canPublishPlugin.value)
    return
  try {
    const saved = await saveSession()
    if (saved)
      sandboxOpen.value = true
  }
  catch {
    // saveSession already reports revision conflicts and validation errors
  }
}

function handleAskAgentToRepair() {
  pendingIntent.value = 'repair_last_publish'
  chatInput.value = '请根据上一次发布失败的脱敏诊断修复当前插件草稿。'
  handleAgentTurn()
}

async function handleDownload() {
  downloading.value = true
  try {
    if (!await validateFiles({ notify: false }))
      return
    const blob = await downloadToolPluginZip({
      plugin_name: form.pluginName,
      ...filesPayload(),
    })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${form.pluginName || 'tool-plugin'}.zip`
    anchor.click()
    URL.revokeObjectURL(url)
    status.value = '插件 ZIP 已下载。'
    statusError.value = false
  }
  catch (error) {
    status.value = error.message || '插件下载失败。'
    statusError.value = true
  }
  finally {
    downloading.value = false
  }
}

function startResize(event) {
  resizing = true
  const startX = event.clientX
  const startRatio = chatRatio.value
  const onMove = (moveEvent) => {
    if (!resizing)
      return
    const delta = moveEvent.clientX - startX
    const next = Math.min(70, Math.max(24, startRatio + (delta / window.innerWidth) * 100))
    chatRatio.value = next
  }
  const onUp = () => {
    resizing = false
    localStorage.setItem('ai-tool-plugin-chat-ratio', String(chatRatio.value))
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

onMounted(async () => {
  try {
    await refreshSessions()
    const bootstrapped = await applyBootstrapQuery()
    if (!bootstrapped && sessions.value[0]?.id)
      await openSession(sessions.value[0].id)
  }
  catch (error) {
    status.value = error.message || '加载会话失败。'
    statusError.value = true
  }
})

onUnmounted(() => {
  clearTimeout(saveTimer)
})

watch(chatMessages, () => scheduleSave(), { deep: true })
</script>

<style scoped>
.studio-page {
  --ink: #25272c;
  --body: #505762;
  --muted: #737b87;
  --hairline: #dfe2e7;
  --canvas: #f6f7f9;
  --surface: #ffffff;
  --primary: #5368a9;
  --primary-active: #43558d;
  --error: #d92d20;
  --success: #079455;
  --font: var(--font-sans);

  box-sizing: border-box;
  height: 100%;
  min-height: 0;
  padding: 16px 20px;
  background: var(--canvas);
  color: var(--ink);
  font-family: var(--font);
  display: flex;
  flex-direction: column;
}
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.page-header h1 {
  margin: 6px 0 0;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.11px;
}
.page-header p { margin: 6px 0 0; color: var(--body); font-size: 13px; }
.back-link { color: var(--muted); font-size: 12px; text-decoration: none; }
.back-link:hover { color: var(--ink); }
.status {
  max-width: 46%;
  border-radius: 8px;
  border: 1px solid var(--hairline);
  background: var(--surface);
  padding: 8px 10px;
  color: var(--success);
  font-size: 12px;
}
.status.error { color: var(--error); }
.studio-shell {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 12px;
}
.studio-shell.rail-collapsed {
  grid-template-columns: 52px minmax(0, 1fr);
}
.split-main {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(240px, var(--chat-ratio)) 6px minmax(0, 1fr);
  gap: 0;
}
.split-resizer {
  cursor: col-resize;
  background: linear-gradient(var(--hairline), var(--hairline)) center/1px 100% no-repeat;
}
.split-resizer:hover { background-color: rgb(83 104 169 / 12%); }
.panel {
  border: 1px solid var(--hairline);
  border-radius: 12px;
  background: var(--surface);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.chat-panel { display: flex; flex-direction: column; }
.panel h2 { margin: 0; font-size: 15px; font-weight: 600; }
button {
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  font-family: var(--font);
  font-weight: 550;
  cursor: pointer;
}
button:disabled { cursor: not-allowed; opacity: .55; }
.primary { border: 0; background: var(--primary); color: #fff; }
.primary:hover:not(:disabled) { background: var(--primary-active); }
.primary:active:not(:disabled), .secondary:active:not(:disabled) { transform: scale(.98); }
.primary:focus-visible, .secondary:focus-visible, .tool-chip:focus-visible { outline: 3px solid rgb(83 104 169 / 20%); outline-offset: 1px; }
.secondary {
  border: 1px solid var(--hairline);
  background: var(--surface);
  color: var(--ink);
}
.workspace-panel { display: flex; flex-direction: column; overflow: hidden; }
.workspace-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid var(--hairline);
  flex-shrink: 0;
}
.workspace-toolbar p { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
.installed-identifier {
  margin: 0;
  border-bottom: 1px solid var(--hairline);
  padding: 8px 16px;
  color: var(--success);
  font-size: 12px;
}
.tool-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--hairline);
}
.tool-chip {
  border: 1px solid var(--hairline);
  border-radius: 999px;
  background: var(--surface);
  color: var(--muted);
  font-size: 12px;
  padding: 4px 10px;
}
.tool-chip.active {
  border-color: var(--primary);
  background: #eef0f8;
  color: var(--primary);
  font-weight: 600;
}
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.editor-layout {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  flex: 1;
  min-height: 0;
}
.file-tree {
  overflow: auto;
  border-right: 1px solid var(--hairline);
  background: var(--canvas);
}
.file-tree button {
  display: block;
  width: 100%;
  overflow: hidden;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--body);
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-tree button:hover,
.file-tree button.active {
  background: rgb(38 37 30 / 4%);
  color: var(--ink);
}
.editor { display: flex; min-width: 0; flex-direction: column; min-height: 0; }
.editor-title {
  padding: 9px 12px;
  border-bottom: 1px solid var(--hairline);
  color: var(--muted);
  font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.editor textarea {
  flex: 1;
  min-height: 0;
  border: 0;
  border-radius: 0;
  padding: 14px;
  font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  resize: none;
  width: 100%;
  box-sizing: border-box;
  color: var(--ink);
  background: var(--surface);
}
.empty-state {
  display: grid;
  flex: 1;
  place-items: center;
  color: var(--muted);
  font-size: 13px;
  padding: 24px;
}
@media (max-width: 1100px) {
  .studio-shell { grid-template-columns: 1fr; overflow: auto; }
  .split-main { grid-template-columns: 1fr; }
  .split-resizer { display: none; }
}
</style>
