<template>
  <aside
    class="workflow-assist-dock"
    :style="dockStyle"
    :aria-label="copy.title"
    :aria-busy="applying || recoveryState === 'loading'"
  >
    <div
      class="dock-resize-handle"
      role="separator"
      :aria-label="copy.resize"
      aria-orientation="vertical"
      :aria-valuenow="assistStore.panelWidth"
      aria-valuemin="360"
      aria-valuemax="560"
      tabindex="0"
      @pointerdown="startDockResize"
      @keydown="resizeDockByKeyboard"
    />

    <header class="dock-header">
      <div class="dock-title">
        <h2>{{ copy.title }}</h2>
        <p>{{ appMode === 'advanced-chat' ? copy.chatflowSubtitle : copy.workflowSubtitle }}</p>
      </div>
      <div class="dock-header-actions">
        <button type="button" :title="copy.newConversation" :aria-label="copy.newConversation" @click="newConversation">＋</button>
        <button
          type="button"
          :title="copy.history"
          :aria-label="copy.history"
          :aria-expanded="historyOpen"
          :aria-controls="historyRegionId"
          @click="historyOpen = !historyOpen"
        >☰</button>
        <button type="button" :title="copy.close" :aria-label="copy.close" @click="handleClose">×</button>
      </div>
    </header>

    <section v-if="historyOpen" :id="historyRegionId" class="conversation-history" :aria-label="copy.history">
      <p v-if="historyLoading" role="status">{{ copy.loading }}</p>
      <div
        v-for="conversation in conversations"
        :key="conversation.id"
        class="history-item"
        :class="{ active: String(conversation.id) === conversationId }"
      >
        <form
          v-if="renamingConversationId === String(conversation.id)"
          class="history-rename"
          @submit.prevent="commitRename(conversation)"
        >
          <input
            ref="renameInput"
            v-model="renameDraft"
            class="history-rename-input"
            maxlength="255"
            :aria-label="copy.renameConversation"
            @keydown.esc.prevent="cancelRename"
            @blur="commitRename(conversation)"
          >
        </form>
        <button
          v-else
          type="button"
          class="history-row"
          :aria-current="String(conversation.id) === conversationId ? 'true' : undefined"
          @click="selectConversation(conversation.id)"
          @dblclick.stop="startRename(conversation)"
        >
          <span class="history-title">{{ conversation.title || copy.untitledConversation }}</span>
          <time
            v-if="formatConversationTimestamp(conversation.updated_at)"
            class="history-time"
            :datetime="conversation.updated_at"
          >{{ formatConversationTimestamp(conversation.updated_at) }}</time>
        </button>
        <button
          v-if="renamingConversationId !== String(conversation.id)"
          type="button"
          class="history-rename-btn"
          :title="copy.renameConversation"
          :aria-label="copy.renameConversation"
          :disabled="renamingBusy"
          @click.stop="startRename(conversation)"
        >✎</button>
        <button
          type="button"
          class="history-delete"
          :title="copy.deleteConversation"
          :aria-label="copy.deleteConversation"
          :disabled="deletingConversationId === String(conversation.id)"
          @click.stop="deleteConversation(conversation)"
        >×</button>
      </div>
      <p v-if="!historyLoading && !conversations.length">{{ copy.noConversations }}</p>
    </section>

    <div v-if="recoveryState !== 'ready'" class="recovery-notice" role="status" aria-live="polite">
      <p>{{ recoveryState === 'loading' ? copy.restoringHistory : recoveryState === 'auth_required' ? copy.authenticationRequired : copy.historyRecoveryFailed }}</p>
      <button v-if="recoveryState === 'error'" type="button" @click="retryRecovery">{{ copy.retryHistory }}</button>
      <button v-if="recoveryState === 'auth_required'" type="button" @click="loginToRestore">{{ copy.signInAgain }}</button>
    </div>

    <AssistMessageList
      :messages="messages"
      :errors="session.errors"
      :warnings="session.warnings"
      :retryable="session.retryable && recoveryState === 'ready'"
      :disabled="recoveryState !== 'ready'"
      :language="language"
      @answer-clarification="answerClarification"
      @retry="assistController.retryFailedStep"
      @switch-model="focusModelSelector"
    />

    <p v-if="candidateStale" class="apply-notice">{{ copy.staleApplyNotice }}</p>
    <section
      v-if="contractUi.visible"
      class="contract-report-card"
      :class="`is-${contractUi.level}`"
      :aria-label="copy.contractValidationTitle"
    >
      <div class="contract-report-header">
        <strong>{{ copy.contractValidationTitle }}</strong>
        <span>{{ contractLevelCopy }}</span>
      </div>
      <p>{{ contractSummaryCopy }}</p>
      <ul v-if="contractUi.issues.length">
        <li v-for="check in contractUi.issues" :key="check.id">
          <strong>{{ contractCategoryCopy(check.category) }}:</strong>
          {{ check.detail }}
        </li>
      </ul>
    </section>
    <section v-if="applyUi.visible" class="apply-card" role="group" :aria-label="copy.applyReady">
      <p>{{ applying ? copy.applying : copy.applyReady }}</p>
      <button
        type="button"
        :disabled="applyUi.disabled || recoveryState !== 'ready'"
        :aria-busy="applying"
        @click="apply"
      >
        {{ applying ? copy.applying : copy.apply }}
      </button>
    </section>
    <p v-if="applyNotice" class="apply-notice">{{ applyNotice }}</p>
    <p class="assist-status-announcement visually-hidden" role="status" aria-live="polite" aria-atomic="true">
      {{ statusAnnouncement }}
    </p>

    <AssistComposer
      ref="composerRef"
      :disabled="applying || recoveryState !== 'ready'"
      :running="session.phase === AssistPhase.running"
      :awaiting-clarification="session.phase === AssistPhase.waiting_user"
      :language="language"
      :model-value="assistStore.selectedModel"
      :target-nodes="targetNodes"
      :current-graph="currentGraph"
      @update:model-value="assistStore.setSelectedModel"
      @add-target-node="addTargetNodes([$event.id])"
      @remove-target-node="removeTargetNode"
      @send="submitMessage"
      @cancel="assistController.stopActiveTurn"
    />
  </aside>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  createWorkflowAssistConversation,
  deleteWorkflowAssistConversation,
  patchWorkflowAssistConversationTitle,
  getWorkflowAssistCandidate,
  getWorkflowAssistConversation,
  getWorkflowAssistConversations,
  getWorkflowAssistRuns,
  getWorkflowAssistTimeline,
  postWorkflowAssistApply,
  postWorkflowAssistRunAbort,
  postWorkflowAssistRunRetry,
  postWorkflowAssistTurn,
  streamWorkflowAssistRunEvents,
} from '@/features/workflow/api/difyWorkflowAssistApi.js'
import { useWorkflowAssistStore } from '@/stores/useWorkflowAssistStore.js'
import { AssistPhase, createAssistSession, reduceAssist } from './assistStateMachine.js'
import { assistErrorsFromAxios } from './assistErrors.js'
import { assistCopy, detectRecoveredAssistLanguage, formatAssistCopy } from './assistLanguage.js'
import { insertSelectedNodeMentions } from './assistMentions.js'
import { formatAssistConversationTimestamp } from './assistConversationHistory.js'
import { createAssistStatusAnnouncement } from './assistLiveAnnouncement.js'
import AssistComposer from './AssistComposer.vue'
import AssistMessageList from './AssistMessageList.vue'
import { useWorkflowAssistController } from './useWorkflowAssistController.js'
import {
  applyWorkflowAssistCandidate,
  isPreviewableAssistGraph,
  nextConversationIdAfterDelete,
  normalizeConversationTitle,
  workflowAssistApplyPresentation,
  workflowContractReportPresentation,
} from './workflowAssistUx.js'

const RUN_STATUS_COPY_KEYS = Object.freeze({
  'queued': 'statusRunQueued',
  'running': 'statusRunRunning',
  'waiting_user': 'statusRunWaitingUser',
  'done': 'statusRunDone',
  'failed': 'statusRunFailed',
  'error': 'statusRunError',
  'aborted': 'statusRunAborted',
  'turn_complete': 'statusRunTurnComplete',
})

const APPLY_STATUS_COPY_KEYS = Object.freeze({
  'ready': 'statusApplyReady',
  'applying': 'statusApplyApplying',
  'applied': 'statusApplyApplied',
  'conflict': 'statusApplyConflict',
  'failed': 'statusApplyFailed',
})

const props = defineProps({
  appId: { type: [String, Number], required: true },
  appMode: { type: String, default: 'workflow' },
  currentGraph: { type: Object, default: () => ({ nodes: [], edges: [] }) },
  serverDraftHash: { type: String, default: '' },
  syncDraftIfDirty: { type: Function, required: true },
})

const emit = defineEmits(['applied', 'candidate-preview', 'close'])
const assistStore = useWorkflowAssistStore()
const session = ref(createAssistSession())
const messages = ref([])
const lastInstruction = ref('')
const conversationId = ref('')
const conversations = ref([])
const candidate = ref(null)
const historyOpen = ref(false)
const historyLoading = ref(false)
const recoveryState = ref('loading')
const deletingConversationId = ref('')
const renamingConversationId = ref('')
const renameDraft = ref('')
const renameInput = ref(null)
const renamingBusy = ref(false)
const applying = ref(false)
const applyNotice = ref('')
const statusAnnouncement = ref('')
const language = ref('zh-Hans')
const composerRef = ref(null)
const copy = computed(() => assistCopy(language.value))
const historyRegionId = computed(() => `workflow-assist-history-${String(props.appId).replace(/[^a-zA-Z0-9_-]/g, '-')}`)
const dockStyle = computed(() => ({ width: `${assistStore.panelWidth}px` }))
const candidateStale = computed(() => {
  const baseHash = candidate.value?.base_hash
  const currentHash = props.serverDraftHash
  return Boolean(baseHash && currentHash && baseHash !== currentHash)
})
const contractUi = computed(() => workflowContractReportPresentation(candidate.value))
const contractLevelCopy = computed(() => copy.value.contractValidationLevels[contractUi.value.level])
const contractSummaryCopy = computed(() => formatAssistCopy(copy.value.contractValidationSummary, contractUi.value.summary))
function contractCategoryCopy(category) {
  return copy.value.contractValidationCategories[category] || copy.value.contractValidationCategories.requirement
}
const applyUi = computed(() => {
  const presentation = workflowAssistApplyPresentation(
    candidate.value,
    props.appMode,
    applying.value,
  )
  if (!candidateStale.value)
    return presentation
  return {
    ...presentation,
    eligible: false,
    disabled: true,
    visible: presentation.visible || Boolean(candidate.value?.graph),
  }
})
const statusLive = createAssistStatusAnnouncement({
  onAnnounce: text => { statusAnnouncement.value = text },
})
const targetNodes = computed(() => {
  const byId = new Map((props.currentGraph?.nodes || []).map(node => [String(node.id), node]))
  return session.value.targetNodeIds.map((id) => {
    const node = byId.get(String(id))
    return node ? {
      id: String(id),
      title: node.data?.title || node.title || node.data?.type || node.type || String(id),
      type: node.data?.type || node.type || '',
    } : null
  }).filter(Boolean)
})

function unwrapItems(payload) {
  if (Array.isArray(payload))
    return payload
  return payload?.items || payload?.conversations || payload?.data || []
}

function unwrapConversation(payload) {
  return payload?.conversation || payload?.data || payload || null
}

function announceRunStatus(status) {
  const normalized = String(status || '')
  const copyKey = RUN_STATUS_COPY_KEYS[normalized]
  if (copyKey)
    statusLive.update('run', normalized, copy.value[copyKey])
}

function announceApplyStatus(status) {
  const normalized = String(status || '')
  const copyKey = APPLY_STATUS_COPY_KEYS[normalized]
  if (copyKey)
    statusLive.update('apply', normalized, copy.value[copyKey])
}

function announceRunFacts(facts) {
  const run = facts?.active_run || facts?.latest_run
  announceRunStatus(run?.status)
}

function reconcileRunFacts(facts) {
  const result = assistStore.reconcileAppCoordination(props.appId, facts)
  announceRunFacts(facts)
  return result
}

function dispatch(event) {
  if (event?.type === 'RESET') {
    statusLive.reset('run')
    statusLive.reset('apply')
    statusAnnouncement.value = ''
  }
  session.value = reduceAssist(session.value, event, language.value)
}

function formatConversationTimestamp(value) {
  return formatAssistConversationTimestamp(value, language.value)
}

async function loadConversations() {
  historyLoading.value = true
  try {
    const payload = await getWorkflowAssistConversations(props.appId, { limit: 50 })
    conversations.value = unwrapItems(payload)
    return { items: conversations.value }
  }
  finally {
    historyLoading.value = false
  }
}

async function selectConversationRecord(id, isCurrent = () => true) {
  if (!id || !isCurrent())
    return false
  conversationId.value = String(id)
  candidate.value = null
  messages.value = []
  dispatch({ type: 'RESET' })
  reconcileRunFacts({ conversation_id: conversationId.value })
  historyOpen.value = false
  return true
}

async function createConversationRecord(isCurrent = () => true) {
  const created = unwrapConversation(await createWorkflowAssistConversation(props.appId, {}))
  if (!created?.id || !isCurrent())
    return false
  conversations.value = [created, ...conversations.value.filter(item => item.id !== created.id)]
  return selectConversationRecord(created.id, isCurrent)
}

const assistController = useWorkflowAssistController({
  state: session,
  messages,
  lastInstruction,
  conversationId,
  language,
  hasSelectedModel: () => assistStore.hasSelectedModel,
  onModelRequired(nextInstruction) {
    language.value = detectRecoveredAssistLanguage([...messages.value, { role: 'user', text: nextInstruction }])
    session.value = {
      ...session.value,
      errors: [{ detail: copy.value.modelRequired }],
    }
  },
  syncDraftIfDirty: () => props.syncDraftIfDirty(),
  async prepareInstruction(nextInstruction, isCurrent) {
    language.value = detectRecoveredAssistLanguage([...messages.value, { role: 'user', text: nextInstruction }])
    applyNotice.value = ''
    if (conversationId.value)
      return { accepted: isCurrent(), conversationId: conversationId.value }
    const created = await createConversationRecord(isCurrent)
    return {
      accepted: created !== false,
      conversationId: created === false ? '' : conversationId.value,
    }
  },
  buildPayload: turn => ({
    message: turn.message,
    ...(turn.live_acceptance_request_id ? { live_acceptance_request_id: turn.live_acceptance_request_id } : {}),
    mode: props.appMode,
    model_config: assistStore.selectedModel,
    ...(session.value.targetNodeIds[0] ? { selected_node: session.value.targetNodeIds[0] } : {}),
    ...(Array.isArray(turn.references) && turn.references.length ? { references: turn.references } : {}),
  }),
  submitTurn: payload => postWorkflowAssistTurn(props.appId, conversationId.value, payload),
  streamRunEvents: (submitted, options) => streamWorkflowAssistRunEvents(
    props.appId,
    conversationId.value,
    submitted.run_id,
    options,
  ),
  abortChat: ({ conversation_id, run_id, epoch }) => postWorkflowAssistRunAbort(
    props.appId,
    conversation_id,
    run_id,
    { epoch },
  ),
  retryRun: ({ conversation_id, run_id, epoch, failed_step_id }) => postWorkflowAssistRunRetry(
    props.appId,
    conversation_id,
    run_id,
    { epoch, failed_step_id },
  ),
  dispatch,
  onRunStatus: announceRunStatus,
  onErrors(errors) {
    session.value = { ...session.value, errors: [...(errors || [])] }
  },
  onRunSubmitted(submitted) {
    conversationId.value = String(submitted.conversation_id || conversationId.value)
    assistStore.setAppCoordination(props.appId, {
      conversation_id: conversationId.value,
      run_id: submitted.run_id,
      epoch: submitted.epoch,
      cursor: Number(submitted.cursor || 0),
    })
  },
  onRunCursor(sequence) {
    assistStore.advanceAppCursor(props.appId, sequence)
  },
  loadConversations,
  loadConversation: id => getWorkflowAssistConversation(props.appId, id),
  loadTimeline: (id, params) => getWorkflowAssistTimeline(props.appId, id, params),
  loadCandidate: id => getWorkflowAssistCandidate(props.appId, id),
  loadRunSummaries: (id, params) => getWorkflowAssistRuns(props.appId, id, params),
  getRunCoordinates: () => assistStore.getAppCoordination(props.appId),
  reconcileRunCoordinates: reconcileRunFacts,
  onCandidate(snapshot) {
    candidate.value = snapshot
    announceRunFacts(snapshot)
    emit('candidate-preview', {
      graph: isPreviewableAssistGraph(snapshot?.graph) ? snapshot.graph : null,
      revision: snapshot?.revision,
      baseHash: snapshot?.base_hash,
    })
    if (workflowAssistApplyPresentation(snapshot, props.appMode).eligible)
      announceApplyStatus('ready')
  },
  onTimelineRecovered({ messages: recoveredMessages }) {
    language.value = detectRecoveredAssistLanguage(recoveredMessages)
  },
  onRecoveryState(next) {
    recoveryState.value = next
  },
  selectConversation: selectConversationRecord,
  newConversation: createConversationRecord,
})

function submitMessage(message, receipt, references) {
  return assistController.submitMessage(message, {
    onAccepted: () => receipt?.accepted?.(),
    references,
  })
}

function answerClarification({ index, answers }) {
  const id = messages.value[index]?.clarification?.clarification_id
  return assistController.submitClarification(id, answers)
}

function selectConversation(id) {
  return assistController.selectConversation(id)
}

function newConversation() {
  return assistController.newConversation().then((created) => {
    if (created !== false)
      emit('candidate-preview', { graph: null })
    return created
  })
}

function cancelRename() {
  renamingConversationId.value = ''
  renameDraft.value = ''
}

function startRename(conversation) {
  const id = String(conversation?.id || '')
  if (!id || renamingBusy.value)
    return
  renamingConversationId.value = id
  renameDraft.value = String(conversation.title || '')
  nextTick(() => {
    const input = renameInput.value
    input?.focus?.()
    input?.select?.()
  })
}

async function commitRename(conversation) {
  const id = String(conversation?.id || '')
  if (!id || renamingConversationId.value !== id || renamingBusy.value)
    return
  const nextTitle = normalizeConversationTitle(renameDraft.value)
  const previous = String(conversation.title || '')
  cancelRename()
  if (!nextTitle || nextTitle === previous)
    return
  renamingBusy.value = true
  try {
    const updated = unwrapConversation(await patchWorkflowAssistConversationTitle(props.appId, id, nextTitle))
    const savedTitle = String(updated?.title || nextTitle)
    conversations.value = conversations.value.map(item => (
      String(item.id) === id ? { ...item, title: savedTitle } : item
    ))
  }
  catch (error) {
    session.value = {
      ...session.value,
      errors: assistErrorsFromAxios(error, language.value),
    }
  }
  finally {
    renamingBusy.value = false
  }
}

async function deleteConversation(conversation) {
  const id = String(conversation?.id || '')
  if (!id || deletingConversationId.value)
    return
  if (!window.confirm(copy.value.confirmDeleteConversation))
    return
  deletingConversationId.value = id
  try {
    if (conversationId.value === id)
      assistController.detachActiveTurn()
    await deleteWorkflowAssistConversation(props.appId, id)
    const remaining = conversations.value.filter(item => String(item.id) !== id)
    conversations.value = remaining
    if (conversationId.value !== id)
      return
    const nextId = nextConversationIdAfterDelete(remaining, id, id)
    if (nextId)
      await selectConversation(nextId)
    else
      await newConversation()
  }
  catch (error) {
    session.value = {
      ...session.value,
      errors: assistErrorsFromAxios(error, language.value),
    }
  }
  finally {
    deletingConversationId.value = ''
  }
}

function focusModelSelector() {
  composerRef.value?.focusModelSelector?.()
}

function removeTargetNode(id) {
  dispatch({
    type: 'SET_TARGET_NODES',
    nodeIds: session.value.targetNodeIds.filter(nodeId => String(nodeId) !== String(id)),
  })
}

function addTargetNodes(nodeIds) {
  return insertSelectedNodeMentions({
    nodes: props.currentGraph?.nodes || [],
    nodeIds,
    insertResource: resource => composerRef.value?.insertResource?.(resource),
  })
}

async function apply() {
  if (applying.value || !applyUi.value.eligible)
    return
  applyNotice.value = ''
  announceApplyStatus('applying')
  try {
    const result = await applyWorkflowAssistCandidate({
      appId: props.appId,
      conversationId: conversationId.value,
      candidate: candidate.value,
      appMode: props.appMode,
      syncDraftIfDirty: props.syncDraftIfDirty,
      postApply: postWorkflowAssistApply,
      reconcile: reconcileRunFacts,
      async onConflict() {
        applyNotice.value = copy.value.applyConflict
        const snapshot = await getWorkflowAssistCandidate(props.appId, conversationId.value)
        candidate.value = snapshot
        reconcileRunFacts({
          conversation_id: conversationId.value,
          active_run: snapshot?.active_run || null,
          latest_run: snapshot?.latest_run || null,
        })
      },
      isApplying: () => applying.value,
      setApplying: value => { applying.value = value },
    })
    if (result.skipped)
      return
    if (result.applied) {
      announceApplyStatus('applied')
      dispatch({ type: 'APPLY_OK' })
      candidate.value = null
      emit('applied', { graph: result.graph, hash: result.hash })
      return
    }
    if (result.conflict) {
      announceApplyStatus('conflict')
    }
  }
  catch (error) {
    applyNotice.value = copy.value.applyFailed
    announceApplyStatus('failed')
    dispatch({ type: 'APPLY_FAIL', errors: assistErrorsFromAxios(error, language.value) })
  }
}

function handleClose() {
  assistController.detachActiveTurn()
  emit('close')
}

let resizeStart = null

function startDockResize(event) {
  if (window.innerWidth < 960)
    return
  stopDockResize()
  resizeStart = { x: event.clientX, width: assistStore.panelWidth }
  window.addEventListener('pointermove', resizeDock)
  window.addEventListener('pointerup', stopDockResize, { once: true })
  event.preventDefault()
}

function resizeDock(event) {
  if (resizeStart)
    assistStore.setPanelWidth(resizeStart.width + (event.clientX - resizeStart.x))
}

function stopDockResize() {
  resizeStart = null
  window.removeEventListener('pointermove', resizeDock)
  window.removeEventListener('pointerup', stopDockResize)
}

function resizeDockByKeyboard(event) {
  if (!['ArrowLeft', 'ArrowRight'].includes(event.key))
    return
  event.preventDefault()
  assistStore.setPanelWidth(assistStore.panelWidth + (event.key === 'ArrowRight' ? 16 : -16))
}

defineExpose({ addTargetNodes })

async function restoreSession() {
  const mounted = await assistController.mountRecoverableSession()
  if (!mounted && recoveryState.value === 'ready' && !conversations.value.length && !conversationId.value)
    await newConversation()
}

function retryRecovery() {
  return conversationId.value
    ? assistController.selectConversation(conversationId.value)
    : restoreSession()
}

function loginToRestore() {
  const returnPath = window.location.hash.replace(/^#/, '') || '/'
  window.location.hash = `#/login?redirect=${encodeURIComponent(returnPath)}`
}

onMounted(async () => {
  assistStore.hydrateAppCoordination(props.appId)
  await restoreSession()
})

onBeforeUnmount(() => {
  assistController.detachActiveTurn()
  statusLive.dispose()
  stopDockResize()
})
</script>

<style scoped>
.recovery-notice {
  padding: 8px 16px;
  color: #344054;
  background: #f2f4f7;
}

.workflow-assist-dock {
  position: relative;
  display: flex;
  min-width: 360px;
  max-width: 560px;
  height: 100%;
  flex-direction: column;
  border-left: 1px solid #e4e7ec;
  background: #fff;
  box-shadow: -8px 0 24px rgb(16 24 40 / 8%);
}

.dock-resize-handle {
  position: absolute;
  inset: 0 -4px 0 auto;
  width: 8px;
  z-index: 1;
  cursor: ew-resize;
}

.dock-resize-handle:focus-visible,
.dock-header-actions button:focus-visible,
.history-row:focus-visible,
.history-delete:focus-visible,
.apply-card button:focus-visible {
  outline: 2px solid #175cd3;
  outline-offset: 2px;
}

.dock-header,
.dock-header-actions {
  display: flex;
  align-items: center;
}

.dock-header {
  justify-content: space-between;
  gap: 12px;
  padding: 14px;
  border-bottom: 1px solid #e4e7ec;
}

.dock-title h2,
.dock-title p {
  margin: 0;
}

.dock-title p {
  margin-top: 2px;
  color: #667085;
  font-size: 12px;
}

.dock-header-actions {
  gap: 6px;
}

.dock-header-actions button {
  width: 32px;
  height: 32px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #fff;
  color: #344054;
  cursor: pointer;
}

.conversation-history {
  display: grid;
  gap: 6px;
  max-height: 220px;
  overflow-y: auto;
  padding: 10px 14px;
  border-bottom: 1px solid #e4e7ec;
}

.history-item {
  display: flex;
  align-items: stretch;
  gap: 4px;
  border: 1px solid transparent;
  border-radius: 8px;
}

.history-item.active {
  border-color: #84adff;
  background: #eff4ff;
}

.history-row,
.history-rename {
  display: flex;
  min-width: 0;
  flex: 1;
  justify-content: space-between;
  gap: 10px;
  border: 0;
  border-radius: 8px;
  padding: 8px;
  background: transparent;
  color: #344054;
  text-align: left;
}

.history-row {
  cursor: pointer;
}

.history-rename {
  align-items: center;
  padding: 4px 8px;
}

.history-rename-input {
  width: 100%;
  min-width: 0;
  border: 1px solid #84adff;
  border-radius: 6px;
  padding: 4px 8px;
  color: #344054;
  background: #fff;
}

.history-rename-btn,
.history-delete {
  flex-shrink: 0;
  width: 28px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #667085;
  cursor: pointer;
}

.history-rename-btn:hover,
.history-rename-btn:focus-visible {
  color: #175cd3;
  background: #eff4ff;
}

.history-delete:hover,
.history-delete:focus-visible {
  color: #b42318;
  background: #fef3f2;
}

.history-title {
  min-width: 0;
  overflow: hidden;
  flex: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-time {
  flex-shrink: 0;
  color: #667085;
  font-size: 12px;
}

.apply-card,
.apply-notice,
.contract-report-card {
  margin: 0 12px 10px;
  padding: 10px 12px;
  border-radius: 10px;
}

.contract-report-card {
  border: 1px solid #d0d5dd;
  color: #344054;
  background: #f9fafb;
  font-size: 12px;
}

.contract-report-card.is-blocked {
  border-color: #fda29b;
  background: #fef3f2;
}

.contract-report-card.is-partially_verified {
  border-color: #fec84b;
  background: #fffaeb;
}

.contract-report-header {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.contract-report-card p {
  margin: 6px 0 0;
}

.contract-report-card ul {
  display: grid;
  gap: 4px;
  max-height: 112px;
  overflow-y: auto;
  margin: 8px 0 0;
  padding-left: 18px;
}

.apply-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  background: #ecfdf3;
  color: #067647;
}

.apply-card p,
.apply-notice {
  margin-top: 0;
  margin-bottom: 0;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

.apply-card button {
  min-height: 34px;
  border: 1px solid #067647;
  border-radius: 8px;
  background: #067647;
  color: #fff;
}

.apply-notice {
  background: #fef3f2;
  color: #b42318;
}

@media (max-width: 959px) {
  .workflow-assist-dock {
    width: min(100vw, 560px) !important;
    min-width: 0;
  }

  .dock-resize-handle {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .workflow-assist-dock,
  .dock-header-actions button,
  .apply-card button {
    animation: none;
    scroll-behavior: auto;
    transition: none;
  }
}
</style>
