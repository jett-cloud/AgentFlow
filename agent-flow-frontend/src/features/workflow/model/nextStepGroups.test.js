import assert from 'node:assert/strict'
import test from 'node:test'

import { getNextStepGroups } from './nextStepGroups.js'

test('groups classifier successors by exact source Handle', () => {
  const groups = getNextStepGroups({
    nodeId: 'classifier',
    nodeData: {
      type: 'question-classifier',
      classes: [{ id: 'a' }, { id: 'b' }],
    },
    nodes: [
      { id: 'one', data: { type: 'llm', title: 'One' } },
      { id: 'two', data: { type: 'code', title: 'Two' } },
    ],
    edges: [
      { source: 'classifier', sourceHandle: 'a', target: 'one' },
      { source: 'classifier', sourceHandle: 'b', target: 'two' },
    ],
  })

  assert.deepEqual(groups.map(group => [
    group.id,
    group.name,
    group.nextNodes.map(node => node.id),
  ]), [
    ['a', 'Class 1', ['one']],
    ['b', 'Class 2', ['two']],
  ])
})

test('keeps successor edge order and ignores missing target nodes', () => {
  const groups = getNextStepGroups({
    nodeId: 'llm',
    nodeData: { type: 'llm' },
    nodes: [{ id: 'one', data: {} }, { id: 'two', data: {} }],
    edges: [
      { source: 'llm', sourceHandle: 'source', target: 'two' },
      { source: 'llm', sourceHandle: 'source', target: 'missing' },
      { source: 'llm', target: 'one' },
    ],
  })

  assert.deepEqual(groups[0].nextNodes.map(node => node.id), ['two', 'one'])
})

test('does not leak edges between failure and normal branches', () => {
  const groups = getNextStepGroups({
    nodeId: 'code',
    nodeData: { type: 'code', error_handle_mode: 'fail-branch' },
    nodes: [
      { id: 'ok', data: {} },
      { id: 'failed', data: {} },
    ],
    edges: [
      { source: 'code', sourceHandle: 'source', target: 'ok' },
      { source: 'code', sourceHandle: 'fail-branch', target: 'failed' },
    ],
  })

  assert.deepEqual(groups.map(group => [group.id, group.nextNodes[0]?.id]), [
    ['source', 'ok'],
    ['fail-branch', 'failed'],
  ])
})
