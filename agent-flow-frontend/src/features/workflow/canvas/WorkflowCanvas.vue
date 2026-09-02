<!-- WorkflowCanvas.vue -->
<!--
  画布外壳：接入 useWorkflowCore（增删/连线/复制粘贴/撤销重做）
  + 右侧 Panel + 右键添加节点菜单 + Background/Controls。
  nodes/edges 可由 props 传入做演示；也可调用 expose 的 initFromGraph / exportGraph。
-->
<template>
  <div
    ref="containerRef"
    class="workflow-canvas-container"
    :class="{ 'is-run-following': isRunning, 'is-workflow-assist-open': workflowAssist.panelOpen }"
    :data-control-mode="effectiveControlMode"
    :style="{ height, width, '--canvas-panel-offset': canvasPanelOffset }"
    @mousemove="handleCanvasMouseMove"
  >
    <WorkflowHeader
      v-if="showToolbar"
      :draft-status="draftStatus"
      :draft-updated-at="draftUpdatedAt"
      :publish-status="publishStatus"
      :read-only="readOnly"
      :is-running="isRunning"
      :can-stop="canStop"
      :checklist-open="showChecklist"
      :checklist-count="checklistCount"
      :run-history-open="showRunHistory"
      :variables-open="showVariables"
      :variables-tab="variablesTab"
      @back="$emit('back')"
      @checklist="toggleChecklist"
      @run-history="toggleRunHistory"
      @variables="openVariables"
      @run="openDebugPreview"
      @stop="$emit('stop-run')"
    />
    <div
      v-if="assistPreviewing"
      class="assist-preview-notice"
      role="status"
    >
      <p>{{ copy.candidatePreviewNotice }}</p>
      <button type="button" @click="restoreOfficialGraphIfPreviewing">{{ copy.restoreDraft }}</button>
    </div>
    <input
      ref="dslFileInput"
      class="visually-hidden"
      type="file"
      accept=".json,.yml,.yaml,application/json,text/yaml"
      aria-label="导入工作流 DSL"
      @change="handleDslFile"
    />
    <FeaturesPanel
      v-if="showFeatures"
      :features="workflowFeatures"
      :read-only="readOnly"
      :saving="featuresSaving"
      :error="featuresError"
      @close="showFeatures = false"
      @save="handleFeaturesSave"
    />
    <VersionHistoryPanel
      v-if="showHistory"
      :versions="versions"
      :loading="historyLoading"
      :error="historyError"
      :restoring-id="restoringVersionId"
      @close="showHistory = false"
      @restore="restoreVersion"
    />
    <RunHistoryPanel
      v-if="showRunHistory"
      :items="runHistoryItems"
      :loading="runHistoryLoading"
      :loading-detail="runHistoryDetailLoading"
      :error="runHistoryError"
      :active-run-id="activeHistoryRunId"
      @close="showRunHistory = false"
      @select="loadHistoryRun"
    />
    <VariableInspectPanel
      v-if="showInspect"
      :app-id="appId"
      :environment-variables="environmentVariables"
      :tracing="effectiveTracing"
      :refresh-token="inspectRefreshToken"
      @close="showInspect = false"
    />
    <ChecklistPanel
      :open="showChecklist"
      :issues="checklistIssues"
      @close="showChecklist = false"
      @goto-node="focusChecklistNode"
    />
    <WorkflowVariablesPanel
      v-if="showVariables"
      v-model:active-tab="variablesTab"
      :read-only="readOnly"
      @close="showVariables = false"
      @change="handleVariablesChanged"
    />
    <div v-if="workflowAssist.panelOpen && syncDraftIfDirty" class="workflow-assist-host">
      <WorkflowAssistDock
        ref="workflowAssistDockRef"
        :app-id="appId"
        :app-mode="workflowMode"
        :current-graph="assistGraphLive"
        :server-draft-hash="draftHash"
        :sync-draft-if-dirty="syncDraftForAssist"
        @close="handleWorkflowAssistClose"
        @candidate-preview="handleWorkflowAssistCandidatePreview"
        @applied="handleWorkflowAssistApplied"
      />
    </div>

    <VueFlow
      :node-types="NODE_COMPONENT_MAP"
      :edge-types="EDGE_COMPONENT_MAP"
      :default-edge-options="{ type: 'custom' }"
      :is-valid-connection="isValidConnection"
      :nodes-draggable="!readOnly"
      :nodes-connectable="!readOnly"
      :elements-selectable="!readOnly"
      :pan-on-drag="effectiveControlMode === 'hand' ? true : [1]"
      :pan-on-scroll="effectiveControlMode === 'pointer' && !readOnly"
      :selection-key-code="effectiveControlMode === 'pointer' && !readOnly"
      multi-selection-key-code="Shift"
      :delete-key-code="null"
      :selection-mode="SelectionMode.Partial"
      :zoom-on-double-click="false"
      :min-zoom="0.25"
      :max-zoom="2"
      @viewport-change-end="handleViewportChange"
      @pane-click="handlePaneClick"
      @pane-context-menu="handlePaneContextMenu"
      @node-context-menu="handleNodeContextMenu"
      @edge-context-menu="handleEdgeContextMenu"
      @selection-context-menu="handleSelectionContextMenu"
      @node-click="handleNodeClick"
      @node-double-click="handleNodeDoubleClick"
      @node-drag-start="handleNodeDragStart"
      @node-drag="handleNodeDrag"
      @node-drag-stop="handleNodeDragStop"
      @nodes-change="handleNodesChange"
      @connect-start="handleConnectStart"
      @connect="handleConnect"
      @connect-end="handleConnectEnd"
      @selection-change="handleSelectionChange"
      @selection-start="handleSelectionStart"
      @selection-drag-start="handleSelectionDragStart"
      @selection-drag-stop="handleSelectionDragStop"
      @edge-double-click="handleEdgeDblClick"
      @edge-mouse-enter="handleEdgeMouseEnter"
      @edge-mouse-leave="handleEdgeMouseLeave"
    >
      <Background :gap="16" :size="1" :pattern-color="canvasDotColor" />
      <template #connection-line="connectionLineProps">
        <CustomConnectionLine v-bind="connectionLineProps" />
      </template>
      <MiniMap
        v-if="showToolbar && showMiniMap"
        position="bottom-right"
        :pannable="true"
        :zoomable="true"
        node-color="var(--workflow-minimap-block, rgba(152, 162, 179, 0.45))"
        mask-color="var(--workflow-minimap-mask, rgba(242, 244, 247, 0.65))"
      />
    </VueFlow>

    <div v-if="helpLineX !== null" class="help-line help-line-vertical" :style="{ left: `${helpLineX}px` }"></div>
    <div v-if="helpLineY !== null" class="help-line help-line-horizontal" :style="{ top: `${helpLineY}px` }"></div>

    <CandidateNodePreview
      v-if="candidateNode"
      :type="candidateNode.type"
      :title="candidateTitle"
      :x="candidateScreenPos.x"
      :y="candidateScreenPos.y"
      :zoom="viewZoom"
    />
    <WorkflowCommentsLayer
      :comments="comments"
      :viewport="viewTransform"
      @update="updateComment"
      @resolve="resolveComment"
      @delete="deleteComment"
    />
    <WorkflowUserCursors :cursors="collaborationCursors" />

    <BlockSelectorMenu
      :visible="menuVisible"
      :x="menuX"
      :y="menuY"
      :mode="selectorMode"
      :workflow-mode="workflowMode"
      :connection-direction="selectorDirection"
      :show-start-tab="selectorShowStartTab"
      :has-start-placeholder="canvasHasStartPlaceholder"
      :has-start-node="canvasHasStartNode"
      :allow-loop-end="selectorAllowsLoopEnd"
      @select="handleBlockSelect"
    />

    <WorkflowContextMenu
      :visible="contextMenu.visible"
      :x="contextMenu.x"
      :y="contextMenu.y"
      :type="contextMenu.type"
      :can-paste="hasClipboard"
      @action="handleContextMenuAction"
    />

    <CanvasControlRail
      v-if="showToolbar"
      v-model:mode="controlMode"
      :read-only="readOnly"
      :agent-open="workflowAssist.panelOpen"
      :agent-panel-width="workflowAssist.panelWidth"
      @add-node="openMenuAtCenter"
      @add-note="startNoteCandidate"
      @organize="handleOrganize"
      @agent="toggleWorkflowAssist"
    />

    <CanvasOperatorDock
      v-if="showToolbar"
      :can-undo="canUndo"
      :can-redo="canRedo"
      :read-only="readOnly"
      :inspect-open="showInspect"
      :zoom-percent="zoomPercent"
      :minimap-open="showMiniMap"
      @undo="undo"
      @redo="redo"
      @inspect="toggleInspect"
      @zoom-out="handleZoomOut"
      @zoom-in="handleZoomIn"
      @fit-view="handleFitView"
      @toggle-minimap="showMiniMap = !showMiniMap"
    />

    <div v-if="viewingHistory" class="history-view-banner" role="status">
      <span>正在查看历史运行 · {{ effectiveRunStatus || '—' }}</span>
      <button type="button" @click="exitHistoryView">退出历史</button>
    </div>

    <div
      v-if="showDebugPreview || (currentPanelComponent && activePanelNode)"
      class="right-panel-stack"
    >
      <NodePanelHost
        v-if="currentPanelComponent && activePanelNode"
        :panel-component="currentPanelComponent"
        :node="activePanelNode"
        :app-id="appId"
        :read-only="readOnly"
        :width="drawerWidth"
        :active-tab="nodePanelTab"
        :supports-single-run="panelSupportsSingleRun"
        :live-result="singleRunResults[activePanelNode.id]"
        :running="singleRunningNodeId === activePanelNode.id"
        @update:width="drawerWidth = $event"
        @update:active-tab="nodePanelTab = $event"
        @update:node-data="handleNodeDataUpdate"
        @close="handleClosePanel"
        @select-node="handlePanelSelectNode"
        @run="handleLastRunSubmit"
        @stop="$emit('stop-run')"
      />

      <div
        v-if="showDebugPreview"
        class="debug-panel-host"
        :style="{ width: previewPanelWidth + 'px' }"
      >
        <WorkflowRunPanel
          :mode="workflowMode"
          :active-tab="activeRunTab"
          :start-variables="startVariables"
          :chat-list="chatList"
          :features="workflowFeatures"
          :app-id="appId"
          :human-input-forms="humanInputForms"
          :submit-human-input="submitHumanInput"
          :after-answer-suggestions="afterAnswerSuggestions"
          :is-running="isRunning && !viewingHistory"
          :can-stop="canStop && !viewingHistory"
          :run-status="effectiveRunStatus"
          :result-text="effectiveResultText"
          :run-error="effectiveRunError"
          :run-outputs="effectiveRunOutputs"
          :conversation-id="conversationId"
          :task-id="taskId"
          :result="effectiveRunResult"
          :tracing="effectiveTracing"
          :selected-node-id="selectedNodeId || ''"
          @close="closeDebugPreview"
          @update:active-tab="onActiveRunTabChange"
          @submit-run="handleDebugSubmitRun"
          @stop="$emit('stop-run')"
          @new-conversation="$emit('new-conversation')"
          @select-node="handleRuntimeNodeSelect"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, shallowRef, computed, watch, provide, onMounted, onUnmounted, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { VueFlow, SelectionMode } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { MiniMap } from '@vue-flow/minimap'
import { NODE_COMPONENT_MAP, PANEL_COMPONENT_MAP, EDGE_COMPONENT_MAP } from '../nodes/registry.js'
import { useWorkflowCore } from '../model/useWorkflowCore.js'
import { useWorkflowStore } from '@/features/workflow/state/useWorkflowStore.js'
import BlockSelectorMenu from './components/BlockSelectorMenu.vue'
import CandidateNodePreview from './components/CandidateNodePreview.vue'
import CustomConnectionLine from './components/CustomConnectionLine.vue'
import WorkflowContextMenu from './components/WorkflowContextMenu.vue'
import WorkflowRunPanel from '../runtime/WorkflowRunPanel.vue'
import WorkflowHeader from './components/WorkflowHeader.vue'
import CanvasControlRail from './components/CanvasControlRail.vue'
import CanvasOperatorDock from './components/CanvasOperatorDock.vue'
import FeaturesPanel from './components/FeaturesPanel.vue'
import VersionHistoryPanel from '../runtime/components/VersionHistoryPanel.vue'
import RunHistoryPanel from '../runtime/components/RunHistoryPanel.vue'
import VariableInspectPanel from './components/VariableInspectPanel.vue'
import ChecklistPanel from './components/ChecklistPanel.vue'
import WorkflowCommentsLayer from './components/WorkflowCommentsLayer.vue'
import WorkflowUserCursors from './components/WorkflowUserCursors.vue'
import WorkflowVariablesPanel from './components/WorkflowVariablesPanel.vue'
import NodePanelHost from './components/NodePanelHost.vue'
import { openNodePanelState } from './nodePanelHost.js'
import WorkflowAssistDock from '@/features/workflow/assistant/WorkflowAssistDock.vue'
import { assistCopy } from '@/features/workflow/assistant/assistLanguage.js'
import { isPreviewableAssistGraph } from '@/features/workflow/assistant/workflowAssistUx.js'
import { selectedAssistNodeIds } from '../model/assistNodeTargets.js'
import { useRouter } from 'vue-router'
import { load as loadYaml } from 'js-yaml'
import { getNodeTitle } from '../model/nodeMeta.js'
import { normalizeNodeSelectorContext } from '../model/nodeSelectorContext.js'
import { BlockEnum } from '../model/constants.js'
import { buildWorkflowChecklist } from '../model/checklist.js'
import { isChatflowMode } from '../model/appModes.js'
import { applyPanelExclusivity, PANEL_KEYS } from '../model/panelExclusivity.js'
import { normalizeCanvasControlMode } from '../model/canvasChrome.js'
import { canRunBySingle } from '../model/canRunBySingle.js'
import { buildCodeRunInputs } from '../nodes/code/codeNode.js'
import { buildTemplateRunInputs } from '../nodes/template-transform/templateTransform.js'
import { buildDocumentExtractorRunInputs } from '../nodes/document-extractor/documentExtractor.js'
import { canAddLoopEnd } from '../nodes/loop-end/loopEndNode.js'
import {
  buildDraftContentSignature,
  quantizeViewport,
} from '../model/draftSignature.js'
import { buildAssistGraphSnapshot } from '../model/graphSnapshot.js'
import { shouldFlushDraftOnLeave } from '../model/draftFlush.js'
import { useWorkflowAssistStore } from '@/stores/useWorkflowAssistStore.js'
import {
  applyContainerFinishedToGraph,
  applyContainerStartedToGraph,
  applyHistoryTracingToGraph,
  applyHumanInputRequiredToGraph,
  applyIterationNextToGraph,
  applyLoopNextToGraph,
  applyNodeFinishedToGraph,
  applyNodeRetryToGraph,
  applyNodeStartedToGraph,
  applyWorkflowFinishedToGraph,
  applyWorkflowStartedToGraph,
  buildHistoryRunView,
  clearGraphRuntime,
  computeFollowViewport,
  refreshGraphRuntimeBindings,
} from '../model/canvasRuntime.js'
import {
  getWorkflowRun,
  getWorkflowRunNodeExecutions,
  listPublishedWorkflows,
  listWorkflowRuns,
} from '@/features/workflow/api/difyWorkflowApi.js'
import {
  getPipelineRun,
  getPipelineRunNodeExecutions,
  listPipelineRuns,
  listPublishedPipelines,
} from '@/features/datasets/api/difyPipelineApi.js'
import {
  mapNodeExecutionsToTracing,
  normalizeWorkflowRunList,
} from '../model/inspectVars.js'
import {
  getRestrictedIterationPosition,
  getIterationContainerBounds,
  getIterationContainerResize,
} from '../nodes/iteration/useIterationInteractions.js'
import {
  getRestrictedLoopPosition,
  getLoopContainerBounds,
  getLoopContainerResize,
} from '../nodes/loop/useLoopInteractions.js'
import { getContainerFitSize } from '../model/containerLayout.js'

import '@vue-flow/minimap/dist/style.css'


const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  width: { type: String, default: '100%' },
  height: { type: String, default: '100%' },
  showToolbar: { type: Boolean, default: true },
  remoteCursors: { type: Array, default: () => [] },
  environmentVariables: { type: Array, default: () => [] },
  conversationVariables: { type: Array, default: () => [] },
  ragPipelineVariables: { type: Array, default: () => [] },
  appId: { type: String, default: '' },
  draftHash: { type: String, default: '' },
  syncDraftIfDirty: { type: Function, default: null },
  /** 'app' uses /apps/{id}/…; 'pipeline' uses /rag/pipelines/{id}/… */
  flowType: { type: String, default: 'app' },
  workflowMode: { type: String, default: 'workflow' },
  isRunning: { type: Boolean, default: false },
  canStop: { type: Boolean, default: false },
  publishing: { type: Boolean, default: false },
  publishStatus: { type: String, default: '' },
  runStatus: { type: String, default: 'idle' },
  resultText: { type: String, default: '' },
  runError: { type: String, default: '' },
  runOutputs: { type: [Object, Array, String, Number, Boolean], default: null },
  conversationId: { type: String, default: null },
  taskId: { type: String, default: '' },
  runResult: { type: Object, default: null },
  tracingItems: { type: Array, default: () => [] },
  chatList: { type: Array, default: () => [] },
  workflowFeatures: { type: Object, default: () => ({}) },
  featuresSaving: { type: Boolean, default: false },
  featuresError: { type: String, default: '' },
  humanInputForms: { type: Array, default: () => [] },
  submitHumanInput: { type: Function, default: null },
  afterAnswerSuggestions: { type: Array, default: () => [] },
  activeRunTab: { type: String, default: 'INPUT' },
})
const emit = defineEmits([
  'run-node',
  'run-workflow',
  'save-draft',
  'publish',
  'stop-run',
  'new-conversation',
  'update:active-run-tab',
  'back',
  'sync-variables',
  'restore-version',
  'cursor-move',
  'save-features',
  'assist-applied',
])

const store = useWorkflowStore()
const workflowAssist = useWorkflowAssistStore()
const router = useRouter()
const {
  canUndo,
  canRedo,
  hasClipboard,
  readOnly,
  selectedNodeId,
  workflowName,
  environmentVariables,
  conversationVariables,
} = storeToRefs(store)
const containerRef = ref(null)
const workflowAssistDockRef = ref(null)
const assistPreviewing = ref(false)
const copy = assistCopy()
let officialGraphSnapshot = null

function toggleWorkflowAssist() {
  workflowAssist.toggle()
}

function syncDraftForAssist() {
  if (assistPreviewing.value)
    return { hash: props.draftHash }
  return props.syncDraftIfDirty?.()
}

function handleWorkflowAssistCandidatePreview(payload) {
  if (!isPreviewableAssistGraph(payload?.graph)) {
    restoreOfficialGraphIfPreviewing()
    return
  }
  if (!assistPreviewing.value)
    officialGraphSnapshot = exportGraph()
  assistPreviewing.value = true
  initFromGraph(payload.graph, { workflowName: workflowName.value })
}

function restoreOfficialGraphIfPreviewing() {
  if (!assistPreviewing.value)
    return
  if (officialGraphSnapshot)
    initFromGraph(officialGraphSnapshot, { workflowName: workflowName.value })
  assistPreviewing.value = false
  officialGraphSnapshot = null
}

function handleWorkflowAssistClose() {
  workflowAssist.close()
}

function handleWorkflowAssistApplied(payload) {
  assistPreviewing.value = false
  officialGraphSnapshot = null
  if (payload?.graph) {
    initFromGraph(payload.graph, { workflowName: workflowName.value })
    clearRuntimeState()
    refreshStartVariables()
    markDraftSaved()
  }
  emit('assist-applied', payload)
}

function goToIntegrations() {
  router.push({ path: '/integrations', query: { tab: 'models' } })
}

const {
  initFromGraph,
  exportGraph,
  addNode,
  addConnectedNode,
  addPredecessorNode,
  insertNodeOnEdge,
  removeNode,
  updateNodeData,
  replaceStartPlaceholder,
  onConnect,
  isValidConnection,
  selectNode,
  clearSelection,
  duplicateNode,
  copySelection,
  copyNode,
  paste,
  deleteSelected,
  undo,
  redo,
  organizeNodes,
  recordHistory,
  vueFlow,
} = useWorkflowCore()

const {
  findNode,
  getNodes,
  getSelectedNodes,
  removeEdges,
  getEdges,
  zoomIn,
  zoomOut,
  fitView,
  viewport,
  setViewport,
  setCenter,
} = vueFlow

// Assist plan/generate uses live canvas, not server draft.
const assistGraphLive = computed(() => buildAssistGraphSnapshot({
  nodes: getNodes.value || [],
  edges: getEdges.value || [],
  viewport: viewport.value || {},
}))

const assistDraftRevision = computed(() => buildDraftContentSignature({
  nodes: getNodes.value || [],
  edges: getEdges.value || [],
  environmentVariables: environmentVariables.value,
  conversationVariables: conversationVariables.value,
  workflowName: workflowName.value,
}))

const controlMode = ref('pointer')
const isSpaceHeld = ref(false)
const comments = ref([])
const collaborationCursors = ref([...props.remoteCursors])
let lastCursorEmitAt = 0

watch(() => props.remoteCursors, cursors => {
  collaborationCursors.value = [...(cursors || [])]
}, { deep: true })

const effectiveControlMode = computed(() => {
  if (isSpaceHeld.value) return 'hand'
  return normalizeCanvasControlMode(controlMode.value)
})

// Do NOT bind live vue-flow viewport into this parent template — float updates
// during fit/measure re-enter WorkflowCanvas render → Maximum recursive updates.
// Only sync from viewport-change-end with quantized values.
const zoomPercent = ref(100)
const viewZoom = ref(1)
const viewTransform = ref({ x: 0, y: 0, zoom: 1 })
const bundledNodeIds = ref([])
let lastBundledKey = ''

function handleViewportChange(vp = {}) {
  const next = quantizeViewport(vp)
  const nextPercent = Math.round(next.zoom * 100)
  if (zoomPercent.value !== nextPercent)
    zoomPercent.value = nextPercent
  if (Math.abs(viewZoom.value - next.zoom) > 0.001)
    viewZoom.value = next.zoom
  const prev = viewTransform.value
  if (prev.x !== next.x || prev.y !== next.y || prev.zoom !== next.zoom)
    viewTransform.value = next
}

const canvasDotColor = computed(() => 'var(--workflow-canvas-dot, #d0d5dd)')
const showDebugPreview = ref(false)
const showMiniMap = ref(true)
const showChecklist = ref(false)
const showFeatures = ref(false)
const runtimeRecords = ref({})
const runtimeItems = computed(() => Object.values(runtimeRecords.value))
const EMPTY_START_VARS = Object.freeze([])
/** Snapshot — never computed from live getNodes (dimension writes would re-render canvas). */
const startVariables = ref(EMPTY_START_VARS)

function refreshStartVariables() {
  const startNode = (getNodes.value || []).find((node) => {
    const type = node.data?.type || node.type
    return type === 'start'
  })
  const vars = startNode?.data?.variables
  startVariables.value = Array.isArray(vars) && vars.length ? vars : EMPTY_START_VARS
}
const dslFileInput = ref(null)
const draftStatus = ref('saved')
const draftUpdatedAt = ref(0)
const AUTOSAVE_DELAY_MS = 5000
let autosaveTimer = null
const showHistory = ref(false)
const showRunHistory = ref(false)
const showVariables = ref(false)
const variablesTab = ref('sys')
const showInspect = ref(false)
const versions = ref([])
const historyLoading = ref(false)
const historyError = ref('')
const restoringVersionId = ref('')
const runHistoryItems = ref([])
const runHistoryLoading = ref(false)
const runHistoryDetailLoading = ref(false)
const runHistoryError = ref('')
const activeHistoryRunId = ref('')
const historyTracing = ref(null)
const historyResult = ref(null)
const historyRunView = ref(null)
const inspectRefreshToken = ref(0)

const viewingHistory = computed(() => Boolean(activeHistoryRunId.value && historyRunView.value))
const effectiveTracing = computed(() => (
  historyTracing.value || props.tracingItems || []
))
const effectiveRunResult = computed(() => (
  historyResult.value || props.runResult || null
))
const effectiveResultText = computed(() => (
  viewingHistory.value ? (historyRunView.value?.resultText || '') : props.resultText
))
const effectiveRunStatus = computed(() => (
  viewingHistory.value ? (historyRunView.value?.status || '') : props.runStatus
))
const effectiveRunOutputs = computed(() => (
  viewingHistory.value ? (historyRunView.value?.outputs || null) : props.runOutputs
))
const effectiveRunError = computed(() => (
  viewingHistory.value ? (historyRunView.value?.error || '') : props.runError
))

/** Checklist is refreshed on demand — never track live Vue Flow nodes in render. */
const checklistIssues = ref([])
const checklistCount = computed(() => checklistIssues.value.length)

function refreshChecklistIssues() {
  const nodes = (getNodes.value || []).map(n => ({
    id: n.id,
    type: n.type,
    parentId: n.parentNode || n.parentId,
    data: n.data,
    position: n.position,
  }))
  const edges = (getEdges.value || []).map(e => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.sourceHandle,
    targetHandle: e.targetHandle,
    data: e.data,
  }))
  checklistIssues.value = buildWorkflowChecklist({ nodes, edges }, {
    isChatMode: isChatflowMode(props.workflowMode),
    environmentVariables: environmentVariables.value,
    conversationVariables: conversationVariables.value,
    ragPipelineVariables: store.ragPipelineVariables || [],
  })
}

const lastSavedSignature = ref('')
const AUTOSAVE_POLL_MS = 1500
let draftPollTimer = null

function readDraftSignature() {
  return buildDraftContentSignature({
    nodes: getNodes.value || [],
    edges: getEdges.value || [],
    environmentVariables: environmentVariables.value,
    conversationVariables: conversationVariables.value,
    workflowName: workflowName.value,
  })
}

function scheduleAutosave() {
  clearTimeout(autosaveTimer)
  if (readOnly.value || assistPreviewing.value)
    return
  autosaveTimer = setTimeout(() => {
    if (draftStatus.value !== 'dirty')
      return
    saveWorkflowDraft({ silent: true })
  }, AUTOSAVE_DELAY_MS)
}

function markDraftDirty() {
  if (draftStatus.value !== 'dirty' && draftStatus.value !== 'saving')
    draftStatus.value = 'dirty'
  scheduleAutosave()
}

function applyDraftSignature(signature) {
  if (!lastSavedSignature.value) {
    lastSavedSignature.value = signature
    return
  }
  if (signature === lastSavedSignature.value) {
    if (draftStatus.value === 'dirty')
      draftStatus.value = 'saved'
    clearTimeout(autosaveTimer)
    return
  }
  markDraftDirty()
}

function pollDraftSignature() {
  // Imperative poll — must NOT be a computed/watch on getNodes (Vue Flow mutates
  // nodes during render; tracking them causes Maximum recursive updates).
  if (assistPreviewing.value)
    return
  try {
    applyDraftSignature(readDraftSignature())
  }
  catch {
    // Ignore transient graph read errors during init.
  }
}

function startDraftPolling() {
  stopDraftPolling()
  draftPollTimer = setInterval(pollDraftSignature, AUTOSAVE_POLL_MS)
}

function stopDraftPolling() {
  if (draftPollTimer) {
    clearInterval(draftPollTimer)
    draftPollTimer = null
  }
}

function updateWorkflowName(name) {
  store.setMeta({ workflowName: name })
  markDraftDirty()
}

function buildDraftPayload() {
  return {
    // Capture at emit time — route query may clear before async parent save.
    appId: props.appId,
    name: workflowName.value,
    graph: exportGraph(),
    environmentVariables: environmentVariables.value,
    conversationVariables: conversationVariables.value,
  }
}

function saveWorkflowDraft({ silent = false } = {}) {
  draftStatus.value = 'saving'
  emit('save-draft', { ...buildDraftPayload(), silent })
}

function flushDraftIfNeeded() {
  clearTimeout(autosaveTimer)
  autosaveTimer = null
  if (assistPreviewing.value)
    return false
  if (!shouldFlushDraftOnLeave({ draftStatus: draftStatus.value, readOnly: readOnly.value }))
    return false
  saveWorkflowDraft({ silent: true })
  return true
}

function handleBeforeUnload(event) {
  if (!shouldFlushDraftOnLeave({ draftStatus: draftStatus.value, readOnly: readOnly.value }))
    return
  flushDraftIfNeeded()
  event.preventDefault()
  event.returnValue = ''
}

function publishWorkflowFromUi() {
  emit('publish', buildDraftPayload())
}

function handleVariablesChanged() {
  emit('sync-variables', {
    environmentVariables: environmentVariables.value,
    conversationVariables: conversationVariables.value,
  })
  markDraftDirty()
}

function panelFlags() {
  return {
    debug: showDebugPreview,
    variables: showVariables,
    inspect: showInspect,
    features: showFeatures,
    checklist: showChecklist,
    versionHistory: showHistory,
    runHistory: showRunHistory,
  }
}

function toggleChecklist() {
  const next = !showChecklist.value
  applyPanelExclusivity(panelFlags(), PANEL_KEYS.checklist, { open: next })
  showChecklist.value = next
  if (next)
    refreshChecklistIssues()
}

function focusChecklistNode(nodeId) {
  if (!nodeId) return
  selectNode(nodeId)
  activePanelNodeId.value = nodeId
  showChecklist.value = false
  const node = findNode(nodeId)
  if (node?.position && typeof setCenter === 'function') {
    const w = Number(node.dimensions?.width || node.width || 240)
    const h = Number(node.dimensions?.height || node.height || 80)
    setCenter(node.position.x + w / 2, node.position.y + h / 2, { zoom: 1, duration: 280 })
  }
}


function toggleFeatures() {
  const next = !showFeatures.value
  applyPanelExclusivity(panelFlags(), PANEL_KEYS.features, { open: next })
  showFeatures.value = next
}

function handleFeaturesSave(nextFeatures) {
  emit('save-features', nextFeatures)
}

async function toggleHistory() {
  const next = !showHistory.value
  applyPanelExclusivity(panelFlags(), PANEL_KEYS.versionHistory, { open: next })
  showHistory.value = next
  if (next)
    await refreshVersionHistory()
}

function toggleInspect() {
  const next = !showInspect.value
  applyPanelExclusivity(panelFlags(), PANEL_KEYS.inspect, { open: next })
  showInspect.value = next
  if (next)
    inspectRefreshToken.value += 1
}

function openVariables(tab = 'sys') {
  const nextTab = ['sys', 'env', 'conversation'].includes(tab) ? tab : 'sys'
  const shouldClose = showVariables.value && variablesTab.value === nextTab
  variablesTab.value = nextTab
  applyPanelExclusivity(panelFlags(), PANEL_KEYS.variables, { open: !shouldClose })
  showVariables.value = !shouldClose
}

async function toggleRunHistory() {
  const next = !showRunHistory.value
  applyPanelExclusivity(panelFlags(), PANEL_KEYS.runHistory, { open: next })
  showRunHistory.value = next
  if (next)
    await refreshRunHistory()
}

const isPipelineFlow = computed(() => props.flowType === 'pipeline')

async function refreshRunHistory() {
  if (!props.appId) {
    runHistoryItems.value = []
    runHistoryError.value = isPipelineFlow.value
      ? '缺少 pipelineId，无法加载运行记录'
      : '缺少 appId，无法加载运行记录'
    return
  }
  runHistoryLoading.value = true
  runHistoryError.value = ''
  try {
    const response = isPipelineFlow.value
      ? await listPipelineRuns(props.appId, { limit: 20 })
      : await listWorkflowRuns(props.appId, {
        limit: 20,
        mode: props.workflowMode,
      })
    runHistoryItems.value = normalizeWorkflowRunList(response)
  }
  catch (error) {
    runHistoryError.value = error.response?.data?.message || error.message || '加载运行记录失败'
    runHistoryItems.value = []
  }
  finally {
    runHistoryLoading.value = false
  }
}

async function loadHistoryRun(item) {
  if (!props.appId || !item?.id)
    return
  runHistoryDetailLoading.value = true
  activeHistoryRunId.value = item.id
  try {
    const [detail, executions] = await Promise.all(
      isPipelineFlow.value
        ? [
            getPipelineRun(props.appId, item.id),
            getPipelineRunNodeExecutions(props.appId, item.id),
          ]
        : [
            getWorkflowRun(props.appId, item.id),
            getWorkflowRunNodeExecutions(props.appId, item.id),
          ],
    )
    const tracing = mapNodeExecutionsToTracing(executions)
    historyResult.value = detail
    historyTracing.value = tracing
    historyRunView.value = buildHistoryRunView(detail?.data || detail || item)
    applyHistoryTracingToGraph(getNodes.value, getEdges.value, tracing)
    refreshGraphRuntimeBindings(getNodes.value, getEdges.value)
    showDebugPreview.value = true
    showRunHistory.value = false
    emit('update:active-run-tab', 'TRACING')
  }
  catch (error) {
    runHistoryError.value = error.response?.data?.message || error.message || '加载运行详情失败'
  }
  finally {
    runHistoryDetailLoading.value = false
  }
}

function exitHistoryView() {
  activeHistoryRunId.value = ''
  historyTracing.value = null
  historyResult.value = null
  historyRunView.value = null
  clearGraphRuntime(getNodes.value, getEdges.value)
  refreshGraphRuntimeBindings(getNodes.value, getEdges.value)
}

function bumpInspectRefresh() {
  inspectRefreshToken.value += 1
}

watch(() => props.runStatus, (status, prev) => {
  if (!prev || prev === status)
    return
  if (['succeeded', 'failed', 'stopped'].includes(status))
    bumpInspectRefresh()
})

async function refreshVersionHistory() {
  if (!props.appId) {
    versions.value = []
    historyError.value = isPipelineFlow.value
      ? '缺少 pipelineId，无法加载版本历史'
      : '缺少 appId，无法加载版本历史'
    return
  }
  historyLoading.value = true
  historyError.value = ''
  try {
    const response = isPipelineFlow.value
      ? await listPublishedPipelines(props.appId, { page: 1, limit: 30 })
      : await listPublishedWorkflows(props.appId, { page: 1, limit: 30 })
    versions.value = response.items || response.data || []
  } catch (error) {
    historyError.value = error.response?.data?.message || error.message || '加载版本历史失败'
    versions.value = []
  } finally {
    historyLoading.value = false
  }
}

function markDraftSaved() {
  lastSavedSignature.value = readDraftSignature()
  draftStatus.value = 'saved'
  draftUpdatedAt.value = Date.now()
  clearTimeout(autosaveTimer)
}

function markDraftSaveFailed() {
  draftStatus.value = 'error'
}

function initializeDraft(draft = {}) {
  initFromGraph(draft.graph || { nodes: [], edges: [] }, {
    workflowId: draft.id,
    workflowName: draft.name || workflowName.value,
  })
  store.setEnvironmentVariables(draft.environment_variables || [])
  store.setConversationVariables(draft.conversation_variables || [])
  store.setRagPipelineVariables(draft.rag_pipeline_variables || [])
  clearRuntimeState()
  refreshStartVariables()
  markDraftSaved()
  // Defer fitView, then select on a later frame so layout/measure and selection
  // do not fight in the same reactive flush.
  nextTick(() => {
    requestAnimationFrame(() => {
      try {
        fitView?.({ padding: 0.2, duration: 0 })
      }
      catch {
        // ignore fit errors before graph is ready
      }
      requestAnimationFrame(() => {
        const placeholder = getNodes.value.find(node => (node.data?.type || node.type) === 'start-placeholder')
        if (placeholder) {
          selectNode(placeholder.id)
          activePanelNodeId.value = placeholder.id
        }
      })
    })
  })
}

function exportDslFile() {
  const content = JSON.stringify({
    version: '0.1.0',
    workflow: {
      name: workflowName.value,
      graph: exportGraph(),
      environment_variables: environmentVariables.value,
      conversation_variables: conversationVariables.value,
      rag_pipeline_variables: store.ragPipelineVariables || [],
    },
  }, null, 2)
  const blob = new Blob([content], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${workflowName.value || 'workflow'}.dsl.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

function openDslImport() {
  dslFileInput.value?.click()
}

async function handleDslFile(event) {
  const file = event.target?.files?.[0]
  if (!file) return
  try {
    const raw = await file.text()
    const parsed = file.name.endsWith('.json') ? JSON.parse(raw) : loadYaml(raw)
    const graph = parsed?.workflow?.graph || parsed?.graph || parsed
    if (!Array.isArray(graph?.nodes) || !Array.isArray(graph?.edges))
      throw new Error('DSL 中缺少 graph.nodes 或 graph.edges')
    initFromGraph(graph, {
      workflowName: parsed?.workflow?.name || parsed?.name || workflowName.value,
    })
    store.setEnvironmentVariables(parsed?.workflow?.environment_variables || parsed?.environment_variables || [])
    store.setConversationVariables(parsed?.workflow?.conversation_variables || parsed?.conversation_variables || [])
    store.setRagPipelineVariables(parsed?.workflow?.rag_pipeline_variables || parsed?.rag_pipeline_variables || [])
    markDraftSaved()
  } catch (error) {
    draftStatus.value = 'error'
    console.error('Failed to import workflow DSL', error)
  } finally {
    event.target.value = ''
  }
}

async function restoreVersion(versionId) {
  if (!versionId || restoringVersionId.value) return
  restoringVersionId.value = String(versionId)
  try {
    emit('restore-version', versionId)
  } finally {
    restoringVersionId.value = ''
    showHistory.value = false
  }
}

function upsertRuntimeRecord(nodeId, { status, inputs, outputs, error } = {}) {
  if (!nodeId)
    return
  const node = findNode(nodeId)
  runtimeRecords.value = {
    ...runtimeRecords.value,
    [nodeId]: {
      ...(runtimeRecords.value[nodeId] || {}),
      nodeId,
      title: node?.data?.title || nodeId,
      status: status || 'running',
      inputs,
      outputs,
      error,
    },
  }
}

/**
 * Apply draft-run canvas paint from SSE canvasEvent.
 * Contrasts Dify use-workflow-*-started/finished + iteration/loop/retry/human-input.
 * Also accepts legacy { nodeId, status } payloads (single-node debug).
 */
function applyNodeRunState(payload = {}) {
  const nodes = getNodes.value
  const edges = getEdges.value
  const type = payload.type
    || (payload.nodeId
      ? (payload.status === 'running' && payload.outputs === undefined && !payload.error
        ? 'node_started'
        : 'node_finished')
      : null)

  if (type === 'workflow_started') {
    applyWorkflowStartedToGraph(nodes, edges)
  }
  else if (type === 'workflow_finished') {
    applyWorkflowFinishedToGraph(nodes, edges, { status: payload.status })
  }
  else if (type === 'node_started') {
    const node = applyNodeStartedToGraph(nodes, edges, payload.nodeId)
    upsertRuntimeRecord(payload.nodeId, {
      status: 'running',
      inputs: payload.inputs,
    })
    followRunningNode(node)
  }
  else if (type === 'node_finished' && payload.nodeId) {
    applyNodeFinishedToGraph(nodes, edges, {
      nodeId: payload.nodeId,
      status: payload.status,
      nodeType: payload.nodeType,
      outputs: payload.outputs,
      executionMetadata: payload.executionMetadata,
    })
    upsertRuntimeRecord(payload.nodeId, {
      status: payload.status,
      inputs: payload.inputs,
      outputs: payload.outputs,
      error: payload.error,
    })
  }
  else if (type === 'iteration_started' || type === 'loop_started') {
    const node = applyContainerStartedToGraph(nodes, edges, {
      nodeId: payload.nodeId,
      iterationLength: payload.iterationLength,
      loopLength: payload.loopLength,
    })
    upsertRuntimeRecord(payload.nodeId, { status: 'running' })
    followRunningNode(node)
  }
  else if (type === 'iteration_next') {
    applyIterationNextToGraph(nodes, payload.nodeId, payload.iterationIndex)
  }
  else if (type === 'loop_next') {
    applyLoopNextToGraph(nodes, {
      nodeId: payload.nodeId,
      loopIndex: payload.loopIndex,
    })
  }
  else if (type === 'iteration_completed' || type === 'loop_completed') {
    applyContainerFinishedToGraph(nodes, edges, {
      nodeId: payload.nodeId,
      status: payload.status,
    })
    upsertRuntimeRecord(payload.nodeId, { status: payload.status })
  }
  else if (type === 'node_retry') {
    applyNodeRetryToGraph(nodes, {
      nodeId: payload.nodeId,
      retryIndex: payload.retryIndex,
    })
    upsertRuntimeRecord(payload.nodeId, { status: payload.status || 'running' })
  }
  else if (type === 'human_input_required') {
    applyHumanInputRequiredToGraph(nodes, payload.nodeId)
    upsertRuntimeRecord(payload.nodeId, { status: 'paused' })
  }

  // Vue Flow only re-renders node/edge chrome when `data` identity changes.
  if (type)
    refreshGraphRuntimeBindings(nodes, edges)
}

/** Camera follow root nodes on node_started (skip nested iteration/loop children). */
function followRunningNode(node) {
  if (!node || node.parentNode || node.parentId)
    return
  const el = containerRef.value
  const clientWidth = el?.clientWidth || 0
  const clientHeight = el?.clientHeight || 0
  if (!clientWidth || !clientHeight || typeof setViewport !== 'function')
    return
  const zoom = viewport.value?.zoom ?? 1
  const width = node.dimensions?.width || node.width || 240
  const height = node.dimensions?.height || node.height || 90
  setViewport(computeFollowViewport({
    position: node.position || { x: 0, y: 0 },
    width,
    height,
    zoom,
    clientWidth,
    clientHeight,
    panelOffset: (
      (showDebugPreview.value ? previewPanelWidth.value : 0)
      + (activePanelNodeId.value ? drawerWidth.value : 0)
    ),
  }))
}

function runNodeFromUi(nodeId) {
  const node = findNode(nodeId)
  const nodeType = node?.data?.type || node?.type
  const isChild = !!(node?.parentNode || node?.parentId)
  if (!canRunBySingle(nodeType, isChild))
    return

  selectNode(nodeId)
  activePanelNodeId.value = nodeId
  // watch resets tab to settings on id change; open LAST RUN after that.
  nextTick(() => {
    nodePanelTab.value = 'last-run'
  })
}

function handleLastRunSubmit({ nodeId, inputs }) {
  if (!nodeId || singleRunningNodeId.value)
    return
  singleRunningNodeId.value = nodeId
  const node = findNode(nodeId)
  if (node?.data) {
    node.data._singleRunningStatus = 'running'
    node.data._runningStatus = 'running'
    refreshGraphRuntimeBindings([node], [])
  }
  const runNodeType = node?.data?.type || node?.type
  const runInputs = runNodeType === BlockEnum.Code
    ? buildCodeRunInputs(node.data, inputs || {})
    : runNodeType === BlockEnum.TemplateTransform
      ? buildTemplateRunInputs(node.data, inputs || {})
      : runNodeType === BlockEnum.DocExtractor
        ? buildDocumentExtractorRunInputs(inputs || {})
        : (inputs || {})
  emit('run-node', { nodeId, inputs: runInputs })
}

/** Apply sync single-node POST result (not full-workflow SSE). */
function applySingleNodeRunResult(nodeId, result = {}) {
  singleRunningNodeId.value = ''
  if (!nodeId)
    return
  const status = result.status || (result.error ? 'failed' : 'succeeded')
  const node = findNode(nodeId)
  if (node?.data) {
    node.data._singleRunningStatus = status
    node.data._runningStatus = status
    refreshGraphRuntimeBindings([node], [])
  }
  singleRunResults.value = {
    ...singleRunResults.value,
    [nodeId]: {
      ...result,
      status,
      nodeId,
    },
  }
  upsertRuntimeRecord(nodeId, {
    status,
    inputs: result.inputs,
    outputs: result.outputs,
    error: result.error,
  })
  bumpInspectRefresh()
}

function openDebugPreview() {
  refreshStartVariables()
  applyPanelExclusivity(panelFlags(), PANEL_KEYS.debug, { open: true })
  showDebugPreview.value = true
  emit('update:active-run-tab', 'INPUT')
}

function closeDebugPreview() {
  showDebugPreview.value = false
  // Contrasts Dify handleCancelDebugAndPreviewPanel: clear node/edge run paint
  if (viewingHistory.value)
    exitHistoryView()
  else
    clearRuntimeState()
}

function toggleDebugPreview() {
  if (showDebugPreview.value) {
    closeDebugPreview()
    return
  }
  openDebugPreview()
}

function onActiveRunTabChange(tab) {
  emit('update:active-run-tab', tab)
}

function handleDebugSubmitRun(payload) {
  exitHistoryView()
  clearRuntimeState()
  emit('run-workflow', payload)
}

function clearRuntimeState() {
  runtimeRecords.value = {}
  clearGraphRuntime(getNodes.value, getEdges.value)
  refreshGraphRuntimeBindings(getNodes.value, getEdges.value)
}

function handleRuntimeNodeSelect(nodeId) {
  selectNode(nodeId)
  activePanelNodeId.value = nodeId
}

provide('workflowCore', {
  removeEdge: (id) => {
    recordHistory()
    removeEdges([id])
  },
  removeNode,
  duplicateNode,
  copyNode,
  updateNodeData,
  replaceStartPlaceholder,
  recordHistory,
  runNode: runNodeFromUi,
})

provide('workflowUi', {
  openNodeSelector: ({
    direction,
    nodeId,
    sourceHandle = 'source',
    targetHandle = 'target',
    edgeId,
    parentId,
    clientX,
    clientY,
    placeImmediately = false,
    mode = 'default',
    preferSourcePosition = false,
  } = {}) => {
    if (readOnly.value) return
    const context = normalizeNodeSelectorContext({
      direction,
      nodeId,
      sourceHandle,
      targetHandle,
      edgeId,
      parentId,
    })
    pendingEdgeId.value = context.edgeId
    pendingConnection.value = context.connection
    pendingTargetConnection.value = context.targetConnection
    pendingParentId.value = context.parentId
    selectorAllowsLoopEnd.value = canAddLoopEnd({
      nodes: getNodes.value,
      parentId: context.parentId,
    })
    selectorDirection.value = context.direction
    pendingPreferSourcePosition.value = Boolean(preferSourcePosition)
    placeImmediatelyOnSelect.value = !!placeImmediately || !!(edgeId || nodeId || parentId)
    selectorMode.value = mode
    // 句柄 / 边 / NextStep / 容器内添加：不对齐 AddBlock，不开 Start 页签
    selectorShowStartTab.value = false
    if (Number.isFinite(clientX) && Number.isFinite(clientY))
      openMenuAtClient(clientX, clientY, { showStartTab: false })
    else {
      const rect = containerRef.value?.getBoundingClientRect()
      if (rect) {
        openMenuAtClient(rect.left + rect.width / 2, rect.top + rect.height / 3, {
          showStartTab: false,
        })
      }
    }
  },
})

/** 供 Panel 内 VarReferencePicker 读取画布 nodes/edges */
provide('workflowGraph', {
  getNodes: () => getNodes.value,
  getEdges: () => getEdges.value,
})
provide('workflowAppId', computed(() => props.appId))
provide('workflowMode', computed(() => props.workflowMode))
provide('bundledNodeIds', bundledNodeIds)
provide('addSelectionToWorkflowAssist', async (clickedNodeId) => {
  const nodeIds = selectedAssistNodeIds(getNodes.value, clickedNodeId)
  if (!nodeIds.length)
    return false
  workflowAssist.open()
  await nextTick()
  return workflowAssistDockRef.value?.addTargetNodes?.(nodeIds) ?? false
})

onMounted(() => {
  // Do NOT init graph from props here. Parent always calls initializeDraft() with
  // the backend draft; doing both caused setEdges + isValidConnection to drop
  // every edge as a "duplicate". Also do not deep-watch props.nodes/edges.
  store.setEnvironmentVariables(props.environmentVariables)
  store.setConversationVariables(props.conversationVariables)
  store.setRagPipelineVariables(props.ragPipelineVariables || [])
  startDraftPolling()
})

watch(
  () => [
    JSON.stringify(props.environmentVariables || []),
    JSON.stringify(props.conversationVariables || []),
    JSON.stringify(props.ragPipelineVariables || []),
  ],
  () => {
    store.setEnvironmentVariables(props.environmentVariables)
    store.setConversationVariables(props.conversationVariables)
    store.setRagPipelineVariables(props.ragPipelineVariables || [])
  },
)

const activePanelNodeId = ref(null)
const nodePanelTab = ref('settings')
const singleRunResults = ref({})
const singleRunningNodeId = ref('')

/**
 * Plain snapshot of the open panel node. MUST NOT be a computed(findNode):
 * Vue Flow rewrites node dimensions during layout; tracking getNodes in this
 * parent re-renders WorkflowCanvas and blows the recursive-update limit.
 */
const activePanelNode = shallowRef(null)

function refreshActivePanelNode() {
  const id = activePanelNodeId.value
  if (!id) {
    activePanelNode.value = null
    return
  }
  openNodePanelState({
    nodeId: id,
    findNode,
    activeNodeId: activePanelNodeId,
    activeNode: activePanelNode,
  })
}

const panelSupportsSingleRun = computed(() => {
  const node = activePanelNode.value
  if (!node)
    return false
  const type = node.data?.type || node.type
  const isChild = !!(node.parentNode || node.parentId)
  return canRunBySingle(type, isChild)
})

watch(activePanelNodeId, () => {
  nodePanelTab.value = 'settings'
  refreshActivePanelNode()
})

const currentPanelComponent = computed(() => {
  if (!activePanelNode.value) return null
  const type = activePanelNode.value.data?.type || activePanelNode.value.type
  return PANEL_COMPONENT_MAP[String(type || '').toLowerCase()] || null
})

const isDraggingNode = ref(false)
let nodeDragTimer = null

function handlePaneClick(event) {
  if (effectiveControlMode.value === 'comment') {
    const e = event?.event || event
    if (e?.clientX !== undefined) {
      comments.value.push({
        id: `comment-${Date.now()}`,
        position: vueFlow.screenToFlowCoordinate({ x: e.clientX, y: e.clientY }),
        text: '',
        author: '我',
        createdAt: Date.now(),
        resolved: false,
      })
    }
    return
  }
  if (candidateNode.value) {
    commitCandidateNode()
    return
  }
  clearSelection()
  activePanelNodeId.value = null
  menuVisible.value = false
}

function openNodeDetailPanel(nodeId) {
  // Defer panel mount until after Vue Flow selection / menu unmount patches finish.
  // Sync open during those updates can hit "Cannot set properties of null (__vnode)".
  nextTick(() => {
    openNodePanelState({
      nodeId,
      findNode,
      activeNodeId: activePanelNodeId,
      activeNode: activePanelNode,
    })
  })
}

function handlePanelSelectNode(id) {
  selectNode(id)
  openNodeDetailPanel(id)
}

function handleNodeClick({ node, event }) {
  if (event?.shiftKey) {
    handleSelectionChange()
  } else if (!(node.selected && getSelectedNodes.value.length > 1)) {
    selectNode(node.id)
  }
  menuVisible.value = false
  if (isDraggingNode.value) return
  openNodeDetailPanel(node.id)
}

function handleNodeDoubleClick({ node }) {
  selectNode(node.id)
  openNodeDetailPanel(node.id)
  menuVisible.value = false
}

function handleEdgeDblClick({ edge, event }) {
  if (readOnly.value) return
  event?.stopPropagation?.()
  recordHistory()
  removeEdges([edge.id])
}

function handleEdgeMouseEnter({ edge }) {
  if (!edge.data) edge.data = {}
  edge.data._hovering = true
}

function handleEdgeMouseLeave({ edge }) {
  if (edge?.data) edge.data._hovering = false
}

function handleNodeDragStart() {
  isDraggingNode.value = true
  if (!readOnly.value)
    recordHistory()
}

const helpLineX = ref(null)
const helpLineY = ref(null)

function updateHelpLines(node) {
  const zoom = viewport.value?.zoom || 1
  const offsetX = viewport.value?.x || 0
  const offsetY = viewport.value?.y || 0
  const threshold = 4 / zoom
  let matchedX = null
  let matchedY = null

  for (const other of getNodes.value) {
    if (other.id === node.id || other.parentNode !== node.parentNode)
      continue
    if (matchedX === null && Math.abs(other.position.x - node.position.x) <= threshold)
      matchedX = other.position.x
    if (matchedY === null && Math.abs(other.position.y - node.position.y) <= threshold)
      matchedY = other.position.y
    if (matchedX !== null && matchedY !== null)
      break
  }

  if (matchedX !== null)
    node.position.x = matchedX
  if (matchedY !== null)
    node.position.y = matchedY
  helpLineX.value = matchedX === null ? null : matchedX * zoom + offsetX
  helpLineY.value = matchedY === null ? null : matchedY * zoom + offsetY
}

function handleNodeDragStop() {
  helpLineX.value = null
  helpLineY.value = null
  if (nodeDragTimer) clearTimeout(nodeDragTimer)
  nodeDragTimer = setTimeout(() => {
    isDraggingNode.value = false
  }, 100)
}

function syncBundledSelection() {
  const list = getSelectedNodes.value
  const selectedIds = list.map(node => node.id)
  // CRITICAL: never mutate node.data / edge.data here. Vue Flow emits
  // selection-change while updating selection; writing node.data in that
  // handler re-enters the same flush → Maximum recursive updates.
  const nextBundled = selectedIds.length > 1 ? selectedIds : []
  const nextKey = nextBundled.join('\0')
  if (nextKey !== lastBundledKey) {
    lastBundledKey = nextKey
    bundledNodeIds.value = nextBundled
  }
  const nextSelected = selectedIds[0] || null
  if (store.selectedNodeId !== nextSelected)
    store.setSelectedNodeId(nextSelected)
}

function handleSelectionChange() {
  syncBundledSelection()
}

function handleSelectionStart() {
  if (lastBundledKey !== '') {
    lastBundledKey = ''
    bundledNodeIds.value = []
  }
}

function handleSelectionDragStart() {
  if (!readOnly.value)
    recordHistory()
}

function handleSelectionDragStop() {
  syncBundledSelection()
}

function handleClosePanel() {
  activePanelNodeId.value = null
}

function handleNodeDataUpdate(newData) {
  if (!activePanelNodeId.value) return
  updateNodeData(activePanelNodeId.value, newData)
  refreshActivePanelNode()
  const type = newData?.type || activePanelNode.value?.data?.type || activePanelNode.value?.type
  if (type === 'start')
    refreshStartVariables()
}

function handleNodeDrag({ node }) {
  updateHelpLines(node)
  if (!node.parentNode) return
  const parentNode = findNode(node.parentNode)
  if (!parentNode) return

  const isLoop = parentNode.type === 'loop' || parentNode.data?.type === 'loop'
  const restricted = isLoop
    ? getRestrictedLoopPosition(node, parentNode)
    : getRestrictedIterationPosition(node, parentNode)

  if (restricted.x !== undefined) node.position.x = restricted.x
  if (restricted.y !== undefined) node.position.y = restricted.y

  const childrenNodes = getNodes.value.filter((n) => n.parentNode === parentNode.id)
  const bounds = isLoop ? getLoopContainerBounds(childrenNodes) : getIterationContainerBounds(childrenNodes)
  const resize = isLoop
    ? getLoopContainerResize(parentNode, bounds)
    : getIterationContainerResize(parentNode, bounds)

  if (resize.width) parentNode.style = { ...parentNode.style, width: `${resize.width}px` }
  if (resize.height) parentNode.style = { ...parentNode.style, height: `${resize.height}px` }
}

function resizeContainerToFit(parentNode) {
  if (!parentNode)
    return
  const children = getNodes.value.filter(node => (node.parentNode || node.parentId) === parentNode.id)
  const size = getContainerFitSize({
    currentWidth: Number.parseFloat(parentNode.style?.width) || parentNode.dimensions?.width || parentNode.width,
    currentHeight: Number.parseFloat(parentNode.style?.height) || parentNode.dimensions?.height || parentNode.height,
    children,
  })
  const currentWidth = Number.parseFloat(parentNode.style?.width) || parentNode.dimensions?.width || parentNode.width
  const currentHeight = Number.parseFloat(parentNode.style?.height) || parentNode.dimensions?.height || parentNode.height
  if (size.width <= currentWidth && size.height <= currentHeight)
    return
  parentNode.style = {
    ...parentNode.style,
    width: `${Math.max(size.width, currentWidth || 0)}px`,
    height: `${Math.max(size.height, currentHeight || 0)}px`,
  }
}

async function handleNodesChange(changes = []) {
  const changedIds = changes
    .filter(change => change.type === 'dimensions' || change.type === 'add')
    .map(change => change.id || change.item?.id)
    .filter(Boolean)
  if (!changedIds.length)
    return

  await nextTick()
  const parentIds = new Set()
  for (const id of changedIds) {
    const node = findNode(id)
    const parentId = node?.parentNode || node?.parentId
    if (parentId)
      parentIds.add(parentId)
  }
  for (const parentId of parentIds)
    resizeContainerToFit(findNode(parentId))
}

const menuVisible = ref(false)
const menuX = ref(0)
const menuY = ref(0)
const menuFlowPos = ref({ x: 0, y: 0 })
const pendingConnection = ref(null)
const pendingTargetConnection = ref(null)
const pendingEdgeId = ref(null)
const pendingParentId = ref(null)
const selectorAllowsLoopEnd = ref(false)
const pendingPreferSourcePosition = ref(false)
const placeImmediatelyOnSelect = ref(false)
const selectorMode = ref('default')
const selectorDirection = ref('free')
/** 仅工具栏 / 右键「添加节点」开启（对齐官方 AddBlock showStartTab） */
const selectorShowStartTab = ref(false)
const workflowAllowsStartTab = computed(() => !isChatflowMode(props.workflowMode))
/**
 * Start-node flags for BlockSelectorMenu. Keep as refs updated by a signature watch —
 * never `computed(() => getNodes...)` in this parent: Vue Flow rewrites selection /
 * dimensions often enough that a template-bound computed re-renders the whole canvas
 * shell and races CustomEdge Teleport → "Cannot set properties of null (__vnode)".
 */
const canvasHasStartPlaceholder = ref(false)
const canvasHasStartNode = ref(false)

watch(
  () => {
    const nodes = getNodes.value || []
    let hasPlaceholder = false
    let hasStart = false
    for (const node of nodes) {
      const type = node.data?.type || node.type
      if (type === 'start-placeholder')
        hasPlaceholder = true
      if (type === 'start')
        hasStart = true
      if (hasPlaceholder && hasStart)
        break
    }
    return `${hasPlaceholder ? 1 : 0}${hasStart ? 1 : 0}:${nodes.length}`
  },
  (sig) => {
    canvasHasStartPlaceholder.value = sig[0] === '1'
    canvasHasStartNode.value = sig[1] === '1'
  },
  { immediate: true },
)
const candidateNode = ref(null)
const candidateScreenPos = ref({ x: 0, y: 0 })
const candidateFlowPos = ref({ x: 0, y: 0 })
const candidateTitle = computed(() => candidateNode.value ? getNodeTitle(candidateNode.value.type) : '')
const connectingFrom = ref(null)
const connectionCompleted = ref(false)
const contextMenu = ref({
  visible: false,
  type: 'pane',
  x: 0,
  y: 0,
  nodeId: null,
  edgeId: null,
})

function getRelativePointer(event) {
  const e = event?.event || event
  const rect = containerRef.value?.getBoundingClientRect()
  if (!e || !rect) return null
  return {
    event: e,
    x: e.clientX - rect.left,
    y: e.clientY - rect.top,
  }
}

function openContextMenu(type, event, target = {}) {
  const pointer = getRelativePointer(event)
  if (!pointer) return
  pointer.event.preventDefault?.()
  menuVisible.value = false
  contextMenu.value = {
    visible: true,
    type,
    x: pointer.x,
    y: pointer.y,
    nodeId: target.nodeId || null,
    edgeId: target.edgeId || null,
  }
}

function handleConnectStart(payload) {
  if (payload?.handleType && payload.handleType !== 'source') {
    connectingFrom.value = null
    return
  }
  const nodeId = payload?.nodeId || payload?.node?.id
  const sourceHandle = payload?.handleId || payload?.sourceHandle || 'source'
  connectingFrom.value = nodeId ? { source: nodeId, sourceHandle } : null
  connectionCompleted.value = false
}

function handleConnect(connection) {
  connectionCompleted.value = true
  onConnect(connection)
}

function handleConnectEnd(event) {
  const e = event?.event || event
  const shouldOpenSelector = connectingFrom.value
    && !connectionCompleted.value
    && e?.target?.classList?.contains?.('vue-flow__pane')

  if (shouldOpenSelector) {
    const rect = containerRef.value?.getBoundingClientRect()
    if (rect) {
      menuX.value = e.clientX - rect.left
      menuY.value = e.clientY - rect.top
      menuFlowPos.value = vueFlow.screenToFlowCoordinate({ x: e.clientX, y: e.clientY })
      pendingConnection.value = { ...connectingFrom.value }
      pendingTargetConnection.value = null
      pendingEdgeId.value = null
      selectorDirection.value = 'after'
      selectorShowStartTab.value = false
      selectorMode.value = 'default'
      menuVisible.value = true
    }
  }
  connectingFrom.value = null
  connectionCompleted.value = false
}

function handleCanvasMouseMove(event) {
  const rect = containerRef.value?.getBoundingClientRect()
  if (!rect) return
  const now = Date.now()
  if (now - lastCursorEmitAt >= 50) {
    lastCursorEmitAt = now
    emit('cursor-move', {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    })
  }
  if (!candidateNode.value) return
  candidateScreenPos.value = {
    x: event.clientX - rect.left + 12,
    y: event.clientY - rect.top + 12,
  }
  candidateFlowPos.value = vueFlow.screenToFlowCoordinate({
    x: event.clientX,
    y: event.clientY,
  })
}

function updateComment({ id, text }) {
  const comment = comments.value.find(item => item.id === id)
  if (comment) comment.text = text
}

function resolveComment(id) {
  const comment = comments.value.find(item => item.id === id)
  if (comment) comment.resolved = true
}

function deleteComment(id) {
  comments.value = comments.value.filter(item => item.id !== id)
}

function applyCollaborationState({ cursors, comments: nextComments } = {}) {
  if (cursors)
    collaborationCursors.value = [...cursors]
  if (nextComments)
    comments.value = structuredClone(nextComments)
}

function cancelCandidateNode() {
  candidateNode.value = null
}

function commitCandidateNode() {
  if (!candidateNode.value) return
  const candidate = candidateNode.value
  const position = { ...candidateFlowPos.value }
  const node = candidate.edgeId
    ? insertNodeOnEdge(candidate.type, candidate.edgeId, { position, data: candidate.data })
    : candidate.connection
      ? addConnectedNode(candidate.type, { ...candidate.connection, position, data: candidate.data })
      : addNode(candidate.type, {
        position,
        parentId: candidate.parentId || undefined,
        data: candidate.data,
      })

  candidateNode.value = null
  if (node) {
    selectNode(node.id)
    openNodeDetailPanel(node.id)
  }
}

function handlePaneContextMenu(event) {
  if (readOnly.value) return
  const e = event?.event || event
  e?.preventDefault?.()
  if (candidateNode.value) {
    cancelCandidateNode()
    return
  }

  const pointer = getRelativePointer(e)
  if (!pointer) return
  // Dify-like: blank canvas right-click opens block selector directly
  pendingConnection.value = null
  pendingTargetConnection.value = null
  pendingEdgeId.value = null
  pendingParentId.value = null
  selectorDirection.value = 'free'
  placeImmediatelyOnSelect.value = true
  selectorMode.value = 'default'
  selectorShowStartTab.value = workflowAllowsStartTab.value
  menuX.value = pointer.x
  menuY.value = pointer.y
  menuFlowPos.value = vueFlow.screenToFlowCoordinate({ x: e.clientX, y: e.clientY })
  contextMenu.value.visible = false
  menuVisible.value = true
}

function handleNodeContextMenu({ node, event }) {
  if (readOnly.value) return
  if (!node.selected)
    selectNode(node.id)
  openContextMenu(getSelectedNodes.value.length > 1 ? 'selection' : 'node', event, { nodeId: node.id })
}

function handleEdgeContextMenu({ edge, event }) {
  if (readOnly.value) return
  openContextMenu('edge', event, { edgeId: edge.id })
}

function handleSelectionContextMenu(event) {
  if (readOnly.value) return
  openContextMenu('selection', event)
}

function openBlockSelectorFromContext({
  placeImmediately = false,
  mode = 'default',
  showStartTab = false,
} = {}) {
  const rect = containerRef.value?.getBoundingClientRect()
  if (!rect) return
  menuX.value = contextMenu.value.x
  menuY.value = contextMenu.value.y
  menuFlowPos.value = vueFlow.screenToFlowCoordinate({
    x: rect.left + contextMenu.value.x,
    y: rect.top + contextMenu.value.y,
  })
  placeImmediatelyOnSelect.value = placeImmediately
  selectorMode.value = mode
  selectorShowStartTab.value = !!showStartTab && workflowAllowsStartTab.value
  menuVisible.value = true
}

function handleContextMenuAction(action) {
  const { type, nodeId, edgeId } = contextMenu.value
  contextMenu.value.visible = false

  if (action === 'add-node') {
    pendingConnection.value = null
    pendingTargetConnection.value = null
    pendingEdgeId.value = null
    pendingParentId.value = null
    selectorDirection.value = 'free'
    openBlockSelectorFromContext({ placeImmediately: true, showStartTab: true })
  } else if (action === 'add-note') {
    const rect = containerRef.value?.getBoundingClientRect()
    if (rect) {
      candidateNode.value = { type: 'note', edgeId: null, connection: null, parentId: null }
      candidateScreenPos.value = { x: contextMenu.value.x + 12, y: contextMenu.value.y + 12 }
      candidateFlowPos.value = vueFlow.screenToFlowCoordinate({
        x: rect.left + contextMenu.value.x,
        y: rect.top + contextMenu.value.y,
      })
    }
  } else if (action === 'paste') {
    paste()
  } else if (action === 'select-all') {
    getNodes.value
      .filter(node => node.selectable !== false)
      .forEach((node) => { node.selected = true })
  } else if (action === 'copy') {
    copySelection()
  } else if (action === 'duplicate') {
    copySelection()
    paste()
  } else if (action === 'run-node' && nodeId) {
    runNodeFromUi(nodeId)
  } else if (action === 'insert-node' && edgeId) {
    pendingEdgeId.value = edgeId
    pendingConnection.value = null
    pendingTargetConnection.value = null
    pendingParentId.value = null
    selectorDirection.value = 'insert'
    openBlockSelectorFromContext({ placeImmediately: true, showStartTab: false })
  } else if (action === 'delete') {
    if (type === 'edge' && edgeId) {
      recordHistory()
      removeEdges([edgeId])
    } else {
      deleteSelected()
    }
  }
}

function openMenuAtCenter({ showStartTab } = {}) {
  const rect = containerRef.value?.getBoundingClientRect()
  if (!rect) return
  // Left control rail: pick type then click canvas to place (candidate mode)
  pendingConnection.value = null
  pendingTargetConnection.value = null
  pendingEdgeId.value = null
  pendingParentId.value = null
  selectorDirection.value = 'free'
  placeImmediatelyOnSelect.value = false
  selectorMode.value = 'default'
  openMenuAtClient(rect.left + rect.width / 2, rect.top + rect.height / 3, {
    showStartTab: showStartTab ?? workflowAllowsStartTab.value,
  })
}

function openMenuAtClient(clientX, clientY, { showStartTab } = {}) {
  const rect = containerRef.value?.getBoundingClientRect()
  if (!rect) return
  if (selectorMode.value !== 'container')
    selectorAllowsLoopEnd.value = false
  if (showStartTab !== undefined)
    selectorShowStartTab.value = !!showStartTab && workflowAllowsStartTab.value
  menuX.value = clientX - rect.left
  menuY.value = clientY - rect.top
  menuFlowPos.value = vueFlow.screenToFlowCoordinate({ x: clientX, y: clientY })
  menuVisible.value = true
}

function startNoteCandidate() {
  const rect = containerRef.value?.getBoundingClientRect()
  if (!rect) return
  const clientX = rect.left + rect.width / 2
  const clientY = rect.top + rect.height / 3
  candidateNode.value = {
    type: 'note',
    edgeId: null,
    connection: null,
    parentId: null,
  }
  candidateFlowPos.value = vueFlow.screenToFlowCoordinate({ x: clientX, y: clientY })
  candidateScreenPos.value = { x: rect.width / 2 + 12, y: rect.height / 3 + 12 }
}

function handleBlockSelect(payload) {
  // Close the selector first; apply the pick on the next tick so we never patch
  // candidate/panel DOM in the same flush as BlockSelectorMenu's v-if unmount.
  menuVisible.value = false
  const type = typeof payload === 'string' ? payload : payload?.type
  const extraData = typeof payload === 'string' ? undefined : payload?.data
  if (!type) return

  const edgeId = pendingEdgeId.value
  const connection = pendingConnection.value ? { ...pendingConnection.value } : null
  const targetConnection = pendingTargetConnection.value
    ? { ...pendingTargetConnection.value }
    : null
  const parentId = pendingParentId.value
  const preferSourcePosition = pendingPreferSourcePosition.value
  const shouldPlaceNow = placeImmediatelyOnSelect.value
  const position = { ...menuFlowPos.value }
  const screenX = menuX.value + 12
  const screenY = menuY.value + 12

  pendingConnection.value = null
  pendingTargetConnection.value = null
  pendingEdgeId.value = null
  pendingParentId.value = null
  selectorAllowsLoopEnd.value = false
  pendingPreferSourcePosition.value = false
  placeImmediatelyOnSelect.value = false
  selectorMode.value = 'default'
  selectorDirection.value = 'free'
  selectorShowStartTab.value = false
  // Start 页签选项与普通节点相同：走 addNode / candidate，不调用 replaceStartPlaceholder

  nextTick(() => {
    if (shouldPlaceNow) {
      const node = edgeId
        ? insertNodeOnEdge(type, edgeId, { position, data: extraData })
        : targetConnection
          ? addPredecessorNode(type, {
            ...targetConnection,
            ...(preferSourcePosition ? {} : { position }),
            data: extraData,
          })
        : connection
          ? addConnectedNode(type, {
            ...connection,
            ...(preferSourcePosition ? {} : { position }),
            data: extraData,
          })
          : addNode(type, { position, parentId: parentId || undefined, data: extraData })
      if (node) {
        selectNode(node.id)
        openNodeDetailPanel(node.id)
      }
      return
    }

    candidateNode.value = {
      type,
      data: extraData,
      edgeId,
      connection,
      parentId,
    }
    candidateFlowPos.value = position
    candidateScreenPos.value = { x: screenX, y: screenY }
  })
}

function onDocClick() {
  menuVisible.value = false
  contextMenu.value.visible = false
}

function handleKeyDown(event) {
  const tag = (event.target?.tagName || '').toLowerCase()
  const mod = event.ctrlKey || event.metaKey
  if (mod && event.key.toLowerCase() === 's') {
    event.preventDefault()
    if (!readOnly.value)
      saveWorkflowDraft()
    return
  }
  if (mod && event.key.toLowerCase() === 'j') {
    event.preventDefault()
    toggleWorkflowAssist()
    return
  }
  if (tag === 'input' || tag === 'textarea' || event.target?.isContentEditable)
    return

  if (!readOnly.value && (event.key === 'Delete' || event.key === 'Backspace')) {
    event.preventDefault()
    deleteSelected()
    return
  }

  if (mod && event.key.toLowerCase() === 'a') {
    event.preventDefault()
    getNodes.value.forEach((node) => {
      if (node.selectable !== false)
        node.selected = true
    })
    handleSelectionChange()
    return
  }

  if (mod && event.key.toLowerCase() === 'c') {
    event.preventDefault()
    copySelection()
    return
  }

  if (!readOnly.value && mod && event.key.toLowerCase() === 'x') {
    event.preventDefault()
    copySelection()
    deleteSelected()
    return
  }

  if (!readOnly.value && mod && event.key.toLowerCase() === 'v') {
    event.preventDefault()
    paste()
    return
  }

  if (event.code === 'Space' || event.key === ' ') {
    if (!isSpaceHeld.value) {
      isSpaceHeld.value = true
    }
    event.preventDefault()
  }

  if (event.key === 'Escape') {
    if (candidateNode.value)
      cancelCandidateNode()
    else
      clearSelection()
    activePanelNodeId.value = null
    event.preventDefault()
    return
  }

  if (event.key.toLowerCase() === 'v')
    controlMode.value = 'pointer'
  if (event.key.toLowerCase() === 'h')
    controlMode.value = 'hand'
}

function handleKeyUp(event) {
  if (event.code === 'Space' || event.key === ' ') {
    isSpaceHeld.value = false
  }
}

function handleWindowBlur() {
  isSpaceHeld.value = false
}

function handleZoomIn() {
  zoomIn({ duration: 180 })
}

function handleZoomOut() {
  zoomOut({ duration: 180 })
}

function handleFitView() {
  fitView({ padding: 0.2, duration: 260 })
}

function handleOrganize() {
  organizeNodes()
  requestAnimationFrame(handleFitView)
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('keyup', handleKeyUp)
  window.addEventListener('blur', handleWindowBlur)
  window.addEventListener('beforeunload', handleBeforeUnload)
})
onUnmounted(() => {
  flushDraftIfNeeded()
  stopDraftPolling()
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('keydown', handleKeyDown)
  window.removeEventListener('keyup', handleKeyUp)
  window.removeEventListener('blur', handleWindowBlur)
  window.removeEventListener('beforeunload', handleBeforeUnload)
})

const drawerWidth = ref(420)
const previewPanelWidth = ref(420)
const canvasPanelOffset = computed(() => {
  const overlayWidth = Math.max(
    showVariables.value ? 438 : 0,
    showChecklist.value ? 384 : 0,
    showHistory.value ? 364 : 0,
    showRunHistory.value ? 376 : 0,
    showFeatures.value ? 376 : 0,
  )
  const stackedPanelWidth = (showDebugPreview.value ? previewPanelWidth.value : 0)
    + (activePanelNodeId.value ? drawerWidth.value : 0)
  return `${Math.max(14, overlayWidth, stackedPanelWidth + 14)}px`
})
defineExpose({
  initFromGraph,
  initializeDraft,
  exportGraph,
  buildDraftPayload,
  addNode,
  applyNodeRunState,
  applySingleNodeRunResult,
  applyCollaborationState,
  clearRuntimeState,
  openDebugPreview,
  markDraftSaved,
  markDraftSaveFailed,
  refreshVersionHistory,
  flushDraftIfNeeded,
  undo,
  redo,
})
</script>

<style scoped>
.workflow-canvas-container {
  position: relative;
  height: 100%;
  width: 100%;
  overflow: hidden;
  background: var(--workflow-canvas-bg, #f2f4f7);
}

.history-view-banner {
  position: absolute;
  top: 56px;
  left: 50%;
  z-index: 58;
  display: flex;
  transform: translateX(-50%);
  align-items: center;
  gap: 12px;
  padding: 8px 14px;
  border: 1px solid #b2ccff;
  border-radius: 999px;
  background: #eff8ff;
  color: #175cd3;
  font-size: 12px;
  box-shadow: 0 4px 12px rgb(16 24 40 / 8%);
}

.history-view-banner button {
  padding: 4px 10px;
  border: 0;
  border-radius: 999px;
  background: #155eef;
  color: #fff;
  font-size: 11px;
  cursor: pointer;
}

/* Aligns with Dify workflow-panel-animation while Running */
.workflow-canvas-container.is-run-following :deep(.vue-flow__viewport) {
  transition: transform 0.3s ease;
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

.help-line {
  position: absolute;
  z-index: 25;
  pointer-events: none;
  background: var(--workflow-link-line-active, #085afc);
}

.help-line-vertical {
  top: 0;
  bottom: 0;
  width: 1px;
}

.help-line-horizontal {
  right: 0;
  left: 0;
  height: 1px;
}

.workflow-assist-host {
  position: absolute;
  top: 52px;
  bottom: 0;
  left: 0;
  z-index: 50;
}

.assist-preview-notice {
  position: absolute;
  top: 60px;
  left: 50%;
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: min(560px, calc(100% - 48px));
  transform: translateX(-50%);
  margin: 0;
  padding: 8px 12px;
  border: 1px solid #b2ddff;
  border-radius: 8px;
  background: #eff8ff;
  color: #175cd3;
  font-size: 12px;
  line-height: 1.4;
}

.assist-preview-notice p {
  margin: 0;
}

.assist-preview-notice button {
  flex-shrink: 0;
  border: 1px solid #84adff;
  border-radius: 6px;
  padding: 4px 8px;
  background: #fff;
  color: #175cd3;
  cursor: pointer;
}

.right-panel-stack {
  position: absolute;
  top: 52px;
  right: 0;
  bottom: 0;
  z-index: 55;
  display: flex;
  flex-direction: row;
  align-items: stretch;
  max-width: 100%;
  pointer-events: none;
}

.right-panel-stack > * {
  pointer-events: auto;
}

.debug-panel-host {
  position: relative;
  flex-shrink: 0;
  height: 100%;
  min-width: 360px;
  border-left: 1px solid var(--components-panel-border, #e4e7ec);
  background: var(--components-panel-bg, #ffffff);
  box-shadow: -8px 0 24px rgba(16, 24, 40, 0.06);
}

/* Contrasts Dify panel stack: debug sits to the right of node panel, not under it. */
.right-panel-stack :deep(.workflow-run-panel),
.right-panel-stack :deep(.chat-debug-panel) {
  position: relative;
  top: auto;
  right: auto;
  bottom: auto;
  width: 100%;
  height: 100%;
  z-index: auto;
  box-shadow: none;
  border-left: 0;
}

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}
</style>

<style>
@import '@vue-flow/core/dist/style.css';
@import '@vue-flow/core/dist/theme-default.css';

.vue-flow__edges {
  z-index: 5 !important;
}
.vue-flow__edge-path {
  stroke-width: 2;
}

.vue-flow__selection,
.vue-flow__nodesselection-rect {
  border: 1px solid #2970ff !important;
  border-radius: 4px;
  background: rgba(41, 112, 255, 0.08) !important;
}

.vue-flow__pane {
  cursor: default;
}

.workflow-canvas-container[data-control-mode="hand"] .vue-flow__pane {
  cursor: grab !important;
}

.workflow-canvas-container[data-control-mode="hand"] .vue-flow__pane.dragging {
  cursor: grabbing !important;
}

.workflow-canvas-container[data-control-mode="pointer"] .vue-flow__pane {
  cursor: default !important;
}

.vue-flow__connection-path {
  stroke: var(--workflow-link-line-active, #2970ff);
  stroke-width: 2;
}

.vue-flow__minimap {
  right: clamp(14px, var(--canvas-panel-offset, 14px), calc(100% - 300px)) !important;
  bottom: 64px !important;
  width: 104px;
  height: 72px;
  overflow: hidden;
  border: 1px solid var(--components-actionbar-border, rgba(16, 24, 40, 0.08));
  border-radius: 8px;
  background: var(--workflow-minimap-bg, #e9ebf0);
  box-shadow: 0 4px 12px rgba(16, 24, 40, 0.08);
}

.right-drawer-wrapper .panel-header {
  min-height: 56px !important;
  box-sizing: border-box;
  padding: 10px 16px !important;
  border-bottom: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08)) !important;
  background: var(--components-panel-bg, #fff) !important;
}

.right-drawer-wrapper .panel-body {
  padding: 16px 20px !important;
  background: var(--components-panel-bg, #fff);
}

.right-drawer-wrapper .form-section {
  padding: 12px;
  border: 1px solid rgba(16, 24, 40, 0.08);
  border-radius: 10px;
  background: #fff;
}

.right-drawer-wrapper .section-label {
  color: #475467 !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.right-drawer-wrapper .el-input__wrapper,
.right-drawer-wrapper .el-select__wrapper,
.right-drawer-wrapper .el-textarea__inner {
  border-radius: 8px;
  box-shadow: 0 0 0 1px #d0d5dd inset;
}
</style>
