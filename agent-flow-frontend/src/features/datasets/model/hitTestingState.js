const VECTOR_SEARCH_METHODS = new Set(['semantic_search', 'hybrid_search'])
const READY_STATUSES = new Set(['completed', 'available'])

export function normalizeHitTestingHistory(records) {
  return (Array.isArray(records) ? records : []).flatMap((record) => {
    const queries = Array.isArray(record?.queries) ? record.queries : []
    const textQuery = queries.find(item => item?.content_type === 'text_query' && item.content?.trim())
    const imageQuery = queries.find(item => item?.content_type === 'image_query' && item.file_info?.name)
    const text = textQuery?.content?.trim() || imageQuery?.file_info?.name || ''

    return text
      ? [{ id: record.id, text, createdAt: record.created_at }]
      : []
  })
}

export function normalizeHitTestingHistoryPage(response) {
  const page = Number(response?.page)
  const total = Number(response?.total)

  return {
    rows: normalizeHitTestingHistory(response?.data),
    page: Number.isFinite(page) && page > 0 ? page : 1,
    total: Number.isFinite(total) && total > 0 ? total : 0,
  }
}

function documentStatus(document) {
  return String(document?.display_status || document?.indexing_status || '').toLowerCase()
}

export function resolveHitTestingSearch({ preferredMethod, documents }) {
  const method = preferredMethod || 'semantic_search'
  if (!VECTOR_SEARCH_METHODS.has(method))
    return { method, warning: '' }

  const enabledDocuments = (Array.isArray(documents) ? documents : [])
    .filter(document => document?.enabled !== false && !document?.archived)
  const hasReadyDocument = enabledDocuments.some(document => READY_STATUSES.has(documentStatus(document)))
  const hasFailedDocument = enabledDocuments.some(document => documentStatus(document) === 'error')

  if (!hasReadyDocument && hasFailedDocument) {
    return {
      method: 'full_text_search',
      warning: '向量索引失败，已切换为全文检索。修复文档索引后可再使用向量或混合检索。',
    }
  }

  return { method, warning: '' }
}

