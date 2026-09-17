export function isQaDocument(document) {
  return document?.doc_form === 'qa_model'
}

export function isHierarchicalDocument(document) {
  return document?.doc_form === 'hierarchical_model'
}

export function buildSegmentBody({
  content,
  answer,
  keywords,
  attachmentIds,
  isQa,
  regenerateChildChunks,
} = {}) {
  const body = {
    content: String(content || '').trim(),
    keywords: Array.isArray(keywords) ? keywords : [],
  }
  if (isQa)
    body.answer = String(answer || '').trim()
  if (Array.isArray(attachmentIds) && attachmentIds.length)
    body.attachment_ids = attachmentIds
  if (regenerateChildChunks)
    body.regenerate_child_chunks = true
  return body
}

export function isSegmentBatchImportFinished(status) {
  const value = String(status || '').toLowerCase()
  return value === 'completed' || value === 'error'
}

export function batchSegmentActions(segments) {
  const list = Array.isArray(segments) ? segments : []
  if (!list.length) {
    return {
      canEnable: false,
      canDisable: false,
      canDelete: false,
    }
  }
  return {
    canEnable: list.some(segment => segment.enabled === false),
    canDisable: list.some(segment => segment.enabled !== false),
    canDelete: true,
  }
}

export async function collectAllSegments(fetchPage, pageSize = 100) {
  const firstResponse = await fetchPage({ page: 1, limit: pageSize })
  const firstPage = Array.isArray(firstResponse?.data) ? firstResponse.data : []
  const total = Number(firstResponse?.total)

  if (!firstPage.length || (Number.isFinite(total) && firstPage.length >= total) || firstPage.length < pageSize)
    return firstPage

  if (Number.isFinite(total)) {
    const remainingPages = Array.from(
      { length: Math.ceil(total / pageSize) - 1 },
      (_, index) => index + 2,
    )
    const responses = await Promise.all(
      remainingPages.map(page => fetchPage({ page, limit: pageSize })),
    )
    return [
      ...firstPage,
      ...responses.flatMap(response => Array.isArray(response?.data) ? response.data : []),
    ]
  }

  const collected = [...firstPage]
  let page = 2
  while (true) {
    const response = await fetchPage({ page, limit: pageSize })
    const items = Array.isArray(response?.data) ? response.data : []
    collected.push(...items)
    if (!items.length || items.length < pageSize)
      return collected
    page += 1
  }
}

export function chunkSegmentIds(segmentIds, batchSize = 50) {
  const ids = Array.isArray(segmentIds) ? segmentIds : []
  const size = Number.isInteger(batchSize) && batchSize > 0 ? batchSize : 50
  const batches = []

  for (let index = 0; index < ids.length; index += size)
    batches.push(ids.slice(index, index + size))

  return batches
}

export function csvImportTemplateText(isQa) {
  const rows = isQa
    ? [['问题', '答案'], ['问题 1', '答案 1'], ['问题 2', '答案 2']]
    : [['分段内容'], ['内容 1'], ['内容 2']]
  return rows.map(row => row.join(',')).join('\n')
}
