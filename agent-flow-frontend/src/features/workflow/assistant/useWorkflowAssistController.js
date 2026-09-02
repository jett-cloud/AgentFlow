import {
  assistErrorAction,
  assistErrorsFromAxios,
} from './assistErrors.js'
import {
  appendAssistStatusMessage,
  applyAssistStreamEvent,
  beginAssistActivity,
  failAssistActivity,
  finalizeAssistStreamMessages,
  normalizeAssistStreamEvent,
} from './assistStreamMessage.js'
import { abortStatusText } from './assistStateMachine.js'
import { clarificationAnswerText } from './assistClarification.js'
import {
  createWorkflowAssistRunState,
  reduceWorkflowAssistRunEvent,
  reduceWorkflowAssistTimeline,
  workflowAssistRunCursor,
} from './workflowAssistRunReducer.js'

function clarificationIdOf(message) {
  return message?.clarification?.clarification_id || ''
}

function normalizeQuestions(questions) {
  if (!Array.isArray(questions))
    return []
  return questions.map((question, index) => {
    if (typeof question === 'string')
      return { id: `q${index}`, question, kind: 'text' }
    return {
      ...question,
      id: question?.id || `q${index}`,
      question: question?.question || question?.prompt || question?.text || '',
      kind: question?.kind || 'text',
    }
  })
}

function setClarificationStatus(messages, clarificationId, status, statusText = '') {
  return messages.map((message) => {
    if (message?.kind !== 'clarification' || clarificationIdOf(message) !== clarificationId)
      return message
    return {
      ...message,
      status,
      statusText,
      resolved: status !== 'pending' && status !== 'submitting',
    }
  })
}

function upsertClarification(messages, clarification) {
  const clarificationId = clarification?.clarification_id
  const index = messages.findIndex(message => (
    message?.kind === 'clarification' && clarificationIdOf(message) === clarificationId
  ))
  const nextMessage = {
    role: 'assistant',
    kind: 'clarification',
    clarification: {
      ...clarification,
      questions: normalizeQuestions(clarification?.questions),
    },
    status: 'pending',
    statusText: '',
    resolved: false,
  }
  if (index < 0)
    return [...messages, nextMessage]
  const next = [...messages]
  next[index] = nextMessage
  return next
}

function isAbortError(error) {
  return error?.name === 'AbortError' || error?.code === 'ERR_CANCELED'
}

function isReconnectableStreamError(error) {
  return !isAbortError(error)
    && !Number.isInteger(error?.status)
    && error?.name !== 'FetchSseParseError'
    && (error instanceof TypeError || error?.name === 'NetworkError')
}

function readRef(value) {
  if (value && typeof value === 'object' && 'value' in value)
    return value.value
  return value
}

function normalizePreparationResult(result) {
  if (result && typeof result === 'object') {
    return {
      accepted: result.accepted !== false,
      conversationId: String(result.conversationId || ''),
    }
  }
  return { accepted: result !== false, conversationId: '' }
}

const TERMINAL_EVENTS = new Set(['waiting_user', 'done', 'failed', 'aborted', 'error', 'turn_complete'])
const TERMINAL_RUN_STATUSES = new Set(['waiting_user', 'done', 'failed', 'aborted', 'error', 'turn_complete'])
const DISPATCHED_EVENTS = new Set(['tool_result', 'waiting_user', 'done', 'failed', 'aborted', 'error', 'turn_complete'])
const RUN_STATUS_EVENTS = new Set(['queued', 'running', 'waiting_user', 'done', 'failed', 'error', 'aborted', 'turn_complete'])
const ACTIVE_RUN_STATUSES = new Set(['queued', 'running'])

function runStatusFromEvent(event, normalized) {
  if (RUN_STATUS_EVENTS.has(event?.event))
    return event.event
  if (event?.event === 'status')
    return ACTIVE_RUN_STATUSES.has(normalized?.status) ? normalized.status : null
  return 'running'
}
const RECONNECT_BASE_DELAY_MS = 250
const RECONNECT_MAX_DELAY_MS = 4000
const MAX_STALE_CANDIDATE_FOLLOW_UPS = 1

function waitForAbortableDelay(delay, signal) {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve(false)
      return
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve(true)
    }, delay)
    function onAbort() {
      clearTimeout(timer)
      resolve(false)
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

function reconnectDelay(attempt) {
  return Math.min(RECONNECT_BASE_DELAY_MS * (2 ** attempt), RECONNECT_MAX_DELAY_MS)
}

export function useWorkflowAssistController({
  state,
  messages,
  lastInstruction,
  conversationId,
  language = 'zh-Hans',
  hasSelectedModel,
  onModelRequired = () => {},
  syncDraftIfDirty = () => {},
  prepareInstruction = async () => true,
  buildPayload,
  submitTurn = null,
  streamRunEvents = null,
  abortChat = async () => {},
  retryRun = null,
  dispatch,
  onErrors = () => {},
  onPersist = () => {},
  onRunSubmitted = () => {},
  onRunStatus = () => {},
  onRunCursor = () => {},
  onRunTerminal = () => {},
  reconcileConversation = async () => {},
  selectConversation: selectConversationImpl = async () => {},
  newConversation: newConversationImpl = async () => {},
  loadConversations = null,
  loadTimeline = null,
  loadCandidate = null,
  loadRunSummaries = null,
  getRunCoordinates = () => null,
  reconcileRunCoordinates = () => null,
  onCandidate = () => {},
  onRunState = () => {},
  onTimelineRecovered = () => {},
  setTimeoutImpl = globalThis.setTimeout?.bind(globalThis),
  clearTimeoutImpl = globalThis.clearTimeout?.bind(globalThis),
  waitForReconnect = waitForAbortableDelay,
}) {
  let requestSequence = 0
  let turnAttemptSequence = 0
  let conversationSequence = 0
  let activeAbortController = null
  let lastTurn = null
  let runState = createWorkflowAssistRunState(messages.value, readRef(language) || 'zh-Hans')
  let lastReportedRunKey = ''
  let lastReportedRunStatus = ''
  let candidateTimer = null
  let candidateInFlight = false
  let candidateInFlightPromise = null
  let candidateFollowUp = false
  let candidateForceFollowUp = false
  let requestedCandidateRevision = 0
  let acceptedCandidateRevision = 0
  let acceptedCandidate = null
  let acceptedCandidateVersion = 0
  let candidateContext = null
  let staleCandidateBudget = null

  function isCurrentRequest(requestId) {
    return requestId === requestSequence
  }

  function currentConversationId() {
    return String(readRef(conversationId) || '')
  }

  function currentLanguage() {
    return String(readRef(language) || 'zh-Hans')
  }

  function reportRunStatus(status, coordinates = {}) {
    if (!status)
      return false
    const runId = String(coordinates.run_id || '')
    const epoch = Number(coordinates.epoch)
    const runKey = runId && Number.isInteger(epoch)
      ? `${runId}:${epoch}`
      : `${currentConversationId()}:${coordinates.source || 'unknown'}`
    if (lastReportedRunKey === runKey && lastReportedRunStatus === status)
      return false
    lastReportedRunKey = runKey
    lastReportedRunStatus = status
    onRunStatus(status, coordinates)
    return true
  }

  function clearCandidateTimer() {
    if (candidateTimer !== null && clearTimeoutImpl)
      clearTimeoutImpl(candidateTimer)
    candidateTimer = null
  }

  function tearStream() {
    turnAttemptSequence += 1
    requestSequence += 1
    activeAbortController?.abort()
    activeAbortController = null
    clearCandidateTimer()
    requestedCandidateRevision = 0
    acceptedCandidateRevision = 0
    acceptedCandidate = null
    acceptedCandidateVersion = 0
    candidateFollowUp = false
    candidateForceFollowUp = false
    candidateContext = null
    staleCandidateBudget = null
  }

  function persistStatus(text) {
    messages.value = appendAssistStatusMessage(messages.value, text)
  }

  function detachActiveTurn() {
    tearStream()
  }

  function cancelActiveTurn() {
    detachActiveTurn()
  }

  function isCurrentRunEvent(requestId, expectedRun, event) {
    if (!isCurrentRequest(requestId))
      return false
    if (!expectedRun || !event?.run_id)
      return true
    return String(event.run_id) === String(expectedRun.run_id)
      && Number(event.epoch) === Number(expectedRun.epoch)
  }

  function syncRunMessages() {
    if (runState.messages !== messages.value)
      runState = { ...runState, messages: messages.value }
  }

  function acceptCandidate(candidate, context, minimumRevision = 0) {
    if (!candidate || !isCurrentRequest(context.requestId))
      return false
    if (currentConversationId() !== context.conversationId)
      return false
    const revision = Number(candidate.revision)
    if (!Number.isInteger(revision) || revision < minimumRevision || revision < acceptedCandidateRevision)
      return false
    acceptedCandidateRevision = revision
    acceptedCandidate = candidate
    acceptedCandidateVersion += 1
    onCandidate(candidate)
    return true
  }

  function candidateBudgetToken(context, requiredRevision) {
    return JSON.stringify([
      context?.requestId ?? null,
      context?.conversationId || '',
      context?.runId || '',
      requiredRevision,
    ])
  }

  function candidateBudgetFor(context, requiredRevision) {
    const token = candidateBudgetToken(context, requiredRevision)
    if (staleCandidateBudget?.token !== token)
      staleCandidateBudget = { token, followUps: 0, reported: false }
    return staleCandidateBudget
  }

  function sameCandidateContext(left, right) {
    return left?.requestId === right?.requestId
      && left?.conversationId === right?.conversationId
      && left?.runId === right?.runId
  }

  function reportStaleCandidate(requiredRevision, context = candidateContext) {
    const budget = candidateBudgetFor(context, requiredRevision)
    if (budget.reported)
      return
    budget.reported = true
    onErrors([{
      code: 'candidate_revision_lag',
      detail: `Candidate snapshot has not reached required revision ${requiredRevision}.`,
    }])
  }

  async function performCandidateRefresh(context, requestedRevision) {
    let returnedRevision = null
    let responseCoversDesiredRevision = false
    let receivedResponse = false
    try {
      const candidate = await loadCandidate(context.conversationId, requestedRevision)
      receivedResponse = true
      returnedRevision = Number(candidate?.revision)
      const desiredRevision = requestedCandidateRevision
      if (Number.isInteger(returnedRevision) && returnedRevision >= desiredRevision) {
        responseCoversDesiredRevision = acceptCandidate(candidate, context, desiredRevision)
        if (responseCoversDesiredRevision) {
          candidateFollowUp = false
          clearCandidateTimer()
          staleCandidateBudget = null
        }
      }
    }
    catch (error) {
      if (!isAbortError(error) && isCurrentRequest(context.requestId))
        onErrors(assistErrorsFromAxios(error, currentLanguage()))
    }
    finally {
      candidateInFlight = false
      candidateInFlightPromise = null
      const followUpContext = candidateContext
      const responseIsBehind = receivedResponse && (
        !Number.isInteger(returnedRevision) || returnedRevision < requestedCandidateRevision
      )
      const handoffToNewContext = followUpContext && !sameCandidateContext(context, followUpContext)
      const budget = responseIsBehind && followUpContext
        ? candidateBudgetFor(followUpContext, requestedCandidateRevision)
        : null
      const followUpRequested = candidateFollowUp || candidateForceFollowUp || responseIsBehind
      if (followUpContext && isCurrentRequest(followUpContext.requestId)
        && !responseCoversDesiredRevision
        && followUpRequested
        && (!responseIsBehind || handoffToNewContext
          || budget.followUps < MAX_STALE_CANDIDATE_FOLLOW_UPS)) {
        if (responseIsBehind && !handoffToNewContext)
          budget.followUps += 1
        candidateFollowUp = false
        candidateForceFollowUp = false
        clearCandidateTimer()
        void startCandidateRefresh(followUpContext)
      }
      else if (followUpContext && isCurrentRequest(followUpContext.requestId) && responseIsBehind) {
        candidateFollowUp = false
        candidateForceFollowUp = false
        reportStaleCandidate(requestedCandidateRevision, followUpContext)
      }
    }
  }

  function startCandidateRefresh(context) {
    if (!loadCandidate || !isCurrentRequest(context.requestId))
      return Promise.resolve()
    if (candidateInFlight) {
      candidateFollowUp = true
      return Promise.resolve()
    }
    candidateInFlight = true
    candidateFollowUp = false
    const requestedRevision = requestedCandidateRevision
    candidateInFlightPromise = performCandidateRefresh(context, requestedRevision)
    return candidateInFlightPromise
  }

  function flushCandidateRefresh(context) {
    candidateTimer = null
    return startCandidateRefresh(context)
  }

  async function drainCandidateRefresh(context, forceFollowUp = false) {
    candidateContext = context
    if (forceFollowUp)
      staleCandidateBudget = null
    candidateForceFollowUp = candidateForceFollowUp || forceFollowUp
    while (isCurrentRequest(context.requestId)) {
      if (candidateInFlightPromise) {
        await candidateInFlightPromise
        continue
      }
      if (candidateFollowUp || candidateForceFollowUp) {
        candidateFollowUp = false
        candidateForceFollowUp = false
        await startCandidateRefresh(context)
        continue
      }
      return
    }
  }

  function scheduleCandidateRefresh(revision, requestId, expectedRun) {
    if (!loadCandidate || !setTimeoutImpl)
      return
    const numericRevision = Number(revision)
    if (!Number.isInteger(numericRevision) || numericRevision < 0)
      return
    if (numericRevision > requestedCandidateRevision) {
      requestedCandidateRevision = numericRevision
    }
    candidateContext = {
      requestId,
      conversationId: currentConversationId(),
      runId: String(expectedRun?.run_id || ''),
    }
    clearCandidateTimer()
    const context = candidateContext
    candidateTimer = setTimeoutImpl(() => flushCandidateRefresh(context), 250)
  }

  function consumeRunEvent(event, requestId, expectedRun) {
    if (!isCurrentRunEvent(requestId, expectedRun, event))
      return false
    const normalized = normalizeAssistStreamEvent(event)
    let authoritativeSequence = null
    if (event?.run_id && Number.isInteger(Number(event?.sequence))) {
      syncRunMessages()
      const next = reduceWorkflowAssistRunEvent(runState, event, currentLanguage())
      if (next === runState)
        return TERMINAL_EVENTS.has(event.event)
      runState = next
      messages.value = runState.messages
      onRunState(runState)
      authoritativeSequence = workflowAssistRunCursor(runState, event.run_id)?.sequence ?? null
    }
    else {
      messages.value = applyAssistStreamEvent(messages.value, normalized, currentLanguage())
      if (event?.event === 'waiting_user') {
        messages.value = finalizeAssistStreamMessages(messages.value)
        messages.value = upsertClarification(messages.value, {
          clarification_id: normalized.tool_call_id,
          questions: normalized.questions || [],
        })
      }
    }
    reportRunStatus(
      runStatusFromEvent(event, normalized),
      {
        source: 'event',
        run_id: expectedRun?.run_id,
        epoch: expectedRun?.epoch,
        sequence: event?.sequence,
      },
    )
    if (DISPATCHED_EVENTS.has(event?.event))
      dispatch({ type: 'SSE', ...normalized })
    if (event?.event === 'failed' || event?.event === 'aborted' || event?.event === 'error') {
      messages.value = failAssistActivity(messages.value)
      const streamErrors = Array.isArray(normalized.errors) ? normalized.errors : []
      if (event?.event === 'error' && streamErrors.length)
        onErrors(streamErrors)
      const statusText = state.value.statusMessage || normalized.reason || normalized.message || ''
      const errorDetail = String(streamErrors[0]?.detail || '')
      if (statusText && statusText !== errorDetail)
        persistStatus(statusText)
    }
    if (typeof event?.sequence === 'number')
      onRunCursor(authoritativeSequence ?? event.sequence)
    if (event?.event === 'candidate.updated')
      scheduleCandidateRefresh(normalized.revision, requestId, expectedRun)
    if (TERMINAL_EVENTS.has(event?.event)) {
      onRunTerminal()
      return true
    }
    return false
  }

  async function refreshTerminalFacts(requestId, expectedRun) {
    const id = currentConversationId()
    if (!id || !isCurrentRequest(requestId))
      return null
    let runs = null
    const context = { requestId, conversationId: id, runId: expectedRun?.run_id || '' }
    const candidateVersionBeforeRefresh = acceptedCandidateVersion
    if (loadCandidate) {
      clearCandidateTimer()
      await drainCandidateRefresh(context, true)
    }
    if (loadRunSummaries && isCurrentRequest(requestId)) {
      try {
        runs = await loadRunSummaries(id, { after_epoch: 0, limit: 100 })
      }
      catch (error) {
        if (!isAbortError(error) && isCurrentRequest(requestId))
          onErrors(assistErrorsFromAxios(error, currentLanguage()))
      }
    }
    const candidate = acceptedCandidateVersion > candidateVersionBeforeRefresh
      ? acceptedCandidate
      : null
    const runItems = Array.isArray(runs?.items) ? runs.items : []
    const latestFromRuns = [...runItems]
      .sort((left, right) => Number(right?.epoch || 0) - Number(left?.epoch || 0))[0] || null
    const activeFromRuns = runItems.find(run => ['queued', 'running'].includes(run?.status)) || null
    const activeRun = candidate ? candidate.active_run || null : activeFromRuns
    const latestRun = candidate ? candidate.latest_run || null : latestFromRuns
    if (isCurrentRequest(requestId)) {
      reconcileRunCoordinates({
        conversation_id: id,
        active_run: activeRun,
        latest_run: latestRun,
        runs: runItems,
      })
    }
    return { active_run: activeRun, latest_run: latestRun, runs: runItems }
  }

  function settleTerminal204(expectedRun, facts) {
    onRunTerminal()
    const summaries = [facts?.latest_run, ...(facts?.runs || [])].filter(Boolean)
    const summary = summaries.find(run => (
      String(run?.run_id || '') === expectedRun.run_id
      && Number(run?.epoch) === expectedRun.epoch
      && TERMINAL_RUN_STATUSES.has(run?.status)
    ))
    if (!summary || state.value.phase !== 'running')
      return
    const terminalEvent = {
      type: 'SSE',
      event: summary.status,
      termination_reason: summary.termination_reason || null,
      reason: summary.termination_reason || '',
      message: summary.termination_reason || '',
    }
    reportRunStatus(summary.status, {
      source: 'summary',
      run_id: expectedRun.run_id,
      epoch: expectedRun.epoch,
    })
    dispatch(terminalEvent)
    messages.value = summary.status === 'done'
      ? finalizeAssistStreamMessages(messages.value)
      : failAssistActivity(messages.value)
  }

  async function subscribeToRun(submitted, requestId, abortController) {
    if (!submitted?.run_id || !streamRunEvents)
      return { terminal: false, status: null }
    let cursor = Number.isInteger(Number(submitted.cursor)) ? Number(submitted.cursor) : 0
    const expectedRun = { run_id: String(submitted.run_id), epoch: Number(submitted.epoch) }
    let reconnectAttempt = 0
    while (isCurrentRequest(requestId) && !abortController.signal.aborted) {
      let terminal = false
      let madeProgress = false
      let result
      try {
        result = await streamRunEvents({ ...submitted, cursor }, {
          signal: abortController.signal,
          after: cursor,
          lastEventId: cursor,
          onEvent: (event) => {
            if (!isCurrentRunEvent(requestId, expectedRun, event))
              return
            terminal = consumeRunEvent(event, requestId, expectedRun) || terminal
            const reducedCursor = workflowAssistRunCursor(runState, expectedRun.run_id)
            if (reducedCursor) {
              const previousCursor = cursor
              cursor = Math.max(cursor, reducedCursor.sequence)
              madeProgress = madeProgress || cursor > previousCursor
            }
          },
        })
      }
      catch (error) {
        if (terminal) {
          await refreshTerminalFacts(requestId, expectedRun)
          return { terminal: true, status: null }
        }
        if (!isCurrentRequest(requestId) || abortController.signal.aborted || !isReconnectableStreamError(error))
          throw error
        if (madeProgress)
          reconnectAttempt = 0
        const waited = await waitForReconnect(reconnectDelay(reconnectAttempt), abortController.signal)
        reconnectAttempt = Math.min(reconnectAttempt + 1, 4)
        if (waited === false || !isCurrentRequest(requestId) || abortController.signal.aborted)
          break
        continue
      }
      const eventCursor = cursor
      const parsedLastEventId = Number(result?.lastEventId)
      if (Number.isInteger(parsedLastEventId) && parsedLastEventId >= 0)
        cursor = Math.max(cursor, parsedLastEventId)
      if (cursor > eventCursor) {
        onRunCursor(cursor)
        madeProgress = true
      }
      if (terminal || result?.status === 204) {
        const facts = await refreshTerminalFacts(requestId, expectedRun)
        if (!terminal && result?.status === 204)
          settleTerminal204(expectedRun, facts)
        return { terminal: true, status: result?.status ?? null }
      }
      if (madeProgress)
        reconnectAttempt = 0
      const waited = await waitForReconnect(reconnectDelay(reconnectAttempt), abortController.signal)
      reconnectAttempt = Math.min(reconnectAttempt + 1, 4)
      if (waited === false)
        break
    }
    return { terminal: false, status: null }
  }

  async function stopActiveTurn() {
    const wasRunning = state.value.phase === 'running'
    const id = currentConversationId()
    const coordinates = getRunCoordinates()
    if (!wasRunning || !id || !coordinates?.run_id || !Number.isInteger(Number(coordinates.epoch)))
      return false
    try {
      await abortChat({
        conversation_id: id,
        run_id: String(coordinates.run_id),
        epoch: Number(coordinates.epoch),
      })
    }
    catch (error) {
      if (error?.response?.status === 409) {
        const facts = {
          conversation_id: id,
          ...(error.response.data || {}),
        }
        reconcileRunCoordinates(facts)
        const activeRun = facts.active_run
        if (activeRun && ACTIVE_RUN_STATUSES.has(activeRun.status)) {
          tearStream()
          void resumeActiveTurn(activeRun)
          return false
        }
        const latestRun = facts.latest_run
        if (latestRun && TERMINAL_RUN_STATUSES.has(latestRun.status)) {
          tearStream()
          const refreshRequestId = requestSequence
          const refreshed = await refreshTerminalFacts(refreshRequestId, latestRun)
          if (!isCurrentRequest(refreshRequestId))
            return false
          const authoritativeFacts = {
            ...facts,
            active_run: refreshed?.active_run ?? facts.active_run ?? null,
            latest_run: refreshed?.latest_run ?? facts.latest_run ?? null,
            runs: refreshed?.runs?.length ? refreshed.runs : facts.runs || [],
          }
          reconcileRunCoordinates(authoritativeFacts)
          const refreshedActiveRun = authoritativeFacts.active_run
          if (refreshedActiveRun && ACTIVE_RUN_STATUSES.has(refreshedActiveRun.status)) {
            void resumeActiveTurn(refreshedActiveRun)
            return false
          }
          const terminalRun = authoritativeFacts.latest_run
          if (terminalRun && TERMINAL_RUN_STATUSES.has(terminalRun.status)) {
            settleTerminal204({ run_id: String(terminalRun.run_id), epoch: Number(terminalRun.epoch) }, authoritativeFacts)
          }
          onPersist()
        }
        return false
      }
      onErrors(assistErrorsFromAxios(error, currentLanguage()))
      return false
    }
    tearStream()
    messages.value = failAssistActivity(messages.value)
    reportRunStatus('aborted', { source: 'stop', run_id: coordinates.run_id, epoch: coordinates.epoch })
    dispatch({ type: 'SSE', event: 'aborted', termination_reason: 'user_abort' })
    persistStatus(abortStatusText('user_abort', currentLanguage()))
    onPersist()
    return true
  }

  async function handleFailure(errors, isCurrent = () => true) {
    messages.value = failAssistActivity(messages.value)
    reportRunStatus('error', { source: 'client_error' })
    dispatch({
      type: 'SSE',
      event: 'error',
      message: errors[0]?.detail || '',
      errors,
    })
    persistStatus(state.value.statusMessage)
    onErrors(errors)
    onPersist()
    if (assistErrorAction(errors) === 'reload_conversation' && isCurrent())
      await reconcileConversation(isCurrent)
  }

  async function followSubmittedRun(submitted, {
    turn = null,
    pushUserMessage = false,
    wasRunning = false,
    waitingToolCallId = '',
    isCurrentAttempt = () => true,
    originConversationId = '',
    onAccepted = () => {},
  } = {}) {
    if (!isCurrentAttempt())
      return { accepted: false }
    if (submitted?.conversation_id
      && String(submitted.conversation_id) !== originConversationId)
      return { accepted: false }

    const requestId = ++requestSequence
    activeAbortController?.abort()
    clearCandidateTimer()
    const abortController = new AbortController()
    activeAbortController = abortController
    dispatch({ type: 'SEND' })
    if (wasRunning)
      persistStatus(abortStatusText('superseded_by_new_turn', currentLanguage()))
    if (waitingToolCallId)
      messages.value = setClarificationStatus(messages.value, waitingToolCallId, 'resolved')
    if (pushUserMessage && turn) {
      lastInstruction.value = turn.message
      lastTurn = { kind: 'message', message: turn.message }
      messages.value.push({
        role: 'user',
        text: turn.message,
        ...(Array.isArray(turn.references) && turn.references.length ? { references: turn.references } : {}),
      })
    }
    messages.value = beginAssistActivity(messages.value)
    reportRunStatus(submitted.status || 'queued', {
      source: 'submitted',
      run_id: submitted.run_id,
      epoch: submitted.epoch,
    })
    onRunSubmitted(submitted)
    onAccepted(submitted)
    onPersist()

    let terminal = false
    try {
      const result = await subscribeToRun(submitted, requestId, abortController)
      terminal = result.terminal
    }
    catch (error) {
      if (!isCurrentRequest(requestId) || isAbortError(error))
        return { accepted: true, submitted }
      await handleFailure(assistErrorsFromAxios(error, currentLanguage()), () => isCurrentRequest(requestId))
      return { accepted: true, submitted }
    }
    finally {
      if (isCurrentRequest(requestId))
        activeAbortController = null
    }

    if (!isCurrentRequest(requestId))
      return { accepted: true, submitted }
    if (terminal) {
      onPersist()
      return { accepted: true, submitted }
    }
    if (state.value.phase === 'running') {
      reportRunStatus('aborted', { source: 'transport_disconnect' })
      dispatch({ type: 'SSE', event: 'aborted', termination_reason: 'transport_disconnect' })
      messages.value = failAssistActivity(messages.value)
      persistStatus(abortStatusText('transport_disconnect', currentLanguage()))
    }
    onPersist()
    return { accepted: true, submitted }
  }

  async function runTurn(turn, {
    onAccepted = () => {},
    waitingToolCallId = '',
    wasRunning = false,
    isCurrentAttempt = () => true,
    originConversationId = '',
  } = {}) {
    if (!isCurrentAttempt())
      return { accepted: false }
    let submitted
    try {
      const payload = buildPayload(turn)
      if (!submitTurn || !streamRunEvents)
        throw new TypeError('Workflow Assist v2 Turn and Run stream dependencies are required')
      submitted = await submitTurn(payload)
    }
    catch (error) {
      if (isCurrentAttempt())
        onErrors(assistErrorsFromAxios(error, currentLanguage()))
      return { accepted: false }
    }
    return followSubmittedRun(submitted, {
      turn,
      pushUserMessage: true,
      wasRunning,
      waitingToolCallId,
      isCurrentAttempt,
      originConversationId,
      onAccepted,
    })
  }

  async function retryFailedStep() {
    if (!retryRun || !streamRunEvents)
      return { accepted: false }
    const failedStepId = String(state.value.failedStepId || '').trim()
    const id = currentConversationId()
    const coordinates = getRunCoordinates()
    if (!state.value.retryable || !failedStepId || !id || !coordinates?.run_id || !Number.isInteger(Number(coordinates.epoch)))
      return { accepted: false }
    let submitted
    try {
      submitted = await retryRun({
        conversation_id: id,
        run_id: String(coordinates.run_id),
        epoch: Number(coordinates.epoch),
        failed_step_id: failedStepId,
      })
    }
    catch (error) {
      onErrors(assistErrorsFromAxios(error, currentLanguage()))
      return { accepted: false }
    }
    if (!submitted?.run_id)
      return { accepted: false }
    return followSubmittedRun(submitted, {
      pushUserMessage: false,
      originConversationId: id,
    })
  }

  async function submitMessage(message, { onAccepted = () => {}, references } = {}) {
    const text = String(message || '').trim()
    if (!text)
      return { accepted: false }
    if (!hasSelectedModel()) {
      onModelRequired(text)
      return { accepted: false }
    }

    const wasRunning = state.value.phase === 'running'
    const waitingToolCallId = state.value.phase === 'waiting_user'
      ? String(state.value.waitingUser?.tool_call_id || '')
      : ''
    const attemptId = ++turnAttemptSequence
    let expectedConversationId = currentConversationId()
    const isCurrentAttemptGeneration = () => attemptId === turnAttemptSequence
    const isCurrentAttempt = () => (
      isCurrentAttemptGeneration()
      && currentConversationId() === expectedConversationId
    )
    try {
      const syncResult = syncDraftIfDirty()
      if (syncResult && typeof syncResult.then === 'function')
        await syncResult
    }
    catch (error) {
      if (isCurrentAttempt())
        onErrors(assistErrorsFromAxios(error, currentLanguage()))
      return { accepted: false }
    }
    if (!isCurrentAttempt())
      return { accepted: false }
    let preparation
    try {
      preparation = normalizePreparationResult(await prepareInstruction(text, isCurrentAttempt))
      if (!isCurrentAttemptGeneration() || !preparation.accepted)
        return { accepted: false }
    }
    catch (error) {
      if (isCurrentAttempt())
        onErrors(assistErrorsFromAxios(error, currentLanguage()))
      return { accepted: false }
    }
    if (preparation.conversationId) {
      if (expectedConversationId && preparation.conversationId !== expectedConversationId)
        return { accepted: false }
      if (!expectedConversationId) {
        if (currentConversationId() !== preparation.conversationId)
          return { accepted: false }
        expectedConversationId = preparation.conversationId
      }
    }
    if (!isCurrentAttempt())
      return { accepted: false }

    return runTurn({
      message: text,
      ...(Array.isArray(references) && references.length ? { references } : {}),
    }, {
      isCurrentAttempt,
      onAccepted,
      originConversationId: expectedConversationId,
      waitingToolCallId,
      wasRunning,
    })
  }

  async function resumeActiveTurn(submitted) {
    if (!submitted?.run_id || !streamRunEvents)
      return
    const requestId = ++requestSequence
    const abortController = new AbortController()
    activeAbortController = abortController
    if (submitted.status)
      reportRunStatus(submitted.status, { source: 'recovery', run_id: submitted.run_id, epoch: submitted.epoch })
    if (state.value.phase !== 'running')
      dispatch({ type: 'SEND' })
    try {
      const result = await subscribeToRun(submitted, requestId, abortController)
      if (result.terminal)
        onPersist()
    }
    catch (error) {
      if (!isCurrentRequest(requestId) || isAbortError(error))
        return
      await handleFailure(assistErrorsFromAxios(error, currentLanguage()), () => isCurrentRequest(requestId))
      return
    }
    finally {
      if (isCurrentRequest(requestId))
        activeAbortController = null
    }
    if (!isCurrentRequest(requestId))
      return
  }

  async function recoverConversation(selectedId, selectionId = ++conversationSequence) {
    if (!selectedId || !loadTimeline || !loadCandidate)
      return false
    tearStream()
    const requestId = requestSequence
    const abortController = new AbortController()
    activeAbortController = abortController
    const isCurrent = () => isCurrentRequest(requestId) && selectionId === conversationSequence
    try {
      const selectedResult = await selectConversationImpl(selectedId, isCurrent)
      if (!isCurrent() || selectedResult === false)
        return false

      runState = createWorkflowAssistRunState([], currentLanguage())
      let afterEpoch = 0
      let afterSequence = 0
      while (isCurrent()) {
        const page = await loadTimeline(selectedId, {
          after_epoch: afterEpoch,
          after_sequence: afterSequence,
          limit: 500,
        })
        if (!isCurrent())
          return false
        runState = reduceWorkflowAssistTimeline(runState, page?.items || [])
        messages.value = runState.messages
        onRunState(runState)
        if (!page?.has_more)
          break
        const nextEpoch = Number(page?.cursor?.epoch)
        const nextSequence = Number(page?.cursor?.sequence)
        if (!Number.isInteger(nextEpoch) || !Number.isInteger(nextSequence)
          || (nextEpoch === afterEpoch && nextSequence === afterSequence))
          break
        afterEpoch = nextEpoch
        afterSequence = nextSequence
      }
      onTimelineRecovered({
        conversation_id: selectedId,
        messages: messages.value,
        runState,
      })

      acceptedCandidateRevision = 0
      acceptedCandidate = null
      requestedCandidateRevision = runState.candidateRevision
      const candidateLoadContext = {
        requestId,
        conversationId: selectedId,
        runId: '',
      }
      for (let attempt = 0; attempt <= MAX_STALE_CANDIDATE_FOLLOW_UPS
        && isCurrent() && acceptedCandidateRevision < runState.candidateRevision; attempt += 1) {
        const snapshot = await loadCandidate(selectedId, runState.candidateRevision)
        acceptCandidate(snapshot, candidateLoadContext, runState.candidateRevision)
      }
      if (!isCurrent())
        return false
      let candidate = acceptedCandidate
      if (!candidate && runState.candidateRevision > 0) {
        reportStaleCandidate(runState.candidateRevision, candidateLoadContext)
        return false
      }
      if (!candidate) {
        candidate = await loadCandidate(selectedId, 0)
        acceptCandidate(candidate, candidateLoadContext)
      }
      if (!acceptedCandidate) {
        reportStaleCandidate(runState.candidateRevision, candidateLoadContext)
        return false
      }
      candidate = acceptedCandidate
      reconcileRunCoordinates({
        conversation_id: selectedId,
        active_run: candidate?.active_run || null,
        latest_run: candidate?.latest_run || null,
      })

      const activeRun = candidate?.active_run
      if (!activeRun || !['queued', 'running'].includes(activeRun.status))
        return true
      reportRunStatus(activeRun.status, {
        source: 'recovery',
        run_id: activeRun.run_id,
        epoch: activeRun.epoch,
      })
      if (state.value.phase !== 'running')
        dispatch({ type: 'SEND' })
      const reducedCursor = workflowAssistRunCursor(runState, activeRun.run_id)
      const cursor = reducedCursor?.epoch === Number(activeRun.epoch) ? reducedCursor.sequence : 0
      onRunCursor(cursor)
      const result = await subscribeToRun({
        run_id: activeRun.run_id,
        epoch: activeRun.epoch,
        cursor,
      }, requestId, abortController)
      return result.terminal
    }
    catch (error) {
      if (!isCurrentRequest(requestId) || isAbortError(error))
        return false
      await handleFailure(assistErrorsFromAxios(error, currentLanguage()), () => isCurrentRequest(requestId))
      return false
    }
    finally {
      if (isCurrent())
        activeAbortController = null
    }
  }

  async function mountRecoverableSession() {
    if (!loadConversations || !loadTimeline || !loadCandidate)
      return false
    const selectionId = ++conversationSequence
    tearStream()
    const requestId = requestSequence
    try {
      const conversationPage = await loadConversations()
      if (!isCurrentRequest(requestId) || selectionId !== conversationSequence)
        return false
      const conversations = Array.isArray(conversationPage)
        ? conversationPage
        : conversationPage?.items || []
      if (!conversations.length)
        return false
      const localConversationId = String(getRunCoordinates()?.conversation_id || '')
      const selected = conversations.find(item => String(item?.id || '') === localConversationId)
        || conversations[0]
      const selectedId = String(selected?.id || '')
      if (!selectedId)
        return false
      return recoverConversation(selectedId, selectionId)
    }
    catch (error) {
      if (!isCurrentRequest(requestId) || isAbortError(error))
        return false
      await handleFailure(assistErrorsFromAxios(error, currentLanguage()), () => isCurrentRequest(requestId))
      return false
    }
  }

  async function submitInstruction(instruction) {
    return submitMessage(instruction)
  }

  async function submitClarification(clarificationId, answers) {
    const id = String(clarificationId || '')
    const card = messages.value.find(message => (
      message?.kind === 'clarification' && clarificationIdOf(message) === id
    ))
    if (!id || !card || !['pending', undefined].includes(card.status) || card.resolved)
      return
    const questions = card.clarification?.questions || []
    const text = clarificationAnswerText(answers, questions)
    if (!text)
      return { accepted: false }
    messages.value = setClarificationStatus(messages.value, id, 'submitting')
    const result = await submitMessage(text)
    if (!result?.accepted)
      messages.value = setClarificationStatus(messages.value, id, 'pending')
    return result
  }

  async function retryLastTurn() {
    const text = lastTurn?.message || lastInstruction.value
    if (text)
      return submitMessage(text)
  }

  async function selectConversation(id) {
    const selectionId = ++conversationSequence
    if (loadTimeline && loadCandidate) {
      const result = await recoverConversation(String(id || ''), selectionId)
      if (selectionId === conversationSequence && result !== false)
        lastTurn = null
      return result
    }
    cancelActiveTurn()
    const result = await selectConversationImpl(id, () => selectionId === conversationSequence)
    if (selectionId === conversationSequence && result !== false)
      lastTurn = null
    return result
  }

  async function newConversation() {
    cancelActiveTurn()
    const selectionId = ++conversationSequence
    const result = await newConversationImpl(() => selectionId === conversationSequence)
    if (selectionId === conversationSequence && result !== false)
      lastTurn = null
    return result
  }

  return {
    state,
    messages,
    submitInstruction,
    submitMessage,
    submitClarification,
    retryLastTurn,
    retryFailedStep,
    selectConversation,
    newConversation,
    cancelActiveTurn,
    detachActiveTurn,
    mountRecoverableSession,
    resumeActiveTurn,
    stopActiveTurn,
  }
}
