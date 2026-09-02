const INDEXING_STATUSES = new Set([
  'waiting',
  'queuing',
  'parsing',
  'cleaning',
  'splitting',
  'indexing',
])

function documentStatus(document) {
  return String(document?.display_status || document?.indexing_status || '').toLowerCase()
}

export function isDocumentArchived(document) {
  return Boolean(document?.archived)
}

export function isDocumentEnabled(document) {
  if (document?.enabled === false || document?.display_status === 'disabled')
    return false
  return true
}

export function documentIndexingError(document) {
  const status = documentStatus(document)
  if (status !== 'error')
    return ''
  const error = document?.error
  if (typeof error === 'string' && error.trim())
    return error.trim()
  if (error && typeof error === 'object') {
    const message = error.message || error.error || error.detail
    if (message)
      return String(message).trim()
  }
  return ''
}

export function documentRowActions(document) {
  const archived = isDocumentArchived(document)
  const enabled = isDocumentEnabled(document)
  const status = documentStatus(document)
  const indexing = INDEXING_STATUSES.has(status)

  return {
    canRename: !archived,
    canDownload: !archived && document?.data_source_type === 'upload_file',
    canPause: !archived && status === 'indexing',
    canResume: !archived && status === 'paused',
    canArchive: !archived,
    canUnarchive: archived,
    canEnable: !archived && !enabled,
    canDisable: !archived && enabled && !indexing,
    canRetry: !archived && status === 'error',
    canDelete: true,
  }
}

export function batchDocumentActions(documents) {
  const list = Array.isArray(documents) ? documents : []
  if (!list.length) {
    return {
      canEnable: false,
      canDisable: false,
      canDelete: false,
    }
  }
  return {
    canEnable: list.some(document => documentRowActions(document).canEnable),
    canDisable: list.some(document => documentRowActions(document).canDisable),
    canDelete: true,
  }
}
