import test from 'node:test'
import assert from 'node:assert/strict'
import { getDatasetCapabilities, visibleDatasetTabs } from './datasetCapabilities.js'

test('empty permission keys grant all capabilities', () => {
  assert.deepEqual(getDatasetCapabilities(undefined), {
    canRetrievalRecall: true,
    canAccessConfig: true,
    canDelete: true,
  })
  assert.deepEqual(getDatasetCapabilities([]), {
    canRetrievalRecall: true,
    canAccessConfig: true,
    canDelete: true,
  })
})

test('present permission keys map recall, access-config, and delete independently', () => {
  assert.deepEqual(getDatasetCapabilities(['dataset.acl.retrieval_recall']), {
    canRetrievalRecall: true,
    canAccessConfig: false,
    canDelete: false,
  })
  assert.deepEqual(getDatasetCapabilities(['dataset.acl.access_config', 'dataset.acl.delete']), {
    canRetrievalRecall: false,
    canAccessConfig: true,
    canDelete: true,
  })
})

test('external datasets hide documents and pipeline tabs', () => {
  const names = visibleDatasetTabs({
    datasetId: 'ds-1',
    isExternal: true,
    canAccessConfig: true,
  }).map(tab => tab.name)
  assert.deepEqual(names, [
    'dataset-hit-testing',
    'dataset-settings',
    'dataset-access-config',
    'dataset-api',
  ])
})

test('access-config tab is hidden without capability', () => {
  const names = visibleDatasetTabs({
    datasetId: 'ds-1',
    isExternal: false,
    canAccessConfig: false,
  }).map(tab => tab.name)
  assert.equal(names.includes('dataset-access-config'), false)
  assert.deepEqual(names, [
    'dataset-documents',
    'dataset-hit-testing',
    'dataset-settings',
    'dataset-pipeline',
    'dataset-api',
  ])
})
