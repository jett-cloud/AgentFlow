import test from 'node:test'
import assert from 'node:assert/strict'
import {
  batchSegmentActions,
  buildSegmentBody,
  chunkSegmentIds,
  collectAllSegments,
  csvImportTemplateText,
  isHierarchicalDocument,
  isQaDocument,
  isSegmentBatchImportFinished,
} from './segmentPayload.js'

test('collects every segment across paginated responses', async () => {
  const requestedPages = []
  const pages = {
    1: { data: [{ id: 'a' }, { id: 'b' }], total: 5 },
    2: { data: [{ id: 'c' }, { id: 'd' }], total: 5 },
    3: { data: [{ id: 'e' }], total: 5 },
  }

  const segments = await collectAllSegments(async ({ page, limit }) => {
    requestedPages.push({ page, limit })
    return pages[page]
  }, 2)

  assert.deepEqual(segments.map(segment => segment.id), ['a', 'b', 'c', 'd', 'e'])
  assert.deepEqual(requestedPages, [
    { page: 1, limit: 2 },
    { page: 2, limit: 2 },
    { page: 3, limit: 2 },
  ])
})

test('requests remaining segment pages concurrently', async () => {
  let releaseRemainingPages
  const remainingPagesReady = new Promise((resolve) => {
    releaseRemainingPages = resolve
  })
  const requestedPages = []

  const pending = collectAllSegments(async ({ page }) => {
    requestedPages.push(page)
    if (page === 1)
      return { data: [{ id: 'a' }, { id: 'b' }], total: 6 }
    await remainingPagesReady
    return page === 2
      ? { data: [{ id: 'c' }, { id: 'd' }], total: 6 }
      : { data: [{ id: 'e' }, { id: 'f' }], total: 6 }
  }, 2)

  await new Promise(resolve => setImmediate(resolve))
  const pagesRequestedBeforeRelease = [...requestedPages]
  releaseRemainingPages()
  await pending

  assert.deepEqual(pagesRequestedBeforeRelease, [1, 2, 3])
})

test('splits segment ids into URL-safe batches', () => {
  const ids = Array.from({ length: 230 }, (_, index) => `segment-${index + 1}`)

  const batches = chunkSegmentIds(ids, 50)

  assert.deepEqual(batches.map(batch => batch.length), [50, 50, 50, 50, 30])
  assert.deepEqual(batches.flat(), ids)
})

test('QA documents require answer in the segment body', () => {
  assert.equal(isQaDocument({ doc_form: 'qa_model' }), true)
  assert.deepEqual(buildSegmentBody({
    content: '问题',
    answer: '答案',
    keywords: ['合同'],
    isQa: true,
  }), {
    content: '问题',
    answer: '答案',
    keywords: ['合同'],
  })
})

test('general segments omit answer and empty attachments', () => {
  assert.equal(isQaDocument({ doc_form: 'text_model' }), false)
  assert.deepEqual(buildSegmentBody({
    content: '  段落  ',
    keywords: [],
    attachmentIds: [],
    isQa: false,
  }), {
    content: '段落',
    keywords: [],
  })
})

test('attachments are included when present', () => {
  assert.deepEqual(buildSegmentBody({
    content: '图文',
    attachmentIds: ['file-1'],
    isQa: false,
  }), {
    content: '图文',
    keywords: [],
    attachment_ids: ['file-1'],
  })
})

test('hierarchical documents are detected by doc_form', () => {
  assert.equal(isHierarchicalDocument({ doc_form: 'hierarchical_model' }), true)
  assert.equal(isHierarchicalDocument({ doc_form: 'text_model' }), false)
})

test('batch import finishes on completed or error', () => {
  assert.equal(isSegmentBatchImportFinished('waiting'), false)
  assert.equal(isSegmentBatchImportFinished('completed'), true)
  assert.equal(isSegmentBatchImportFinished('error'), true)
})

test('parent-child update can request child regeneration', () => {
  assert.equal(buildSegmentBody({
    content: '父分段',
    regenerateChildChunks: true,
  }).regenerate_child_chunks, true)
})

test('csv templates differ for QA and general documents', () => {
  assert.match(csvImportTemplateText(true), /问题,答案/)
  assert.match(csvImportTemplateText(false), /分段内容/)
})

test('batch segment actions follow selection', () => {
  assert.deepEqual(batchSegmentActions([]), {
    canEnable: false,
    canDisable: false,
    canDelete: false,
  })
  assert.deepEqual(batchSegmentActions([
    { id: 'a', enabled: false },
    { id: 'b', enabled: true },
  ]), {
    canEnable: true,
    canDisable: true,
    canDelete: true,
  })
})
