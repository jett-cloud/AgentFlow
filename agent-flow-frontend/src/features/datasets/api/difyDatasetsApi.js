// Console dataset APIs — mirrors web/service/datasets.ts + knowledge/use-document.ts
import difyClient from '../../../shared/http/difyClient.js'

export function fetchDatasets({ page = 1, limit = 30, keyword = '', ids, include_all } = {}) {
  return difyClient.get('/datasets', {
    params: {
      page,
      limit,
      ...(keyword ? { keyword } : {}),
      ...(ids?.length ? { ids } : {}),
      ...(include_all != null ? { include_all } : {}),
    },
  })
}

export function createEmptyDataset({ name, description } = {}) {
  return difyClient.post('/datasets', {
    name,
    ...(description ? { description } : {}),
  })
}

export function fetchDatasetDetail(datasetId) {
  return difyClient.get(`/datasets/${encodeURIComponent(datasetId)}`)
}

export function updateDataset(datasetId, body) {
  return difyClient.patch(`/datasets/${encodeURIComponent(datasetId)}`, body)
}

export function deleteDataset(datasetId) {
  return difyClient.delete(`/datasets/${encodeURIComponent(datasetId)}`)
}

export function checkDatasetUsedInApp(datasetId) {
  return difyClient.get(`/datasets/${encodeURIComponent(datasetId)}/use-check`, { silent: true })
}

export function fetchRetrievalSetting() {
  return difyClient.get('/datasets/retrieval-setting')
}

export function fetchDefaultProcessRule({ documentId } = {}) {
  return difyClient.get('/datasets/process-rule', {
    params: documentId ? { document_id: documentId } : undefined,
  })
}

export function fetchIndexingEstimate(body) {
  return difyClient.post('/datasets/indexing-estimate', body)
}

/** Create dataset + first documents. Contrasts POST /datasets/init */
export function createFirstDocument(body) {
  return difyClient.post('/datasets/init', body)
}

/** Add documents to existing dataset. Contrasts POST /datasets/{id}/documents */
export function createDocument(datasetId, body) {
  return difyClient.post(`/datasets/${encodeURIComponent(datasetId)}/documents`, body)
}

export function fetchDocuments(datasetId, {
  page = 1,
  limit = 20,
  keyword = '',
  sort,
  status,
} = {}) {
  return difyClient.get(`/datasets/${encodeURIComponent(datasetId)}/documents`, {
    params: {
      page,
      limit,
      ...(keyword ? { keyword } : {}),
      ...(sort ? { sort } : {}),
      ...(status && status !== 'all' ? { status } : {}),
    },
  })
}

export function fetchDocumentDetail(datasetId, documentId) {
  return difyClient.get(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}`,
  )
}

export function fetchBatchIndexingStatus(datasetId, batchId) {
  return difyClient.get(
    `/datasets/${encodeURIComponent(datasetId)}/batch/${encodeURIComponent(batchId)}/indexing-status`,
  )
}

export function fetchDocumentIndexingStatus(datasetId, documentId) {
  return difyClient.get(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/indexing-status`,
  )
}

export function deleteDocuments(datasetId, documentIds) {
  const ids = Array.isArray(documentIds) ? documentIds : [documentIds]
  return difyClient.delete(
    `/datasets/${encodeURIComponent(datasetId)}/documents`,
    { params: { document_id: ids } },
  )
}

export function retryDocuments(datasetId, documentIds) {
  return difyClient.post(`/datasets/${encodeURIComponent(datasetId)}/retry`, {
    document_ids: documentIds,
  })
}

export function patchDocumentsStatus(datasetId, action, documentIds) {
  const ids = Array.isArray(documentIds) ? documentIds : [documentIds]
  return difyClient.patch(
    `/datasets/${encodeURIComponent(datasetId)}/documents/status/${encodeURIComponent(action)}/batch`,
    {},
    { params: { document_id: ids } },
  )
}

export function renameDocument(datasetId, documentId, name) {
  return difyClient.post(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/rename`,
    { name },
  )
}

export function pauseDocumentIndexing(datasetId, documentId) {
  return difyClient.patch(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/processing/pause`,
  )
}

export function resumeDocumentIndexing(datasetId, documentId) {
  return difyClient.patch(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/processing/resume`,
  )
}

/**
 * Get download URL for an uploaded knowledge document.
 * Contrasts Dify GET /datasets/{id}/documents/{id}/download
 * @returns {Promise<{ url?: string }>}
 */
export function fetchDocumentDownloadUrl(datasetId, documentId) {
  return difyClient.get(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/download`,
    { silent: true },
  )
}

export function hitTesting(datasetId, body) {
  return difyClient.post(`/datasets/${encodeURIComponent(datasetId)}/hit-testing`, body)
}

export function externalHitTesting(datasetId, body) {
  return difyClient.post(`/datasets/${encodeURIComponent(datasetId)}/external-hit-testing`, body)
}

export function fetchHitTestingRecords(datasetId, { page = 1, limit = 10 } = {}) {
  return difyClient.get(`/datasets/${encodeURIComponent(datasetId)}/queries`, {
    params: { page, limit },
  })
}

/* ---- External knowledge API ---- */

export function fetchExternalKnowledgeApis({ page = 1, limit = 30, keyword = '' } = {}) {
  return difyClient.get('/datasets/external-knowledge-api', {
    params: {
      page,
      limit,
      ...(keyword ? { keyword } : {}),
    },
  })
}

export function createExternalKnowledgeApi({ name, endpoint, api_key }) {
  return difyClient.post('/datasets/external-knowledge-api', {
    name,
    settings: { endpoint, api_key },
  })
}

export function updateExternalKnowledgeApi(apiId, { name, endpoint, api_key }) {
  return difyClient.patch(`/datasets/external-knowledge-api/${encodeURIComponent(apiId)}`, {
    name,
    settings: { endpoint, api_key },
  })
}

export function deleteExternalKnowledgeApi(apiId) {
  return difyClient.delete(`/datasets/external-knowledge-api/${encodeURIComponent(apiId)}`)
}

export function checkExternalKnowledgeApiUsage(apiId) {
  return difyClient.get(
    `/datasets/external-knowledge-api/${encodeURIComponent(apiId)}/use-check`,
    { silent: true },
  )
}

/** Connect an external KB as a workspace dataset. Contrasts POST /datasets/external */
export function createExternalKnowledgeBase(body) {
  return difyClient.post('/datasets/external', body)
}

/* ---- Website crawl ---- */

export function createWebsiteCrawl({ provider, url, options }) {
  return difyClient.post('/website/crawl', { provider, url, options })
}

export function fetchWebsiteCrawlStatus(jobId, provider) {
  return difyClient.get(`/website/crawl/status/${encodeURIComponent(jobId)}`, {
    params: { provider },
  })
}

export function fetchSegments(datasetId, documentId, {
  page = 1,
  limit = 20,
  keyword = '',
  enabled = 'all',
} = {}) {
  return difyClient.get(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/segments`,
    {
      params: {
        page,
        limit,
        ...(keyword ? { keyword } : {}),
        ...(enabled === 'all' || enabled === '' ? {} : { enabled }),
      },
    },
  )
}

export function addSegment(datasetId, documentId, body) {
  return difyClient.post(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/segment`,
    body,
  )
}

export function updateSegment(datasetId, documentId, segmentId, body) {
  return difyClient.patch(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/segments/${encodeURIComponent(segmentId)}`,
    body,
  )
}

export function deleteSegments(datasetId, documentId, segmentIds) {
  const ids = Array.isArray(segmentIds) ? segmentIds : [segmentIds]
  const query = ids.map(id => `segment_id=${encodeURIComponent(id)}`).join('&')
  return difyClient.delete(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/segments?${query}`,
  )
}

export function enableSegments(datasetId, documentId, segmentIds) {
  const ids = Array.isArray(segmentIds) ? segmentIds : [segmentIds]
  const query = ids.map(id => `segment_id=${encodeURIComponent(id)}`).join('&')
  return difyClient.patch(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/segment/enable?${query}`,
  )
}

export function disableSegments(datasetId, documentId, segmentIds) {
  const ids = Array.isArray(segmentIds) ? segmentIds : [segmentIds]
  const query = ids.map(id => `segment_id=${encodeURIComponent(id)}`).join('&')
  return difyClient.patch(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/segment/disable?${query}`,
  )
}

function childChunksPath(datasetId, documentId, segmentId, childChunkId) {
  const base = `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/segments/${encodeURIComponent(segmentId)}/child_chunks`
  return childChunkId ? `${base}/${encodeURIComponent(childChunkId)}` : base
}

export function fetchChildChunks(datasetId, documentId, segmentId, {
  page = 1,
  limit = 50,
  keyword = '',
} = {}) {
  return difyClient.get(childChunksPath(datasetId, documentId, segmentId), {
    params: {
      page,
      limit,
      ...(keyword ? { keyword } : {}),
    },
  })
}

export function addChildChunk(datasetId, documentId, segmentId, content) {
  return difyClient.post(childChunksPath(datasetId, documentId, segmentId), { content })
}

export function updateChildChunk(datasetId, documentId, segmentId, childChunkId, content) {
  return difyClient.patch(childChunksPath(datasetId, documentId, segmentId, childChunkId), { content })
}

export function deleteChildChunk(datasetId, documentId, segmentId, childChunkId) {
  return difyClient.delete(childChunksPath(datasetId, documentId, segmentId, childChunkId))
}

export function importSegmentsCsv(datasetId, documentId, uploadFileId) {
  return difyClient.post(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/segments/batch_import`,
    { upload_file_id: uploadFileId },
  )
}

export function fetchSegmentBatchImportStatus(jobId) {
  return difyClient.get(`/datasets/batch_import_status/${encodeURIComponent(jobId)}`)
}

export function fetchDatasetMetadata(datasetId) {
  return difyClient.get(`/datasets/${encodeURIComponent(datasetId)}/metadata`)
}

export function createDatasetMetadata(datasetId, { type, name }) {
  return difyClient.post(`/datasets/${encodeURIComponent(datasetId)}/metadata`, { type, name })
}

export function renameDatasetMetadata(datasetId, metadataId, name) {
  return difyClient.patch(
    `/datasets/${encodeURIComponent(datasetId)}/metadata/${encodeURIComponent(metadataId)}`,
    { name },
  )
}

export function deleteDatasetMetadata(datasetId, metadataId) {
  return difyClient.delete(
    `/datasets/${encodeURIComponent(datasetId)}/metadata/${encodeURIComponent(metadataId)}`,
  )
}

export function fetchBuiltInMetadataFields() {
  return difyClient.get('/datasets/metadata/built-in')
}

export function setBuiltInMetadata(datasetId, enabled) {
  const action = enabled ? 'enable' : 'disable'
  return difyClient.post(
    `/datasets/${encodeURIComponent(datasetId)}/metadata/built-in/${action}`,
  )
}

export function updateDocumentsMetadata(datasetId, operationData) {
  return difyClient.post(
    `/datasets/${encodeURIComponent(datasetId)}/documents/metadata`,
    { operation_data: operationData },
  )
}

/* ---- Service API ---- */

export function fetchDatasetApiBaseInfo() {
  return difyClient.get('/datasets/api-base-info')
}

export function fetchDatasetRelatedApps(datasetId) {
  return difyClient.get(`/datasets/${encodeURIComponent(datasetId)}/related-apps`)
}

export function enableDatasetServiceApi(datasetId) {
  return difyClient.post(`/datasets/${encodeURIComponent(datasetId)}/api-keys/enable`)
}

export function disableDatasetServiceApi(datasetId) {
  return difyClient.post(`/datasets/${encodeURIComponent(datasetId)}/api-keys/disable`)
}

export function fetchDatasetApiKeys() {
  return difyClient.get('/datasets/api-keys')
}

export function createDatasetApiKey() {
  return difyClient.post('/datasets/api-keys', {})
}

export function deleteDatasetApiKey(keyId) {
  return difyClient.delete(`/datasets/api-keys/${encodeURIComponent(keyId)}`)
}
