import difyClient, { DIFY_API_PREFIX } from '../../../shared/http/difyClient.js'
import { fetchSse } from '../assistant/fetchSse.js'

function workflowAssistPath(appId, suffix) {
  return `/apps/${encodeURIComponent(appId)}/workflow-assist/${suffix}`
}

function conversationPath(appId, conversationId, suffix = '') {
  const base = `conversations/${encodeURIComponent(conversationId)}`
  return workflowAssistPath(appId, suffix ? `${base}/${suffix}` : base)
}

export function getWorkflowAssistConversations(appId, params = {}) {
  return difyClient.get(workflowAssistPath(appId, 'conversations'), { params })
}

export function createWorkflowAssistConversation(appId, body = {}) {
  return difyClient.post(workflowAssistPath(appId, 'conversations'), body)
}

export function getWorkflowAssistConversation(appId, conversationId) {
  return difyClient.get(conversationPath(appId, conversationId))
}

export function deleteWorkflowAssistConversation(appId, conversationId) {
  return difyClient.delete(conversationPath(appId, conversationId))
}

export function workflowAssistConversationTitleBody(input) {
  const raw = typeof input === 'string' ? input : input?.title
  const title = String(raw ?? '').trim().slice(0, 255)
  if (!title)
    throw new TypeError('title must be a non-empty string')
  return { title }
}

export function patchWorkflowAssistConversationTitle(appId, conversationId, title) {
  return difyClient.patch(
    conversationPath(appId, conversationId, 'title'),
    workflowAssistConversationTitleBody(title),
  )
}

export function workflowAssistTurnBody(input) {
  const body = {
    message: input?.message,
    mode: input?.mode,
    model_config: input?.model_config,
  }
  if (input?.selected_node !== undefined)
    body.selected_node = input.selected_node
  if (Array.isArray(input?.references) && input.references.length)
    body.references = input.references
  return body
}

export function postWorkflowAssistTurn(appId, conversationId, input) {
  const body = workflowAssistTurnBody(input)
  if (typeof input.live_acceptance_request_id === 'string')
    body.live_acceptance_request_id = input.live_acceptance_request_id
  return difyClient.post(
    conversationPath(appId, conversationId, 'turns'),
    body,
  )
}

export function getWorkflowAssistRuns(appId, conversationId, params = {}) {
  return difyClient.get(conversationPath(appId, conversationId, 'runs'), { params })
}

export function getWorkflowAssistTimeline(appId, conversationId, params = {}) {
  return difyClient.get(conversationPath(appId, conversationId, 'timeline'), { params })
}

export function getWorkflowAssistCandidate(appId, conversationId) {
  return difyClient.get(conversationPath(appId, conversationId, 'candidate'))
}

export function streamWorkflowAssistRunEvents(appId, conversationId, runId, {
  after = 0,
  lastEventId = null,
  onEvent,
  signal,
  fetchImpl,
} = {}) {
  const suffix = `runs/${encodeURIComponent(runId)}/events?after=${encodeURIComponent(String(after))}`
  const url = `${DIFY_API_PREFIX}${conversationPath(appId, conversationId, suffix)}`
  return fetchSse(url, {
    lastEventId,
    signal,
    fetchImpl,
    onEvent: frame => onEvent?.(frame.data),
  })
}

export function workflowAssistAbortBody(input) {
  if (!Number.isInteger(input?.epoch) || input.epoch < 1)
    throw new TypeError('epoch must be a positive integer')
  return { epoch: input?.epoch }
}

export function postWorkflowAssistRunAbort(appId, conversationId, runId, input) {
  return difyClient.post(
    conversationPath(appId, conversationId, `runs/${encodeURIComponent(runId)}/abort`),
    workflowAssistAbortBody(input),
  )
}

export function workflowAssistRetryBody(input) {
  if (!Number.isInteger(input?.epoch) || input.epoch < 1)
    throw new TypeError('epoch must be a positive integer')
  const failedStepId = String(input?.failed_step_id || '').trim()
  if (!failedStepId)
    throw new TypeError('failed_step_id must be a non-empty string')
  return { epoch: input.epoch, failed_step_id: failedStepId }
}

export function postWorkflowAssistRunRetry(appId, conversationId, runId, input) {
  return difyClient.post(
    conversationPath(appId, conversationId, `runs/${encodeURIComponent(runId)}/retry`),
    workflowAssistRetryBody(input),
  )
}

export function workflowAssistApplyBody(conversationIdOrInput, hash) {
  const input = typeof conversationIdOrInput === 'object'
    ? conversationIdOrInput
    : { conversation_id: conversationIdOrInput, hash }
  if (!/^[0-9a-f]{64}$/.test(input?.hash || ''))
    throw new TypeError('hash must be a lowercase SHA-256 digest')
  return {
    conversation_id: input?.conversation_id,
    hash: input?.hash,
  }
}

export function postWorkflowAssistApply(appId, input) {
  return difyClient.post(
    workflowAssistPath(appId, 'apply'),
    workflowAssistApplyBody(input),
  )
}
