import {
  applyAssistStreamEvent,
  failAssistActivity,
  finalizeAssistStreamMessages,
  normalizeAssistStreamEvent,
} from './assistStreamMessage.js'
import { detectRecoveredAssistLanguage } from './assistLanguage.js'

const TERMINAL_EVENTS = new Set(['waiting_user', 'done', 'failed', 'error', 'aborted', 'turn_complete'])

function eventCoordinate(event) {
  const runId = String(event?.run_id || '')
  const sequence = Number(event?.sequence)
  if (!runId || !Number.isInteger(sequence) || sequence < 0)
    return null
  return { runId, sequence }
}

function hasSequence(tracker, sequence) {
  return sequence <= tracker.through
    || tracker.pending.some(([start, end]) => sequence >= start && sequence <= end)
}

function addPendingRange(ranges, sequence, lastSequence = sequence) {
  const pending = []
  let start = sequence
  let end = lastSequence
  let inserted = false
  for (const range of ranges) {
    if (range[1] + 1 < start) {
      pending.push(range)
      continue
    }
    if (end + 1 < range[0]) {
      if (!inserted) {
        pending.push([start, end])
        inserted = true
      }
      pending.push(range)
      continue
    }
    start = Math.min(start, range[0])
    end = Math.max(end, range[1])
  }
  if (!inserted)
    pending.push([start, end])
  return pending
}

function addSequence(tracker, sequence, firstSequence = sequence) {
  const pending = addPendingRange(tracker.pending, firstSequence, sequence)
  let through = tracker.through
  let consumed = 0
  while (pending[consumed]?.[0] <= through + 1) {
    through = Math.max(through, pending[consumed][1])
    consumed += 1
  }
  return { through, pending: pending.slice(consumed) }
}

function normalizedQuestions(questions) {
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

function waitingUserMessage(event) {
  const payload = normalizeAssistStreamEvent(event)
  return {
    role: 'assistant',
    kind: 'clarification',
    clarification: {
      clarification_id: payload.tool_call_id || '',
      questions: normalizedQuestions(payload.questions),
    },
    status: 'pending',
    statusText: '',
    resolved: false,
  }
}

export function createWorkflowAssistRunState(messages = [], language = 'zh-Hans') {
  return {
    messages: Array.isArray(messages) ? messages : [],
    eventSequencesByRun: {},
    cursorsByRun: {},
    terminalRuns: new Set(),
    candidateRevision: 0,
    language,
  }
}

export function workflowAssistRunCursor(state, runId) {
  return state?.cursorsByRun?.[String(runId || '')] || null
}

export function reduceWorkflowAssistRunEvent(state, event, selectedLanguage = '', options = {}) {
  const current = state || createWorkflowAssistRunState()
  const coordinate = eventCoordinate(event)
  if (!coordinate)
    return current
  const mode = options.mode === 'hydrate' ? 'hydrate' : 'live'

  const { runId, sequence } = coordinate
  const previousTracker = current.eventSequencesByRun[runId] || { through: -1, pending: [] }
  if (hasSequence(previousTracker, sequence))
    return current
  // Only history projections may cover a contiguous range of durable deltas.
  const projectedStart = event.data?.sequence_start
  const firstSequence = mode === 'hydrate'
    && ['message.delta', 'reasoning.delta'].includes(event.event)
    && Number.isInteger(projectedStart) && projectedStart > 0 && projectedStart <= sequence
    ? projectedStart : sequence
  const eventSequencesByRun = {
    ...current.eventSequencesByRun,
    [runId]: addSequence(previousTracker, sequence, firstSequence),
  }
  const epoch = Number(event.epoch)
  const previousCursor = workflowAssistRunCursor(current, runId)
  const cursorsByRun = {
    ...current.cursorsByRun,
    [runId]: {
      epoch: Number.isInteger(epoch) && epoch >= 0 ? epoch : previousCursor?.epoch ?? null,
      sequence: Math.max(previousCursor?.sequence ?? 0, sequence),
    },
  }
  let terminalRuns = current.terminalRuns
  if (TERMINAL_EVENTS.has(event.event) && !terminalRuns.has(runId)) {
    terminalRuns = new Set(terminalRuns)
    terminalRuns.add(runId)
  }

  const payload = normalizeAssistStreamEvent(event)
  const language = event.event === 'user.message' && String(payload.text || '').trim()
    ? detectRecoveredAssistLanguage([...current.messages, { role: 'user', text: payload.text }])
    : selectedLanguage || current.language || 'zh-Hans'
  let messages = current.messages
  if (event.event === 'user.message') {
    messages = [
      ...finalizeAssistStreamMessages(messages).map(message => (
        message.kind === 'clarification' && !message.resolved
          ? { ...message, status: 'resolved', resolved: true }
          : message
      )),
      { role: 'user', text: String(payload.text || ''), run_id: runId, epoch, sequence, ...(Array.isArray(payload.references) && payload.references.length ? { references: payload.references } : {}) },
    ]
  }
  else if (event.event === 'candidate.updated') {
    messages = current.messages
  }
  else if (event.event === 'waiting_user') {
    messages = [...finalizeAssistStreamMessages(messages), waitingUserMessage(event)]
  }
  else if (event.event === 'failed' || event.event === 'error' || event.event === 'aborted') {
    messages = failAssistActivity(messages)
  }
  else if (event.event === 'turn_complete') {
    messages = finalizeAssistStreamMessages(messages)
  }
  else {
    messages = applyAssistStreamEvent(messages, event, language, { mode })
  }

  const revision = event.event === 'candidate.updated' ? Number(payload.revision) : 0
  return {
    messages,
    eventSequencesByRun,
    cursorsByRun,
    terminalRuns,
    candidateRevision: Number.isInteger(revision)
      ? Math.max(current.candidateRevision, revision)
      : current.candidateRevision,
    language,
  }
}

export function reduceWorkflowAssistTimeline(state, events, options = {}) {
  return (Array.isArray(events) ? events : [])
    .reduce((current, event) => reduceWorkflowAssistRunEvent(current, event, '', options), state)
}

export function hydrateWorkflowAssistTimeline(state, events) {
  return reduceWorkflowAssistTimeline(state, events, { mode: 'hydrate' })
}

export function settleHydratedAssistRunState(state, { keepLiveTail = false } = {}) {
  const current = state || createWorkflowAssistRunState()
  if (keepLiveTail) {
    const messages = Array.isArray(current.messages) ? [...current.messages] : []
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index]
      if (message?.kind === 'assistant_text') {
        messages[index] = { ...message, streaming: true }
        break
      }
      if (message?.kind === 'activity' && message.status === 'running') {
        messages[index] = { ...message, streaming: true, collapsed: false }
        break
      }
      if (message?.role === 'user')
        break
    }
    return { ...current, messages }
  }
  return {
    ...current,
    messages: finalizeAssistStreamMessages(current.messages),
  }
}
