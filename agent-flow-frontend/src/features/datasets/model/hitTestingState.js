const VECTOR_SEARCH_METHODS = new Set(['semantic_search', 'hybrid_search'])
const READY_STATUSES = new Set(['completed', 'available'])

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

