import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildIterationInputPatch,
  buildIterationOutputPatch,
  deriveIterationOutputType,
  isIterationArrayVariable,
  normalizeIterationArrayType,
  normalizeIterationData,
  normalizeIterationErrorHandleMode,
} from './iterationNode.js'

test('iteration array aliases persist as canonical Dify types', () => {
  assert.equal(normalizeIterationArrayType('arrayString'), 'array[string]')
  assert.equal(normalizeIterationArrayType('arrayNumber'), 'array[number]')
  assert.equal(normalizeIterationArrayType('arrayBoolean'), 'array[boolean]')
  assert.equal(normalizeIterationArrayType('arrayObject'), 'array[object]')
  assert.equal(normalizeIterationArrayType('arrayFile'), 'array[file]')
  assert.equal(normalizeIterationArrayType('array[file]'), 'array[file]')
})

test('iteration output type follows the official aggregation mapping', () => {
  assert.equal(deriveIterationOutputType('string'), 'array[string]')
  assert.equal(deriveIterationOutputType('number'), 'array[number]')
  assert.equal(deriveIterationOutputType('object'), 'array[object]')
  assert.equal(deriveIterationOutputType('file'), 'array[file]')
  assert.equal(deriveIterationOutputType('arrayNumber'), 'array[number]')
  assert.equal(deriveIterationOutputType('boolean'), 'array[string]')
  assert.equal(deriveIterationOutputType('arrayBoolean'), 'array[string]')
})

test('iteration selector patches keep selector and derived type together', () => {
  assert.deepEqual(buildIterationInputPatch(['start', 'items'], { type: 'arrayNumber' }), {
    iterator_selector: ['start', 'items'],
    iterator_input_type: 'array[number]',
  })
  assert.deepEqual(buildIterationOutputPatch(['child', 'score'], { type: 'number' }), {
    output_selector: ['child', 'score'],
    output_type: 'array[number]',
  })
})

test('normalizeIterationData canonicalizes stored array types and keeps unknown fields', () => {
  const normalized = normalizeIterationData({
    iterator_input_type: 'arrayBoolean',
    output_type: 'arrayNumber',
    future: true,
  })
  assert.equal(normalized.iterator_input_type, 'array[boolean]')
  assert.equal(normalized.output_type, 'array[number]')
  assert.equal(normalized.future, true)
  assert.equal(isIterationArrayVariable({ type: 'array[number]' }), true)
  assert.equal(isIterationArrayVariable({ type: 'string' }), false)
})

test('normalizeIterationData keeps only official error handle modes', () => {
  assert.equal(normalizeIterationErrorHandleMode('continue-on-error'), 'continue-on-error')
  assert.equal(normalizeIterationErrorHandleMode('remove-abnormal-output'), 'remove-abnormal-output')
  assert.equal(normalizeIterationErrorHandleMode('terminated'), 'terminated')
  assert.equal(normalizeIterationErrorHandleMode('ignore'), 'terminated')
  assert.equal(normalizeIterationData({ error_handle_mode: 'explode' }).error_handle_mode, 'terminated')
  assert.equal(normalizeIterationData({ error_strategy: 'continue-on-error' }).error_handle_mode, 'continue-on-error')
})
