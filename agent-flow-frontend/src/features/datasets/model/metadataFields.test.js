import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildDocumentsMetadataBody,
  defaultOperatorForType,
  intersectMetadataByName,
  mergeDocumentMetadataForBatch,
  metadataNameError,
  operatorRequiresValue,
  operatorsForMetadataType,
} from './metadataFields.js'

test('metadata names must be lowercase identifiers', () => {
  assert.equal(metadataNameError('category'), '')
  assert.equal(metadataNameError('a1_b'), '')
  assert.ok(metadataNameError(''))
  assert.ok(metadataNameError('Name'))
  assert.ok(metadataNameError('1cat'))
  assert.ok(metadataNameError('a'.repeat(256)))
})

test('operators are constrained by metadata type', () => {
  assert.deepEqual(operatorsForMetadataType('string'), [
    'is', 'is not', 'contains', 'not contains', 'start with', 'end with',
    'empty', 'not empty', 'in', 'not in',
  ])
  assert.deepEqual(operatorsForMetadataType('number'), [
    '=', '≠', '>', '<', '≥', '≤', 'empty', 'not empty',
  ])
  assert.deepEqual(operatorsForMetadataType('time'), [
    'is', 'before', 'after', 'empty', 'not empty',
  ])
  assert.equal(defaultOperatorForType('number'), '=')
  assert.equal(defaultOperatorForType('string'), 'is')
  assert.equal(defaultOperatorForType('time'), 'is')
})

test('empty-like operators do not require a value', () => {
  assert.equal(operatorRequiresValue('empty'), false)
  assert.equal(operatorRequiresValue('not empty'), false)
  assert.equal(operatorRequiresValue('is'), true)
  assert.equal(operatorRequiresValue('='), true)
})

test('shared metadata is the name intersection across selected datasets', () => {
  assert.deepEqual(intersectMetadataByName([
    [{ id: 'a', name: 'shared', type: 'string' }, { id: 'b', name: 'only_a', type: 'string' }],
    [{ id: 'c', name: 'shared', type: 'string' }, { id: 'd', name: 'only_b', type: 'number' }],
  ]), [{ id: 'a', name: 'shared', type: 'string' }])
  assert.deepEqual(intersectMetadataByName([]), [])
  assert.deepEqual(intersectMetadataByName([[{ id: 'a', name: 'x', type: 'string' }]]), [
    { id: 'a', name: 'x', type: 'string' },
  ])
  assert.deepEqual(intersectMetadataByName([
    [{ id: 'a', name: 'x', type: 'string' }],
    [],
  ]), [])
})

test('batch merge marks fields with mixed document values', () => {
  assert.deepEqual(mergeDocumentMetadataForBatch([
    { doc_metadata: [{ id: 'm1', name: 'lang', type: 'string', value: 'zh' }] },
    { doc_metadata: [{ id: 'm1', name: 'lang', type: 'string', value: 'en' }] },
  ]), [{
    id: 'm1',
    name: 'lang',
    type: 'string',
    value: null,
    isMultipleValue: true,
  }])
  assert.deepEqual(mergeDocumentMetadataForBatch([
    { doc_metadata: [{ id: 'm1', name: 'lang', type: 'string', value: 'zh' }, { id: 'built-in', name: 'document_name', type: 'string', value: 'a' }] },
    { doc_metadata: [{ id: 'm1', name: 'lang', type: 'string', value: 'zh' }] },
  ]), [{
    id: 'm1',
    name: 'lang',
    type: 'string',
    value: 'zh',
    isMultipleValue: false,
  }])
})

test('batch payload uses partial updates per document', () => {
  assert.deepEqual(buildDocumentsMetadataBody(['d1', 'd2'], [
    { id: 'm1', name: 'lang', value: 'zh' },
  ]), {
    operation_data: [
      { document_id: 'd1', metadata_list: [{ id: 'm1', name: 'lang', value: 'zh' }], partial_update: true },
      { document_id: 'd2', metadata_list: [{ id: 'm1', name: 'lang', value: 'zh' }], partial_update: true },
    ],
  })
})
