import assert from 'node:assert/strict'
import test from 'node:test'
import { canConnectAsSource, canConnectAsTarget, SELECTABLE_BLOCKS } from '../../model/nodeMeta.js'
import { getLoopEndValidationErrors } from './loopEndNode.js'

test('loop-end is target-only and hidden from the ordinary add menu', () => {
  assert.equal(canConnectAsSource('loop-end'), false)
  assert.equal(canConnectAsTarget('loop-end'), true)
  assert.equal(SELECTABLE_BLOCKS.includes('loop-end'), false)
})

test('loop-end ownership uses wrapper parentId not data.parentId', () => {
  const outside = {
    id: 'exit',
    data: { type: 'loop-end', loop_id: 'loop-1', parentId: 'loop-1' },
  }
  const errors = getLoopEndValidationErrors(outside, [
    { id: 'loop-1', data: { type: 'loop' } },
    outside,
  ])
  assert.ok(errors.length)

  const owned = { id: 'exit', parentId: 'loop-1', data: { type: 'loop-end', loop_id: 'loop-1' } }
  assert.deepEqual(getLoopEndValidationErrors(owned, [
    { id: 'loop-1', data: { type: 'loop' } },
    owned,
  ]), [])
})

test('loop-end requires data.loop_id to match the wrapper parent', () => {
  const missing = { id: 'exit', parentId: 'loop-1', data: { type: 'loop-end' } }
  assert.ok(getLoopEndValidationErrors(missing, [
    { id: 'loop-1', data: { type: 'loop' } },
    missing,
  ]).length)
})

test('the same loop cannot keep two loop-end nodes', () => {
  const first = { id: 'exit-1', parentId: 'loop-1', data: { type: 'loop-end', loop_id: 'loop-1' } }
  const second = { id: 'exit-2', parentId: 'loop-1', data: { type: 'loop-end', loop_id: 'loop-1' } }
  const nodes = [
    { id: 'loop-1', data: { type: 'loop' } },
    first,
    second,
  ]
  assert.ok(getLoopEndValidationErrors(first, nodes).length)
  assert.ok(getLoopEndValidationErrors(second, nodes).length)
})
