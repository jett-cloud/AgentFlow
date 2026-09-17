import { assistCopy } from './assistLanguage.js'

export const AssistPhase = {
  idle: 'idle',
  running: 'running',
  waiting_user: 'waiting_user',
}

const UI_PHASES = new Set(Object.values(AssistPhase))

export function normalizeAssistPhase(phase) {
  return UI_PHASES.has(phase) ? phase : AssistPhase.idle
}

export function createAssistSession() {
  return {
    phase: AssistPhase.idle,
    mode: 'rebuild',
    targetNodeIds: [],
    candidateGraph: null,
    diff: null,
    validation: null,
    applyEnabled: false,
    composerSendable: true,
    terminationReason: null,
    waitingUser: null,
    statusMessage: '',
    errors: [],
    warnings: [],
    retryable: false,
    failedStepId: '',
    clarification: null,
    plan: null,
    mutableNodeIds: [],
    intentFlags: {},
    approvedToolKeys: [],
    approvedDatasetIds: [],
  }
}

function uniqueNodeIds(nodeIds) {
  return [...new Set(
    (nodeIds || []).map(nodeId => String(nodeId || '').trim()).filter(Boolean),
  )]
}

function withComposer(session) {
  return {
    ...session,
    composerSendable: true,
  }
}

function clearApply(session) {
  return {
    ...session,
    applyEnabled: false,
  }
}

function endRun(session, overrides) {
  return withComposer({
    ...session,
    phase: AssistPhase.idle,
    applyEnabled: false,
    waitingUser: null,
    ...overrides,
  })
}

export function abortStatusText(reason, language = 'zh-Hans') {
  return assistCopy(language).abortStatuses[reason] || ''
}

export function approvedToolsFromSession(session) {
  return session.approvedToolKeys.map((key) => {
    const index = key.indexOf('/')
    return {
      provider_name: key.slice(0, index),
      tool_name: key.slice(index + 1),
    }
  })
}

export function approvedDatasetsFromSession(session, plan) {
  const requests = plan?.resource_requests || []
  return session.approvedDatasetIds.map((id) => {
    const request = requests.find(item => item?.kind === 'dataset' && item.dataset_id === id)
    return { id, name: request?.dataset_name || '' }
  })
}

function reduceSse(session, event, language) {
  switch (event.event) {
    case 'tool_result':
      return withComposer({
        ...clearApply(session),
        candidateGraph: event.graph ?? session.candidateGraph,
      })

    case 'waiting_user':
      return withComposer({
        ...clearApply(session),
        phase: AssistPhase.waiting_user,
        waitingUser: {
          tool_call_id: event.tool_call_id,
          questions: event.questions || [],
        },
        terminationReason: null,
        statusMessage: '',
        errors: [],
        retryable: false,
        failedStepId: '',
      })

    case 'done': {
      const valid = event.validation?.ok === true
      return withComposer({
        ...session,
        phase: AssistPhase.idle,
        candidateGraph: event.graph ?? session.candidateGraph,
        diff: event.diff ?? session.diff,
        validation: event.validation ?? null,
        applyEnabled: valid,
        waitingUser: null,
        terminationReason: null,
        statusMessage: '',
        errors: valid ? [] : [...(event.validation?.errors || [])],
        retryable: false,
        failedStepId: '',
      })
    }

    case 'failed':
      return endRun(session, {
        terminationReason: null,
        statusMessage: String(event.reason || ''),
        errors: event.reason ? [{ detail: event.reason }] : [],
        retryable: event.retryable !== false,
        failedStepId: String(event.step_id || ''),
      })

    case 'aborted':
      return endRun(session, {
        terminationReason: event.termination_reason || null,
        statusMessage: abortStatusText(event.termination_reason, language),
        errors: [],
        retryable: false,
        failedStepId: '',
      })

    case 'turn_complete':
      return endRun(session, {
        terminationReason: null,
        statusMessage: '',
        errors: [],
        retryable: false,
        failedStepId: '',
      })

    case 'error':
      return endRun(session, {
        terminationReason: event.termination_reason || null,
        statusMessage: String(event.message || ''),
        errors: event.errors || (event.message ? [{ detail: event.message }] : []),
        retryable: event.retryable !== false && event.termination_reason !== 'user_abort',
        failedStepId: String(event.step_id || ''),
      })

    default:
      return withComposer(session)
  }
}

export function reduceAssist(session, event, language = 'zh-Hans') {
  switch (event.type) {
    case 'SET_MODE':
      return withComposer({
        ...session,
        mode: event.mode,
      })

    case 'SET_TARGET_NODES': {
      const targetNodeIds = uniqueNodeIds(event.nodeIds)
      return withComposer({
        ...session,
        mode: targetNodeIds.length ? 'local' : 'rebuild',
        targetNodeIds,
      })
    }

    case 'CLEAR_TARGET_NODES':
      return withComposer({
        ...session,
        mode: 'rebuild',
        targetNodeIds: [],
      })

    case 'SEND': {
      const superseded = session.phase === AssistPhase.running
      return withComposer({
        ...clearApply(session),
        phase: AssistPhase.running,
        waitingUser: null,
        terminationReason: superseded ? 'superseded_by_new_turn' : null,
        statusMessage: superseded ? abortStatusText('superseded_by_new_turn', language) : '',
        errors: [],
        retryable: false,
        failedStepId: '',
      })
    }

    case 'SSE':
      return reduceSse(session, event, language)

    case 'APPLY_OK':
      return withComposer({
        ...session,
        phase: AssistPhase.idle,
        applyEnabled: false,
        errors: [],
      })

    case 'APPLY_FAIL':
      return withComposer({
        ...session,
        errors: [...(event.errors || [])],
      })

    case 'DISCARD':
      return withComposer({
        ...session,
        phase: AssistPhase.idle,
        candidateGraph: null,
        diff: null,
        validation: null,
        applyEnabled: false,
        errors: [],
        warnings: [],
        statusMessage: '',
      })

    case 'RESET':
      return withComposer({
        ...createAssistSession(),
        mode: session.mode,
        targetNodeIds: [...session.targetNodeIds],
      })

    default:
      return withComposer(session)
  }
}
