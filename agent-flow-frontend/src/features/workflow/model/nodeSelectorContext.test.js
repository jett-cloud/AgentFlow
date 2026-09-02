import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeNodeSelectorContext } from './nodeSelectorContext.js'

test('normalizes target Handle selection into an exclusive before connection', () => {
  assert.deepEqual(normalizeNodeSelectorContext({
    direction: 'before',
    nodeId: 'target',
    targetHandle: 'target',
    edgeId: 'ignored',
  }), {
    direction: 'before',
    connection: null,
    targetConnection: { target: 'target', targetHandle: 'target' },
    edgeId: null,
    parentId: null,
  })
})

test('normalizes exact source Handle selection into an exclusive after connection', () => {
  assert.deepEqual(normalizeNodeSelectorContext({
    direction: 'after',
    nodeId: 'classifier',
    sourceHandle: 'class-a',
    edgeId: 'ignored',
  }), {
    direction: 'after',
    connection: { source: 'classifier', sourceHandle: 'class-a' },
    targetConnection: null,
    edgeId: null,
    parentId: null,
  })
})

test('keeps existing node selector callers compatible by defaulting nodeId to after', () => {
  assert.deepEqual(normalizeNodeSelectorContext({
    nodeId: 'llm',
    sourceHandle: 'source',
  }).connection, {
    source: 'llm',
    sourceHandle: 'source',
  })
})

test('keeps edge insertion and free placement mutually exclusive', () => {
  assert.deepEqual(normalizeNodeSelectorContext({ edgeId: 'edge-1' }), {
    direction: 'insert',
    connection: null,
    targetConnection: null,
    edgeId: 'edge-1',
    parentId: null,
  })
  assert.deepEqual(normalizeNodeSelectorContext({ parentId: 'loop-1' }), {
    direction: 'free',
    connection: null,
    targetConnection: null,
    edgeId: null,
    parentId: 'loop-1',
  })
})
