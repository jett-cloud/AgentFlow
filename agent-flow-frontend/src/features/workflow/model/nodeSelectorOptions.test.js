import assert from 'node:assert/strict'
import test from 'node:test'

import { getSelectableBlocksForDirection } from './nodeMeta.js'

const choices = ['llm', 'start', 'answer', 'end']

test('before selectors exclude terminal nodes that cannot be predecessors', () => {
  assert.deepEqual(getSelectableBlocksForDirection(choices, 'before'), ['llm', 'start', 'answer'])
})

test('after selectors exclude entry nodes that cannot be successors', () => {
  assert.deepEqual(getSelectableBlocksForDirection(choices, 'after'), ['llm', 'answer', 'end'])
})

test('edge insertion requires both source and target connection capabilities', () => {
  assert.deepEqual(getSelectableBlocksForDirection(choices, 'insert'), ['llm', 'answer'])
  assert.deepEqual(getSelectableBlocksForDirection(choices, 'free'), choices)
})
