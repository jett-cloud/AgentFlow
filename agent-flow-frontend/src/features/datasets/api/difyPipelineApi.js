// RAG pipeline create APIs — mirrors web/service/use-pipeline.ts + use-create-dataset.ts
import { CSRF_HEADER_NAME, DIFY_API_PREFIX, getCsrfToken } from '../../../shared/http/difyClient.js'
import difyClient from '../../../shared/http/difyClient.js'

export function fetchPipelineTemplates({ type = 'built-in' } = {}) {
  return difyClient.get('/rag/pipeline/templates', { params: { type } })
}

export function fetchPipelineTemplateDetail(templateId, { type = 'built-in' } = {}) {
  return difyClient.get(`/rag/pipeline/templates/${encodeURIComponent(templateId)}`, {
    params: { type },
  })
}

/** Create pipeline dataset from template DSL. Body: { yaml_content } */
export function createPipelineDatasetFromYaml({ yaml_content }) {
  return difyClient.post('/rag/pipeline/dataset', { yaml_content })
}

export function createEmptyPipelineDataset() {
  return difyClient.post('/rag/pipeline/empty-dataset', {})
}

export function importPipelineDsl({ mode = 'yaml-content', yaml_content, yaml_url }) {
  return difyClient.post('/rag/pipelines/imports', {
    mode,
    ...(yaml_content ? { yaml_content } : {}),
    ...(yaml_url ? { yaml_url } : {}),
  })
}

export function confirmPipelineDslImport(importId) {
  return difyClient.post(`/rag/pipelines/imports/${encodeURIComponent(importId)}/confirm`, {})
}

function pipelinePath(pipelineId, suffix) {
  return `/rag/pipelines/${encodeURIComponent(pipelineId)}${suffix}`
}

/** Contrasts Dify fetchWorkflowDraft → GET /rag/pipelines/{id}/workflows/draft */
export function loadPipelineDraft(pipelineId, { silent = false } = {}) {
  return difyClient.get(pipelinePath(pipelineId, '/workflows/draft'), { silent })
}

/** Contrasts Dify syncWorkflowDraft → POST /rag/pipelines/{id}/workflows/draft */
export function savePipelineDraft(pipelineId, {
  graph,
  hash,
  environment_variables = [],
  conversation_variables = [],
  rag_pipeline_variables = [],
  features,
} = {}) {
  return difyClient.post(pipelinePath(pipelineId, '/workflows/draft'), {
    graph,
    ...(hash != null ? { hash } : {}),
    environment_variables,
    conversation_variables,
    rag_pipeline_variables,
    ...(features != null ? { features } : {}),
  })
}

export function getPublishedPipeline(pipelineId, { silent = false } = {}) {
  return difyClient.get(pipelinePath(pipelineId, '/workflows/publish'), { silent })
}

/** Contrasts Dify publish workflow → POST /rag/pipelines/{id}/workflows/publish */
export function publishPipeline(pipelineId, { marked_name = '', marked_comment = '' } = {}) {
  return difyClient.post(pipelinePath(pipelineId, '/workflows/publish'), {
    marked_name,
    marked_comment,
  })
}

/** Convert a general dataset into rag_pipeline mode. */
export function transformDatasetToPipeline(datasetId) {
  return difyClient.post(`/rag/pipelines/transform/datasets/${encodeURIComponent(datasetId)}`)
}

export function isDraftWorkflowNotExistError(error) {
  const data = error?.response?.data
  return data?.code === 'draft_workflow_not_exist'
    || /draft_workflow_not_exist/i.test(String(data?.message || error?.message || ''))
}

export function stopPipelineRun(pipelineId, taskId) {
  return difyClient.post(
    pipelinePath(pipelineId, `/workflow-runs/tasks/${encodeURIComponent(taskId)}/stop`),
    {},
  )
}

/** Contrasts Dify run history → GET /rag/pipelines/{id}/workflow-runs */
export function listPipelineRuns(pipelineId, { limit = 20, lastId } = {}) {
  return difyClient.get(pipelinePath(pipelineId, '/workflow-runs'), {
    params: {
      limit,
      ...(lastId ? { last_id: lastId } : {}),
    },
  })
}

export function getPipelineRun(pipelineId, runId) {
  return difyClient.get(
    pipelinePath(pipelineId, `/workflow-runs/${encodeURIComponent(runId)}`),
  )
}

export function getPipelineRunNodeExecutions(pipelineId, runId) {
  return difyClient.get(
    pipelinePath(pipelineId, `/workflow-runs/${encodeURIComponent(runId)}/node-executions`),
  )
}

/** Contrasts Dify version list → GET /rag/pipelines/{id}/workflows */
export function listPublishedPipelines(pipelineId, { page = 1, limit = 20, namedOnly = false } = {}) {
  return difyClient.get(pipelinePath(pipelineId, '/workflows'), {
    params: {
      page,
      limit,
      named_only: namedOnly,
    },
  })
}

export function getPublishedPipelineVersion(pipelineId, workflowId) {
  return difyClient.get(
    pipelinePath(pipelineId, `/workflows/${encodeURIComponent(workflowId)}`),
  )
}

export function restorePipelineVersion(pipelineId, workflowId) {
  return difyClient.post(
    pipelinePath(pipelineId, `/workflows/${encodeURIComponent(workflowId)}/restore`),
    {},
  )
}

export async function runPipelineDraft(pipelineId, {
  inputs = {},
  onEvent = () => {},
  signal,
} = {}) {
  return consumeFetchSse(`${DIFY_API_PREFIX}${pipelinePath(pipelineId, '/workflows/draft/run')}`, {
    method: 'POST',
    body: JSON.stringify({ inputs }),
    onEvent,
    signal,
  })
}

function shouldConsumeAsSse(response) {
  const contentType = String(response.headers.get('content-type') || '').toLowerCase()
  return contentType.includes('text/event-stream')
}

function parseSseBlock(block) {
  const lines = String(block || '').split(/\r?\n/)
  const eventType = lines
    .find(line => line.startsWith('event:'))
    ?.slice('event:'.length)
    ?.trim()
  const dataLines = lines
    .filter(line => line.startsWith('data:'))
    .map(line => line.slice('data:'.length).trim())
  if (!eventType && !dataLines.length)
    return null
  const raw = dataLines.join('\n')
  if (!raw)
    return eventType ? { event: eventType } : null
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') {
      if (!parsed.event && eventType)
        parsed.event = eventType
      return parsed
    }
    return eventType ? { event: eventType, data: parsed } : parsed
  }
  catch {
    return eventType ? { event: eventType, data: raw } : { data: raw }
  }
}

function consumeSseText(buffer, onEvent) {
  let cursor = 0
  while (true) {
    const sep = buffer.indexOf('\n\n', cursor)
    if (sep === -1)
      break
    const block = buffer.slice(cursor, sep).trim()
    cursor = sep + 2
    if (!block)
      continue
    const payload = parseSseBlock(block)
    if (payload)
      onEvent(payload)
  }
  return buffer.slice(cursor)
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
  const csrfToken = getCsrfToken(document.cookie)
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
      // fallback to status text for non-JSON errors
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
