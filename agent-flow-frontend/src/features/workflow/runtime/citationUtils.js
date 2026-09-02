/**
 * Chat citation helpers.
 * Contrasts Dify CitationItem + message_end.metadata.retriever_resources.
 */

/**
 * @param {unknown} item
 * @returns {object | null}
 */
export function normalizeCitationItem(item) {
  if (!item || typeof item !== 'object' || Array.isArray(item))
    return null
  const documentName = String(item.document_name || item.documentName || '').trim()
  const datasetName = String(item.dataset_name || item.datasetName || '').trim()
  const content = String(item.content || '').trim()
  const segmentPosition = item.segment_position ?? item.segmentPosition
  return {
    document_id: item.document_id || item.documentId || '',
    document_name: documentName,
    dataset_id: item.dataset_id || item.datasetId || '',
    dataset_name: datasetName,
    data_source_type: item.data_source_type || item.dataSourceType || '',
    content,
    score: typeof item.score === 'number' ? item.score : null,
    segment_id: item.segment_id || item.segmentId || '',
    segment_position: typeof segmentPosition === 'number' ? segmentPosition : null,
    word_count: typeof item.word_count === 'number' ? item.word_count : (typeof item.wordCount === 'number' ? item.wordCount : null),
    hit_count: typeof item.hit_count === 'number' ? item.hit_count : (typeof item.hitCount === 'number' ? item.hitCount : null),
    index_node_hash: item.index_node_hash || item.indexNodeHash || '',
  }
}

/**
 * @param {unknown} list
 * @returns {object[]}
 */
export function normalizeCitationItems(list) {
  return (Array.isArray(list) ? list : [])
    .map(normalizeCitationItem)
    .filter(Boolean)
}

/**
 * @param {object} item
 * @returns {string}
 */
export function formatCitationLabel(item) {
  if (!item)
    return '引用'
  return item.document_name || item.dataset_name || '未命名文档'
}

/**
 * Group citation items by document (Dify citation/index.tsx resources reduce).
 * @param {unknown} list
 * @returns {Array<{
 *   documentId: string,
 *   documentName: string,
 *   datasetName: string,
 *   dataSourceType: string,
 *   sources: object[],
 * }>}
 */
export function groupCitationsByDocument(list) {
  const items = normalizeCitationItems(list)
  /** @type {Array<{ documentId: string, documentName: string, datasetName: string, dataSourceType: string, sources: object[] }>} */
  const groups = []
  const indexByKey = new Map()

  for (const item of items) {
    const key = item.document_id
      || (item.document_name ? `name:${item.document_name}` : '')
      || (item.segment_id ? `seg:${item.segment_id}` : '')
      || `idx:${groups.length}`

    if (indexByKey.has(key)) {
      groups[indexByKey.get(key)].sources.push(item)
      continue
    }

    indexByKey.set(key, groups.length)
    groups.push({
      documentId: item.document_id || '',
      documentName: item.document_name || formatCitationLabel(item),
      datasetName: item.dataset_name || '',
      dataSourceType: item.data_source_type || '',
      sources: [item],
    })
  }

  return groups
}

/**
 * Whether a citation group can be downloaded (upload_file / file + ids).
 * @param {{ dataSourceType?: string, documentId?: string, sources?: object[] }} group
 */
export function canDownloadCitationGroup(group) {
  const type = group?.dataSourceType || group?.sources?.[0]?.data_source_type || ''
  const isUpload = type === 'upload_file' || type === 'file'
  const datasetId = group?.sources?.[0]?.dataset_id || ''
  const documentId = group?.documentId || group?.sources?.[0]?.document_id || ''
  return Boolean(isUpload && datasetId && documentId)
}

/**
 * Extract retriever_resources from message_end-like payloads.
 * @param {object} event
 * @returns {object[]}
 */
export function extractRetrieverResourcesFromEvent(event) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {}
  const meta = data.metadata || event?.metadata || {}
  return normalizeCitationItems(meta.retriever_resources || meta.retrieverResources || [])
}
