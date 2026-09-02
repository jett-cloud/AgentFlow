/**
 * Vue composable wrapping draft-run debug session state.
 */

import { computed, reactive, ref } from 'vue'
import {
  fetchSuggestedQuestions as fetchSuggestedQuestionsApi,
  runDraft,
  stopRun as stopRunApi,
  submitHumanInputForm as submitHumanInputFormApi,
  subscribeWorkflowEvents as subscribeWorkflowEventsApi,
} from '@/features/workflow/api/difyWorkflowApi.js'
import {
  applyWorkflowRunEvent,
  createInitialRunningData,
  RUN_STATUS,
  RUN_TABS,
} from '../runtime/applyWorkflowRunEvent.js'
import {
  appendChatTurn,
  clearChatList,
  updateLastAssistant,
} from '../runtime/chatDebugList.js'
import {
  normalizeSuggestedQuestionsResponse,
  shouldFetchSuggestedAfterAnswer,
} from './workflowFeatures.js'

export {
  applyDebugRunEvent,
  applyWorkflowRunEvent,
  buildStartVariableDefaults,
  createInitialDebugState,
  createInitialRunningData,
  RUN_STATUS,
  RUN_TABS,
  validateRequiredStartInputs,
} from '../runtime/applyWorkflowRunEvent.js'

/**
 * @param {{
 *   runDraftFn?: typeof runDraft,
 *   stopRunFn?: typeof stopRunApi,
 *   submitHumanInputFormFn?: typeof submitHumanInputFormApi,
 *   subscribeWorkflowEventsFn?: typeof subscribeWorkflowEventsApi,
 *   fetchSuggestedQuestionsFn?: typeof fetchSuggestedQuestionsApi,
 * }} [deps]
 */
export function useWorkflowDebugSession(deps = {}) {
  const runDraftFn = deps.runDraftFn || runDraft
  const stopRunFn = deps.stopRunFn || stopRunApi
  const submitHumanInputFormFn = deps.submitHumanInputFormFn || submitHumanInputFormApi
  const subscribeWorkflowEventsFn = deps.subscribeWorkflowEventsFn || subscribeWorkflowEventsApi
  const fetchSuggestedQuestionsFn = deps.fetchSuggestedQuestionsFn || fetchSuggestedQuestionsApi

  const state = reactive(createInitialRunningData())
  const runController = ref(null)
  const activeTab = ref(RUN_TABS.INPUT)
  /** @type {import('vue').Ref<import('../runtime/chatDebugList.js').ChatMessage[]>} */
  const chatList = ref([])
  /** Post-answer suggested questions (Chatflow follow-up). */
  const afterAnswerSuggestions = ref([])

  const canStop = computed(() => state.isRunning && !!state.taskId)

  function syncAssistantBubble() {
    if (!chatList.value.length)
      return
    chatList.value = updateLastAssistant(chatList.value, {
      content: state.resultText || state.runError || '',
      status: state.isRunning ? 'streaming' : state.runStatus,
      error: state.runError || '',
      citation: state.citations || [],
      message_files: state.messageFiles || [],
    })
  }

  function patchState(partial) {
    Object.assign(state, partial)
  }

  function clearAfterAnswerSuggestions() {
    afterAnswerSuggestions.value = []
  }

  function resetForNewRun({ keepConversation = true } = {}) {
    patchState({
      isRunning: false,
      taskId: '',
      workflowRunId: '',
      resultText: '',
      transcript: '',
      runError: '',
      runStatus: RUN_STATUS.idle,
      runOutputs: null,
      result: null,
      tracing: [],
      preferredTab: RUN_TABS.INPUT,
      iterTimes: 1,
      humanInputFormDataList: [],
      humanInputFilledFormDataList: [],
      citations: [],
      messageFiles: [],
      ...(keepConversation
        ? {}
        : { conversationId: null, parentMessageId: null }),
    })
    activeTab.value = RUN_TABS.INPUT
    clearAfterAnswerSuggestions()
  }

  function clearConversation() {
    patchState({
      conversationId: null,
      parentMessageId: null,
      resultText: '',
      transcript: '',
      runError: '',
      tracing: [],
      result: null,
      runOutputs: null,
      runStatus: RUN_STATUS.idle,
      humanInputFormDataList: [],
      humanInputFilledFormDataList: [],
      citations: [],
      messageFiles: [],
    })
    chatList.value = clearChatList()
    clearAfterAnswerSuggestions()
  }

  function setActiveTab(tab) {
    activeTab.value = tab
  }

  function handleEvent(event, onCanvasEvent, { syncChat = false } = {}) {
    const { state: next, nodeState, canvasEvent } = applyWorkflowRunEvent(state, event)
    Object.assign(state, next)
    if (next.preferredTab)
      activeTab.value = next.preferredTab
    if (syncChat)
      syncAssistantBubble()
    // Prefer canvasEvent (includes workflow_started); fall back to nodeState.
    if (canvasEvent)
      onCanvasEvent?.(canvasEvent)
    else if (nodeState?.nodeId)
      onCanvasEvent?.(nodeState)
  }

  async function loadAfterAnswerSuggestions(appId, features) {
    if (!shouldFetchSuggestedAfterAnswer({
      mode: 'advanced-chat',
      runStatus: state.runStatus,
      features,
      messageId: state.parentMessageId,
    })) {
      clearAfterAnswerSuggestions()
      return
    }
    try {
      const payload = await fetchSuggestedQuestionsFn(appId, state.parentMessageId)
      afterAnswerSuggestions.value = normalizeSuggestedQuestionsResponse(payload)
    }
    catch {
      clearAfterAnswerSuggestions()
    }
  }

  async function startRun({
    appId,
    mode = 'workflow',
    inputs = {},
    query = '',
    files = [],
    messageFiles = [],
    features = {},
    syncDraft,
    onCanvasEvent,
    onNodeState,
  } = {}) {
    if (state.isRunning)
      return

    const isChatflow = mode === 'advanced-chat'
    resetForNewRun({ keepConversation: isChatflow })
    if (isChatflow)
      chatList.value = appendChatTurn(chatList.value, query, messageFiles)

    patchState({
      isRunning: true,
      runStatus: RUN_STATUS.running,
      preferredTab: isChatflow ? RUN_TABS.INPUT : RUN_TABS.TRACING,
    })
    activeTab.value = isChatflow ? RUN_TABS.INPUT : RUN_TABS.TRACING

    const controller = new AbortController()
    runController.value = controller
    const canvasCb = onCanvasEvent || onNodeState
    const onEvent = (event) => handleEvent(event, canvasCb, { syncChat: isChatflow })

    try {
      if (syncDraft)
        await syncDraft()

      await runDraftFn(appId, {
        mode,
        inputs,
        files,
        query,
        conversationId: state.conversationId,
        parentMessageId: state.parentMessageId,
        signal: controller.signal,
        onEvent,
      })

      // Contrasts Dify onWorkflowPaused → GET /workflow/{id}/events (stay open until resume finishes).
      if (state.runStatus === RUN_STATUS.paused && state.workflowRunId && !controller.signal.aborted) {
        await subscribeWorkflowEventsFn(state.workflowRunId, {
          signal: controller.signal,
          onEvent,
        })
      }

      // Stream closed without workflow_finished / error — do not fake success.
      if (state.runStatus === RUN_STATUS.running) {
        patchState({
          isRunning: false,
          runStatus: RUN_STATUS.failed,
          runError: state.runError || '运行结束但未收到结果事件，请重试',
          preferredTab: isChatflow ? RUN_TABS.INPUT : RUN_TABS.RESULT,
        })
        canvasCb?.({ type: 'workflow_finished', status: RUN_STATUS.failed })
        if (!isChatflow)
          activeTab.value = RUN_TABS.RESULT
      }
      if (isChatflow)
        syncAssistantBubble()
      if (isChatflow && state.runStatus === RUN_STATUS.succeeded)
        await loadAfterAnswerSuggestions(appId, features)
    }
    catch (error) {
      clearAfterAnswerSuggestions()
      if (error?.name === 'AbortError') {
        if (state.runStatus !== RUN_STATUS.paused) {
          patchState({
            isRunning: false,
            runStatus: RUN_STATUS.stopped,
          })
        }
        if (isChatflow)
          syncAssistantBubble()
        return
      }
      patchState({
        isRunning: false,
        runStatus: RUN_STATUS.failed,
        runError: error?.response?.data?.message || error?.message || '工作流运行失败',
        preferredTab: isChatflow ? RUN_TABS.INPUT : RUN_TABS.RESULT,
      })
      if (!isChatflow)
        activeTab.value = RUN_TABS.RESULT
      if (isChatflow)
        syncAssistantBubble()
      throw error
    }
    finally {
      runController.value = null
      if (state.isRunning && state.runStatus !== RUN_STATUS.paused)
        patchState({ isRunning: false })
      if (isChatflow)
        syncAssistantBubble()
    }
  }

  async function submitHumanInput(formToken, data) {
    await submitHumanInputFormFn(formToken, data)
  }

  async function stopRun(appId) {
    const id = state.taskId
    if (id) {
      try {
        await stopRunFn(appId, id)
      }
      catch {
        // Still abort the local stream even if stop API fails.
      }
    }
    runController.value?.abort()
    patchState({
      isRunning: false,
      runStatus: RUN_STATUS.stopped,
    })
    clearAfterAnswerSuggestions()
    syncAssistantBubble()
  }

  function abortLocal() {
    runController.value?.abort()
    patchState({
      isRunning: false,
      runStatus: state.runStatus === RUN_STATUS.running || state.runStatus === RUN_STATUS.paused
        ? RUN_STATUS.stopped
        : state.runStatus,
    })
    clearAfterAnswerSuggestions()
  }

  return {
    state,
    activeTab,
    chatList,
    afterAnswerSuggestions,
    canStop,
    setActiveTab,
    startRun,
    stopRun,
    submitHumanInput,
    clearConversation,
    resetForNewRun,
    abortLocal,
    handleEvent,
  }
}
