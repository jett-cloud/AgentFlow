import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getEdgesAfterNodeDataUpdate,
  getNodeOutputBranches,
  getRemovedOutputHandleIds,
} from './nodeHandleBranches.js'

test('resolves ordinary, classifier, and conditional output Handles', () => {
  assert.deepEqual(getNodeOutputBranches({ type: 'llm' }), [
    { id: 'source', name: '', kind: 'normal' },
  ])
  assert.deepEqual(getNodeOutputBranches({
    type: 'question-classifier',
    classes: [{ id: 'a', name: '账户问题' }, { id: 'b', name: '' }],
  }), [
    { id: 'a', name: '账户问题', kind: 'normal' },
    { id: 'b', name: 'Class 2', kind: 'normal' },
  ])
  assert.deepEqual(getNodeOutputBranches({
    type: 'if-else',
    cases: [{ case_id: 'true' }, { case_id: 'elif-1' }],
  }), [
    { id: 'true', name: 'CASE 1', kind: 'normal' },
    { id: 'elif-1', name: 'CASE 2', kind: 'normal' },
    { id: 'false', name: 'ELSE', kind: 'normal' },
  ])
})

test('prefers runtime branch metadata and preserves exact Handle ids', () => {
  assert.deepEqual(getNodeOutputBranches({
    type: 'question-classifier',
    _targetBranches: [
      { id: 'custom-a', name: '退款' },
      { id: 'custom-b', name: '咨询' },
    ],
    classes: [{ id: 'stale' }],
  }), [
    { id: 'custom-a', name: '退款', kind: 'normal' },
    { id: 'custom-b', name: '咨询', kind: 'normal' },
  ])
})

test('resolves human-input action, timeout, and failure Handles', () => {
  assert.deepEqual(getNodeOutputBranches({
    type: 'human-input',
    user_actions: [
      { id: 'approve', title: '满意' },
      { id: 'retry', title: '不满意' },
    ],
    timeout: 24,
  }), [
    { id: 'approve', name: '满意', kind: 'normal' },
    { id: 'retry', name: '不满意', kind: 'normal' },
    { id: '__timeout', name: 'Timeout (超时)', kind: 'normal' },
  ])
  assert.deepEqual(getNodeOutputBranches({
    type: 'human-input',
    user_actions: [{ id: 'approve', title: '同意' }],
    _targetBranches: [{ id: 'stale', name: '旧分支' }],
  }).map(item => item.id), ['approve', '__timeout'])
  assert.deepEqual(getNodeOutputBranches({
    type: 'code',
    error_strategy: 'failBranch',
  }), [
    { id: 'source', name: '', kind: 'normal' },
    { id: 'fail-branch', name: '失败', kind: 'failure' },
  ])
})

test('terminal nodes do not expose output Handles while Answer can continue', () => {
  for (const type of ['end', 'start-placeholder'])
    assert.deepEqual(getNodeOutputBranches({ type }), [])
  assert.deepEqual(getNodeOutputBranches({ type: 'answer' }), [
    { id: 'source', name: '', kind: 'normal' },
  ])
})

test('reports exact Handles removed by a branch edit', () => {
  assert.deepEqual(getRemovedOutputHandleIds(
    { type: 'question-classifier', classes: [{ id: 'a' }, { id: 'b' }] },
    { type: 'question-classifier', classes: [{ id: 'a' }] },
  ), ['b'])
  assert.deepEqual(getRemovedOutputHandleIds(
    { type: 'code', error_handle_mode: 'fail-branch' },
    { type: 'code', error_handle_mode: 'terminated' },
  ), ['fail-branch'])
})

test('removes only edges whose source Handle disappeared', () => {
  const result = getEdgesAfterNodeDataUpdate({
    nodeId: 'classifier',
    previousData: {
      type: 'question-classifier',
      classes: [{ id: 'a' }, { id: 'b' }],
    },
    nextData: {
      type: 'question-classifier',
      classes: [{ id: 'a' }],
    },
    edges: [
      { id: 'a-one', source: 'classifier', sourceHandle: 'a', target: 'one' },
      { id: 'b-two', source: 'classifier', sourceHandle: 'b', target: 'two' },
      { id: 'other', source: 'one', sourceHandle: 'source', target: 'two' },
    ],
  })

  assert.deepEqual(result.removedEdgeIds, ['b-two'])
  assert.deepEqual(result.affectedTargetIds, ['two'])
  assert.deepEqual(result.edges.map(edge => edge.id), ['a-one', 'other'])
  assert.deepEqual(result.connectedSourceHandleIds, ['a'])
})

test('human-input Action rename migrates only that Handle and delete removes only that edge', () => {
  const previousData = {
    type: 'human-input',
    user_actions: [
      { id: 'approve', title: '同意' },
      { id: 'reject', title: '拒绝' },
    ],
  }
  const renamed = getEdgesAfterNodeDataUpdate({
    nodeId: 'human-1',
    previousData,
    nextData: {
      type: 'human-input',
      user_actions: [
        { id: 'accept', title: '同意' },
        { id: 'reject', title: '拒绝' },
      ],
    },
    edges: [
      { id: 'approve-end', source: 'human-1', sourceHandle: 'approve', target: 'end' },
      { id: 'reject-end', source: 'human-1', sourceHandle: 'reject', target: 'end' },
      { id: 'timeout-end', source: 'human-1', sourceHandle: '__timeout', target: 'end' },
    ],
  })
  assert.deepEqual(renamed.removedEdgeIds, [])
  assert.deepEqual(renamed.remappedEdges, [{ id: 'approve-end', sourceHandle: 'accept' }])
  assert.deepEqual(renamed.edges.filter(edge => edge.source === 'human-1').map(edge => edge.sourceHandle), ['accept', 'reject', '__timeout'])

  const deleted = getEdgesAfterNodeDataUpdate({
    nodeId: 'human-1',
    previousData,
    nextData: {
      type: 'human-input',
      user_actions: [{ id: 'approve', title: '同意' }],
    },
    edges: [
      { id: 'approve-end', source: 'human-1', sourceHandle: 'approve', target: 'end' },
      { id: 'reject-end', source: 'human-1', sourceHandle: 'reject', target: 'end' },
      { id: 'other', source: 'start', sourceHandle: 'source', target: 'human-1' },
    ],
  })
  assert.deepEqual(deleted.removedEdgeIds, ['reject-end'])
  assert.deepEqual(deleted.edges.map(edge => edge.id), ['approve-end', 'other'])
})
