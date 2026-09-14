import difyClient, {
  CSRF_HEADER_NAME,
  DIFY_API_PREFIX,
  getCsrfToken,
} from '../../../shared/http/difyClient.js'
import { consumeSseText, parseSseBlock, shouldConsumeAsSse } from '../../../shared/http/difyProtocol.js'
import { buildInitialDraftPayloadForMode } from '../model/workflowTemplates.js'
import { normalizeWorkflowFeatures as normalizeFeaturesShape } from '../model/workflowFeatures.js'

export {
  consumeSseText,
  HIDDEN_SECRET_VALUE,
  parseSseBlock,
  sanitizeEnvironmentVariables,
  shouldConsumeAsSse,
} from '../../../shared/http/difyProtocol.js'

export { normalizeWorkflowFeatures } from '../model/workflowFeatures.js'

function appPath(appId, suffix) {
  return `/apps/${encodeURIComponent(appId)}${suffix}`
}

export function listApps({ page = 1, limit = 30, mode, name, sort_by = 'last_modified' } = {}) {
  // Contrasts Dify apps/list query: mode / name / sort_by / tag_ids / creator_ids
  return difyClient.get('/apps', {
    params: {
      page,
      limit,
      sort_by,
      ...(mode ? { mode } : {}),
      ...(name ? { name } : {}),
    },
  })
}

export function createApp({
  name,
  mode = 'workflow',
  description = '',
  icon_type = 'emoji',
  icon = '🤖',
  icon_background,
} = {}) {
  const resolvedIconBackground = icon_background ?? (icon_type === 'emoji' ? '#FFEAD5' : undefined)
  return difyClient.post('/apps', {
    name,
    mode,
    description,
    icon_type,
    icon,
    ...(resolvedIconBackground != null ? { icon_background: resolvedIconBackground } : {}),
  })
}

/** Contrasts Dify deleteApp → DELETE /apps/{id} */
export function deleteApp(appId) {
  return difyClient.delete(appPath(appId, ''))
}

/** Contrasts Dify importDSL → POST /apps/imports */
export function importAppDsl({
  mode = 'yaml-content',
  yaml_content,
  yaml_url,
  name,
  description,
  icon_type,
  icon,
  icon_background,
} = {}) {
  return difyClient.post('/apps/imports', {
    mode,
    ...(yaml_content != null ? { yaml_content } : {}),
    ...(yaml_url != null ? { yaml_url } : {}),
    ...(name != null ? { name } : {}),
    ...(description != null ? { description } : {}),
    ...(icon_type != null ? { icon_type } : {}),
    ...(icon != null ? { icon } : {}),
    ...(icon_background != null ? { icon_background } : {}),
  })
}

export function exportAppDsl(appId, { includeSecret = false } = {}) {
  return difyClient.get(appPath(appId, '/export'), {
    params: { include_secret: includeSecret },
  })
}

/** Contrasts Dify importDSLConfirm → POST /apps/imports/{id}/confirm */
export function confirmAppDslImport(importId) {
  return difyClient.post(`/apps/imports/${encodeURIComponent(importId)}/confirm`, {})
}

export function loadDraft(appId, options = {}) {
  return difyClient.get(appPath(appId, '/workflows/draft'), {
    silent: options.silent,
  })
}

export function loadAppDetail(appId) {
  return difyClient.get(appPath(appId, ''))
}

export function updateAppDetail(appId, payload) {
  return difyClient.put(appPath(appId, ''), payload)
}

export function saveDraft(appId, payload) {
  return difyClient.post(appPath(appId, '/workflows/draft'), payload)
}

/** Contrasts Dify updateFeatures → POST /apps/{id}/workflows/draft/features */
export function updateFeatures(appId, features) {
  return difyClient.post(appPath(appId, '/workflows/draft/features'), {
    features: normalizeFeaturesShape(features),
  })
}

/** Contrasts Dify fetchSuggestedQuestions → GET /apps/{id}/chat-messages/{messageId}/suggested-questions */
export function fetchSuggestedQuestions(appId, messageId) {
  return difyClient.get(
    appPath(appId, `/chat-messages/${encodeURIComponent(messageId)}/suggested-questions`),
  )
}

/** New apps have no draft until the first sync POST (same as Dify web onboarding). */
export function buildInitialDraftPayload(mode = 'workflow') {
  return buildInitialDraftPayloadForMode(mode)
}

export async function ensureDraft(appId, { mode = 'workflow' } = {}) {
  try {
    return await loadDraft(appId, { silent: true })
  } catch (error) {
    const code = error.response?.data?.code
    if (error.response?.status !== 404 && code !== 'draft_workflow_not_exist')
      throw error
    await saveDraft(appId, buildInitialDraftPayload(mode))
    return loadDraft(appId)
  }
}

export function updateEnvironmentVariables(appId, environmentVariables) {
  return difyClient.post(appPath(appId, '/workflows/draft/environment-variables'), {
    environment_variables: environmentVariables,
  })
}

export function updateConversationVariables(appId, conversationVariables) {
  return difyClient.post(appPath(appId, '/workflows/draft/conversation-variables'), {
    conversation_variables: conversationVariables,
  })
}

/**
 * Single-node run. Contrasts Dify singleNodeRun — no advanced-chat prefix
 * (only iteration/loop SSE URLs use that prefix).
 */
export function runNode(appId, nodeId, payload) {
  return difyClient.post(
    appPath(appId, `/workflows/draft/nodes/${encodeURIComponent(nodeId)}/run`),
    payload,
  )
}

/**
 * Cached last single-node run. Contrasts Dify useLastRun GET .../last-run.
 * 404 means no prior run.
 */
export function fetchNodeLastRun(appId, nodeId) {
  return difyClient.get(
    appPath(appId, `/workflows/draft/nodes/${encodeURIComponent(nodeId)}/last-run`),
    { silent: true },
  )
}

/** Draft inspect vars (paginated). Contrasts Dify fetchAllInspectVars. */
export function listInspectVars(appId, { page = 1, limit = 100 } = {}) {
  return difyClient.get(appPath(appId, '/workflows/draft/variables'), {
    params: { page, limit },
    silent: true,
  })
}

export async function fetchAllInspectVars(appId) {
  const first = await listInspectVars(appId, { page: 1, limit: 100 })
  const items = [...(first.items || first.data || [])]
  const total = first.total ?? items.length
  if (total <= items.length)
    return items
  const pageCount = Math.ceil(total / 100)
  const rest = await Promise.all(
    Array.from({ length: pageCount - 1 }, (_, i) => listInspectVars(appId, { page: i + 2, limit: 100 })),
  )
  for (const page of rest)
    items.push(...(page.items || page.data || []))
  return items
}

export function fetchNodeInspectVars(appId, nodeId) {
  return difyClient.get(
    appPath(appId, `/workflows/draft/nodes/${encodeURIComponent(nodeId)}/variables`),
    { silent: true },
  ).then(res => res.items || res.data || res || [])
}

export function fetchConversationInspectVars(appId) {
  return difyClient.get(appPath(appId, '/workflows/draft/conversation-variables'), { silent: true })
}

export function fetchSystemInspectVars(appId) {
  return difyClient.get(appPath(appId, '/workflows/draft/system-variables'), { silent: true })
}

/** Contrasts Dify useEditInspectorVar. */
export function patchInspectVar(appId, varId, { name, value } = {}) {
  const body = {}
  if (name !== undefined)
    body.name = name
  if (value !== undefined)
    body.value = value
  return difyClient.patch(
    appPath(appId, `/workflows/draft/variables/${encodeURIComponent(varId)}`),
    body,
  )
}

/** Contrasts Dify useDeleteInspectVar. */
export function deleteInspectVar(appId, varId) {
  return difyClient.delete(
    appPath(appId, `/workflows/draft/variables/${encodeURIComponent(varId)}`),
  )
}

/** Contrasts Dify useResetToLastRunValue / useResetConversationVar. */
export function resetInspectVar(appId, varId) {
  return difyClient.put(
    appPath(appId, `/workflows/draft/variables/${encodeURIComponent(varId)}/reset`),
  )
}

/** Contrasts Dify useDeleteAllInspectorVars. */
export function deleteAllInspectVars(appId) {
  return difyClient.delete(appPath(appId, '/workflows/draft/variables'))
}

/** Contrasts Dify useDeleteNodeInspectorVars. */
export function deleteNodeInspectVars(appId, nodeId) {
  return difyClient.delete(
    appPath(appId, `/workflows/draft/nodes/${encodeURIComponent(nodeId)}/variables`),
  )
}

/**
 * Debug run history list. Contrasts Dify view-history historyUrl
 * (advanced-chat uses prefix; detail/trace do not).
 */
export function listWorkflowRuns(appId, { limit = 20, lastId, mode = 'workflow' } = {}) {
  const prefix = mode === 'advanced-chat' ? '/advanced-chat' : ''
  return difyClient.get(appPath(appId, `${prefix}/workflow-runs`), {
    params: {
      limit,
      ...(lastId ? { last_id: lastId } : {}),
    },
  })
}

export function getWorkflowRun(appId, runId) {
  return difyClient.get(appPath(appId, `/workflow-runs/${encodeURIComponent(runId)}`))
}

export function getWorkflowRunNodeExecutions(appId, runId) {
  return difyClient.get(
    appPath(appId, `/workflow-runs/${encodeURIComponent(runId)}/node-executions`),
  )
}

export function stopRun(appId, taskId) {
  return difyClient.post(
    appPath(appId, `/workflow-runs/tasks/${encodeURIComponent(taskId)}/stop`),
    {},
  )
}

export function publishWorkflow(appId, payload = {}) {
  return difyClient.post(appPath(appId, '/workflows/publish'), payload)
}

export function listPublishedWorkflows(appId, { page = 1, limit = 20, namedOnly = false } = {}) {
  return difyClient.get(appPath(appId, '/workflows'), {
    params: {
      page,
      limit,
      named_only: namedOnly,
    },
  })
}

export function getPublishedWorkflow(appId, workflowId) {
  return difyClient.get(appPath(appId, `/workflows/${encodeURIComponent(workflowId)}`))
}

export function restoreWorkflowVersion(appId, workflowId) {
  return difyClient.post(appPath(appId, `/workflows/${encodeURIComponent(workflowId)}/restore`), {})
}

export function fetchTextGenerationModels() {
  return difyClient.get('/workspaces/current/models/model-types/llm')
}

// Re-export workspace model helpers for callers that already import this module.
export {
  createProviderCredential,
  fetchModelParameterRules,
  fetchModelProviders,
  fetchModelsByType,
  switchProviderCredential,
  validateProviderCredential,
} from '../../integrations/api/difyModelsApi.js'

export async function runDraft(appId, {
  inputs = {},
  files = [],
  query = '',
  conversationId = null,
  parentMessageId = null,
  mode = 'workflow',
  onEvent = () => {},
  signal,
} = {}) {
  const isChatflow = mode === 'advanced-chat'
  const path = isChatflow
    ? appPath(appId, '/advanced-chat/workflows/draft/run')
    : appPath(appId, '/workflows/draft/run')
  const body = isChatflow
    ? {
        inputs,
        files,
        query,
        conversation_id: conversationId,
        parent_message_id: parentMessageId,
      }
    : { inputs, files }

  return consumeFetchSse(`${DIFY_API_PREFIX}${path}`, {
    method: 'POST',
    body: JSON.stringify(body),
    onEvent,
    signal,
  })
}

/** Contrasts Dify submitHumanInputForm → POST /form/human_input/{token} */
export function submitHumanInputForm(formToken, { inputs = {}, action } = {}) {
  return difyClient.post(`/form/human_input/${encodeURIComponent(formToken)}`, {
    inputs,
    action,
  })
}

/**
 * Resume SSE after workflow_paused.
 * Contrasts Dify sseGet(`/workflow/${workflow_run_id}/events`).
 */
export async function subscribeWorkflowEvents(workflowRunId, {
  onEvent = () => {},
  signal,
} = {}) {
  if (!workflowRunId)
    throw new Error('workflowRunId is required to subscribe events')
  const path = `/workflow/${encodeURIComponent(workflowRunId)}/events`
  return consumeFetchSse(`${DIFY_API_PREFIX}${path}`, {
    method: 'GET',
    onEvent,
    signal,
  })
}

async function consumeFetchSse(url, {
  method = 'GET',
  body,
  onEvent = () => {},
  signal,
} = {}) {
  const headers = {
    Accept: 'text/event-stream',
  }
  if (body != null)
    headers['Content-Type'] = 'application/json'
  const csrfToken = getCsrfToken()
  if (csrfToken)
    headers[CSRF_HEADER_NAME] = csrfToken

  const response = await fetch(url, {
    method,
    credentials: 'include',
    headers,
    ...(body != null ? { body } : {}),
    signal,
  })
  if (!response.ok) {
    let errorData = null
    try {
      errorData = await response.json()
    }
    catch {
      // The status text is the fallback for non-JSON proxy errors.
    }
    const error = new Error(errorData?.message || errorData?.error || response.statusText)
    error.status = response.status
    error.data = errorData
    throw error
  }

  if (!shouldConsumeAsSse(response)) {
    const payload = await response.json()
    onEvent(payload)
    return payload
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    buffer = consumeSseText(buffer, onEvent)
    if (done)
      break
  }
  if (buffer.trim()) {
    const payload = parseSseBlock(buffer)
    if (payload)
      onEvent(payload)
  }
  return null
}
