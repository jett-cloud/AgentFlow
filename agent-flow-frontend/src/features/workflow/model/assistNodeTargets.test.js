import assert from 'node:assert/strict'
import test from 'node:test'
import { mergeAssistTargetIds, selectedAssistNodeIds } from './assistNodeTargets.js'

test('selectedAssistNodeIds returns all selected nodes in canvas order', () => {
  const nodes = [{ id: 'a', selected: true }, { id: 'b' }, { id: 'c', selected: true }]
  assert.deepEqual(selectedAssistNodeIds(nodes, 'c'), ['a', 'c'])
})

test('selectedAssistNodeIds falls back to clicked node', () => {
  assert.deepEqual(selectedAssistNodeIds([{ id: 'a' }], 'a'), ['a'])
})

test('mergeAssistTargetIds deduplicates and removes deleted nodes', () => {
  assert.deepEqual(mergeAssistTargetIds(['a', 'deleted'], ['a', 'b'], new Set(['a', 'b'])), ['a', 'b'])
})
