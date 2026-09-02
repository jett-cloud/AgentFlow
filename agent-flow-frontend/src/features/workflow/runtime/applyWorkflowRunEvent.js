/**
 * Workflow debug running-data model + SSE event reduction.
 * Aligns with Dify web use-workflow-finished (resultText from single-string outputs).
 */

import { getFilesInLogs } from './resultFiles.js'
import { extractRetrieverResourcesFromEvent } from './citationUtils.js'
import {
  extractMessageEndFiles,
  mergeChatMessageFiles,
  normalizeMessageFileEvent,
} from './chatMessageFiles.js'
import {
  getStartVariableDefault,
  validateStartVariableInputs,
} from './startVariableUtils.js'

export const RUN_STATUS = {
  idle: 'idle',
  running: 'running',
  succeeded: 'succeeded',
  failed: 'failed',
  stopped: 'stopped',
  paused: 'paused',
}

export const RUN_TABS = {
  INPUT: 'INPUT',
  RESULT: 'RESULT',
  DETAIL: 'DETAIL',
  TRACING: 'TRACING',
}

/** Aligns with Dify DEFAULT_ITER_TIMES for iteration_next index. */
export const DEFAULT_ITER_TIMES = 1

export function createInitialRunningData() {
  return {
    isRunning: false,
    taskId: '',
    conversationId: null,
    parentMessageId: null,
    runStatus: RUN_STATUS.idle,
    runError: '',
    /** Streamed or extracted primary result text (shown in RESULT). */
    resultText: '',
    /** Alias kept for older callers. */
    transcript: '',
    runOutputs: null,
    result: null,
    tracing: [],
    preferredTab: RUN_TABS.INPUT,
    /** Counter used like Dify store.iterTimes for iteration_next. */
    iterTimes: DEFAULT_ITER_TIMES,
    /** Workflow run id for pause resume: GET /workflow/{id}/events */
    workflowRunId: '',
    humanInputFormDataList: [],
    humanInputFilledFormDataList: [],
    /** Chatflow citation from message_end.metadata.retriever_resources */
    citations: [],
    /** Chatflow assistant message_files from message_file / message_end.files */
    messageFiles: [],
  }
}

/** @deprecated use createInitialRunningData */
export function createInitialDebugState() {
  return createInitialRunningData()
}

function eventNameOf(event) {
  return event?.event || event?.type || ''
}

function eventDataOf(event) {
  if (event?.data !== undefined && event.data !== null && typeof event.data === 'object')
    return event.data
  return event || {}
}

function appendText(existing, chunk) {
  if (chunk === undefined || chunk === null || chunk === '')
    return existing || ''
  return `${existing || ''}${chunk}`
}

function extractSingleStringOutput(outputs) {
  if (!outputs || typeof outputs !== 'object' || Array.isArray(outputs))
    return ''
  const keys = Object.keys(outputs)
  if (keys.length !== 1)
    return ''
  const value = outputs[keys[0]]
  return typeof value === 'string' ? value : ''
}

function formatOutputsAsText(outputs) {
  if (outputs === undefined || outputs === null)
    return ''
  if (typeof outputs === 'string')
    return outputs
  try {
    return JSON.stringify(outputs, null, 2)
  }
  catch {
    return String(outputs)
  }
}

function upsertTracing(tracing, entry) {
  const list = Array.isArray(tracing) ? [...tracing] : []
  const index = list.findIndex(item => item.nodeId === entry.nodeId && item.status === 'running')
  if (entry.status === 'running') {
    list.push(entry)
    return list
  }
  if (index >= 0) {
    list[index] = { ...list[index], ...entry }
    return list
  }
  list.push(entry)
  return list
}

/** Normalize SSE node payload into a tracing list entry (Dify NodeTracing subset). */
export function buildTracingEntry(data = {}, overrides = {}) {
  const status = overrides.status
    ?? data.status
    ?? (data.error ? 'failed' : 'running')
  return {
    nodeId: data.node_id,
    title: data.title || data.node_type || data.node_id,
    nodeType: data.node_type,
    status,
    inputs: data.inputs,
    processData: data.process_data,
    outputs: data.outputs,
    error: data.error,
    elapsed_time: data.elapsed_time,
    executionMetadata: data.execution_metadata,
    retryIndex: data.retry_index,
    index: overrides.index,
    ...overrides,
  }
}

export function formatJsonValue(value) {
  if (value === undefined || value === null)
    return '—'
  if (typeof value === 'string')
    return value
  try {
    return JSON.stringify(value, null, 2)
  }
  catch {
    return String(value)
  }
}

export function formatElapsed(value) {
  if (value === undefined || value === null || value === '')
    return ''
  return typeof value === 'number' ? `${value.toFixed(3)}s` : String(value)
}

export function extractTotalTokens(resultOrMeta) {
  if (!resultOrMeta || typeof resultOrMeta !== 'object')
    return null
  if (resultOrMeta.total_tokens != null)
    return resultOrMeta.total_tokens
  if (resultOrMeta.execution_metadata?.total_tokens != null)
    return resultOrMeta.execution_metadata.total_tokens
  return null
}

/**
 * @returns {{ state: object, nodeState: object|null, canvasEvent: object|null }}
 * canvasEvent drives Phase 1 canvas runtime paint (waiting / path / branch / camera).
 */
export function applyWorkflowRunEvent(state, event) {
  const next = { ...state }
  const name = eventNameOf(event)
  const data = eventDataOf(event)
  let nodeState = null
  let canvasEvent = null

  if (event?.conversation_id)
    next.conversationId = event.conversation_id
  else if (data.conversation_id)
    next.conversationId = data.conversation_id

  if (event?.message_id)
    next.parentMessageId = event.message_id
  else if (data.message_id)
    next.parentMessageId = data.message_id

  if (name === 'workflow_started') {
    next.taskId = event.task_id || data.task_id || next.taskId
    next.workflowRunId = data.id || event.workflow_run_id || next.workflowRunId
    next.isRunning = true
    next.runStatus = RUN_STATUS.running
    next.runError = ''
    next.resultText = ''
    next.transcript = ''
    next.runOutputs = null
    next.result = null
    next.tracing = []
    next.preferredTab = RUN_TABS.TRACING
    next.iterTimes = DEFAULT_ITER_TIMES
    next.humanInputFormDataList = []
    next.humanInputFilledFormDataList = []
    canvasEvent = { type: 'workflow_started' }
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'node_started') {
    nodeState = {
      nodeId: data.node_id,
      status: 'running',
      inputs: data.inputs,
    }
    canvasEvent = {
      type: 'node_started',
      ...nodeState,
    }
    next.tracing = upsertTracing(next.tracing, buildTracingEntry(data, {
      status: 'running',
      index: next.tracing.length,
    }))
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'node_finished') {
    const status = data.status || (data.error ? 'failed' : 'succeeded')
    nodeState = {
      nodeId: data.node_id,
      status,
      inputs: data.inputs,
      outputs: data.outputs,
      error: data.error,
    }
    canvasEvent = {
      type: 'node_finished',
      ...nodeState,
      nodeType: data.node_type,
      executionMetadata: data.execution_metadata,
    }
    next.tracing = upsertTracing(next.tracing, buildTracingEntry(data, { status }))
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'iteration_started') {
    next.iterTimes = DEFAULT_ITER_TIMES
    const iterationLength = data.metadata?.iterator_length
    canvasEvent = {
      type: 'iteration_started',
      nodeId: data.node_id,
      iterationLength,
    }
    next.tracing = upsertTracing(next.tracing, buildTracingEntry(data, {
      status: 'running',
      index: next.tracing.length,
    }))
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'iteration_next') {
    const iterationIndex = next.iterTimes ?? DEFAULT_ITER_TIMES
    canvasEvent = {
      type: 'iteration_next',
      nodeId: data.node_id,
      iterationIndex,
    }
    next.iterTimes = iterationIndex + 1
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'iteration_completed') {
    next.iterTimes = DEFAULT_ITER_TIMES
    const status = data.status || (data.error ? 'failed' : 'succeeded')
    canvasEvent = {
      type: 'iteration_completed',
      nodeId: data.node_id,
      status,
    }
    next.tracing = upsertTracing(next.tracing, buildTracingEntry(data, { status }))
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'loop_started') {
    const loopLength = data.metadata?.loop_length
    canvasEvent = {
      type: 'loop_started',
      nodeId: data.node_id,
      loopLength,
    }
    next.tracing = upsertTracing(next.tracing, buildTracingEntry(data, {
      status: 'running',
      index: next.tracing.length,
    }))
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'loop_next') {
    canvasEvent = {
      type: 'loop_next',
      nodeId: data.node_id,
      loopIndex: data.index,
    }
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'loop_completed') {
    const status = data.status || (data.error ? 'failed' : 'succeeded')
    canvasEvent = {
      type: 'loop_completed',
      nodeId: data.node_id,
      status,
    }
    next.tracing = upsertTracing(next.tracing, buildTracingEntry(data, { status }))
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'node_retry') {
    canvasEvent = {
      type: 'node_retry',
      nodeId: data.node_id,
      retryIndex: data.retry_index,
      status: data.status || 'running',
    }
    next.tracing = [
      ...(Array.isArray(next.tracing) ? next.tracing : []),
      buildTracingEntry(data, {
        status: data.status || 'running',
        retryIndex: data.retry_index,
      }),
    ]
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'human_input_required') {
    if (event.workflow_run_id)
      next.workflowRunId = event.workflow_run_id
    const list = Array.isArray(next.humanInputFormDataList)
      ? [...next.humanInputFormDataList]
      : []
    const idx = list.findIndex(item => item.node_id === data.node_id)
    if (idx >= 0)
      list[idx] = data
    else
      list.push(data)
    next.humanInputFormDataList = list
    next.tracing = upsertTracing(next.tracing, buildTracingEntry(data, {
      status: 'paused',
      title: data.title || data.node_title || data.node_type || data.node_id,
    }))
    canvasEvent = {
      type: 'human_input_required',
      nodeId: data.node_id,
    }
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'human_input_form_filled') {
    const list = Array.isArray(next.humanInputFormDataList)
      ? next.humanInputFormDataList.filter(item => item.node_id !== data.node_id)
      : []
    next.humanInputFormDataList = list
    const filled = Array.isArray(next.humanInputFilledFormDataList)
      ? [...next.humanInputFilledFormDataList, data]
      : [data]
    next.humanInputFilledFormDataList = filled
    next.tracing = upsertTracing(next.tracing, buildTracingEntry(data, {
      status: 'succeeded',
      title: data.node_title || data.node_id,
    }))
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'human_input_form_timeout') {
    const list = Array.isArray(next.humanInputFormDataList)
      ? next.humanInputFormDataList.filter(item => item.node_id !== data.node_id)
      : []
    next.humanInputFormDataList = list
    next.tracing = upsertTracing(next.tracing, buildTracingEntry(data, {
      status: 'failed',
      title: data.node_title || data.node_id,
      error: data.error || 'human input timed out',
    }))
    canvasEvent = {
      type: 'human_input_form_timeout',
      nodeId: data.node_id,
    }
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'workflow_paused') {
    next.runStatus = RUN_STATUS.paused
    next.isRunning = true
    next.workflowRunId = event.workflow_run_id || data.workflow_run_id || data.id || next.workflowRunId
    next.preferredTab = RUN_TABS.RESULT
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'text_chunk') {
    const text = data.text ?? data.delta ?? ''
    next.resultText = appendText(next.resultText, text)
    next.transcript = next.resultText
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'text_replace') {
    const text = data.text ?? ''
    next.resultText = text
    next.transcript = text
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'message' || name === 'agent_message') {
    const text = data.answer ?? data.text ?? event.answer ?? ''
    next.resultText = appendText(next.resultText, text)
    next.transcript = next.resultText
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'message_file') {
    // Contrasts Dify onFile → append to responseItem.message_files
    const file = normalizeMessageFileEvent(event)
    if (file)
      next.messageFiles = mergeChatMessageFiles(next.messageFiles, [file])
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'message_end') {
    // Contrasts Dify onMessageEnd → citation + allFiles from files
    next.citations = extractRetrieverResourcesFromEvent(event)
    const endFiles = extractMessageEndFiles(event)
    if (endFiles.length)
      next.messageFiles = mergeChatMessageFiles(next.messageFiles, endFiles)
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'workflow_finished') {
    next.isRunning = false
    const status = data.status
    if (status === 'stopped' || status === 'cancelled')
      next.runStatus = RUN_STATUS.stopped
    else if (status === 'failed' || data.error)
      next.runStatus = RUN_STATUS.failed
    else
      next.runStatus = RUN_STATUS.succeeded

    next.result = {
      ...data,
      files: getFilesInLogs(data.outputs),
    }
    next.runOutputs = data.outputs ?? null
    next.taskId = event.task_id || data.task_id || next.taskId

    if (data.error) {
      next.runError = typeof data.error === 'string'
        ? data.error
        : (data.error.message || String(data.error))
    }

    const single = extractSingleStringOutput(data.outputs)
    if (single) {
      next.resultText = single
      next.transcript = single
      next.preferredTab = RUN_TABS.RESULT
    }
    else if (!next.resultText && data.outputs != null) {
      next.resultText = formatOutputsAsText(data.outputs)
      next.transcript = next.resultText
      next.preferredTab = RUN_TABS.RESULT
    }
    else if (next.resultText) {
      next.preferredTab = RUN_TABS.RESULT
    }
    else if (next.runError) {
      next.preferredTab = RUN_TABS.RESULT
    }
    else if (next.result.files?.length) {
      next.preferredTab = RUN_TABS.RESULT
    }
    else {
      next.preferredTab = RUN_TABS.DETAIL
    }

    canvasEvent = {
      type: 'workflow_finished',
      status: next.runStatus,
    }
    return { state: next, nodeState, canvasEvent }
  }

  if (name === 'error') {
    next.isRunning = false
    next.runStatus = RUN_STATUS.failed
    next.runError = event.message || data.message || data.error || '工作流运行失败'
    next.preferredTab = RUN_TABS.RESULT
    canvasEvent = {
      type: 'workflow_finished',
      status: RUN_STATUS.failed,
    }
    return { state: next, nodeState, canvasEvent }
  }

  return { state: next, nodeState, canvasEvent }
}

/** @deprecated use applyWorkflowRunEvent */
export function applyDebugRunEvent(state, event) {
  return applyWorkflowRunEvent(state, event)
}

export function buildStartVariableDefaults(variables = []) {
  const inputs = {}
  for (const variable of variables) {
    const name = variable?.variable
    if (!name)
      continue
    inputs[name] = getStartVariableDefault(variable)
  }
  return inputs
}

export function validateRequiredStartInputs(variables = [], inputs = {}) {
  return validateStartVariableInputs(variables, inputs)
}
