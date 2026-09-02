import test from 'node:test'
import assert from 'node:assert/strict'
import { batchDocumentActions, documentIndexingError, documentRowActions } from './documentActions.js'

test('completed document can be disabled, archived, renamed, deleted, not paused', () => {
  assert.deepEqual(documentRowActions({
    enabled: true,
    archived: false,
    indexing_status: 'completed',
    data_source_type: 'upload_file',
  }), {
    canRename: true,
    canDownload: true,
    canPause: false,
    canResume: false,
    canArchive: true,
    canUnarchive: false,
    canEnable: false,
    canDisable: true,
    canRetry: false,
    canDelete: true,
  })
})

test('disabled document can be enabled, not disabled again', () => {
  const actions = documentRowActions({
    enabled: false,
    archived: false,
    display_status: 'disabled',
    data_source_type: 'upload_file',
  })
  assert.equal(actions.canEnable, true)
  assert.equal(actions.canDisable, false)
  assert.equal(actions.canRename, true)
})

test('indexing document can pause but not disable or archive-adjacent ops that mutate index', () => {
  const actions = documentRowActions({
    enabled: true,
    archived: false,
    indexing_status: 'indexing',
    display_status: 'indexing',
  })
  assert.equal(actions.canPause, true)
  assert.equal(actions.canResume, false)
  assert.equal(actions.canDisable, false)
  assert.equal(actions.canRetry, false)
})

test('paused document can resume', () => {
  const actions = documentRowActions({
    enabled: true,
    archived: false,
    indexing_status: 'paused',
    display_status: 'paused',
  })
  assert.equal(actions.canResume, true)
  assert.equal(actions.canPause, false)
})

test('archived document can only unarchive or delete', () => {
  const actions = documentRowActions({
    enabled: true,
    archived: true,
    indexing_status: 'completed',
    data_source_type: 'upload_file',
  })
  assert.equal(actions.canRename, false)
  assert.equal(actions.canDownload, false)
  assert.equal(actions.canArchive, false)
  assert.equal(actions.canUnarchive, true)
  assert.equal(actions.canEnable, false)
  assert.equal(actions.canDisable, false)
  assert.equal(actions.canDelete, true)
})

test('error document can retry', () => {
  assert.equal(documentRowActions({
    enabled: true,
    archived: false,
    indexing_status: 'error',
  }).canRetry, true)
})

test('error documents expose the indexing error text', () => {
  assert.equal(documentIndexingError({
    indexing_status: 'error',
    error: '  ProviderNotInitializeError: No Embedding Model available  ',
  }), 'ProviderNotInitializeError: No Embedding Model available')
  assert.equal(documentIndexingError({
    display_status: 'error',
    error: { message: 'rerank model missing' },
  }), 'rerank model missing')
  assert.equal(documentIndexingError({ indexing_status: 'completed', error: 'stale' }), '')
  assert.equal(documentIndexingError({ indexing_status: 'error' }), '')
})

test('download is only for uploaded files', () => {
  assert.equal(documentRowActions({
    enabled: true,
    archived: false,
    indexing_status: 'completed',
    data_source_type: 'website_crawl',
  }).canDownload, false)
})

test('batch actions follow selected rows', () => {
  assert.deepEqual(batchDocumentActions([]), {
    canEnable: false,
    canDisable: false,
    canDelete: false,
  })
  assert.deepEqual(batchDocumentActions([
    { enabled: false, archived: false, display_status: 'disabled' },
    { enabled: true, archived: false, indexing_status: 'completed' },
  ]), {
    canEnable: true,
    canDisable: true,
    canDelete: true,
  })
})
