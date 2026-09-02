import test from 'node:test'
import assert from 'node:assert/strict'
import {
  isPreviewableAssistGraph,
  nextConversationIdAfterDelete,
  normalizeConversationTitle,
} from './workflowAssistUx.js'

test('a candidate is previewable only when it has at least one node', () => {
  assert.equal(isPreviewableAssistGraph(null), false)
  assert.equal(isPreviewableAssistGraph({ nodes: [], edges: [] }), false)
  assert.equal(isPreviewableAssistGraph({ nodes: [{ id: 'start' }] }), true)
})

test('deleting the current conversation selects the next remaining one', () => {
  const conversations = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]
  assert.equal(nextConversationIdAfterDelete(conversations, 'a', 'a'), 'b')
  assert.equal(nextConversationIdAfterDelete(conversations, 'c', 'c'), 'a')
})

test('deleting a non-current conversation leaves the current selection', () => {
  const conversations = [{ id: 'a' }, { id: 'b' }]
  assert.equal(nextConversationIdAfterDelete(conversations, 'b', 'a'), 'a')
})

test('deleting the last conversation asks for a new empty conversation', () => {
  assert.equal(nextConversationIdAfterDelete([{ id: 'only' }], 'only', 'only'), null)
})

test('conversation titles are trimmed and capped before save', () => {
  assert.equal(normalizeConversationTitle('  Invoice review  '), 'Invoice review')
  assert.equal(normalizeConversationTitle('   '), '')
  assert.equal(normalizeConversationTitle('x'.repeat(300)), 'x'.repeat(255))
})
