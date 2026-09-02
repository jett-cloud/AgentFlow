import assert from 'node:assert/strict'
import test from 'node:test'

import { getNodeHandleAddAction } from './nodeHandleInteraction.js'

test('source Handle add action preserves the exact branch id', () => {
  assert.deepEqual(getNodeHandleAddAction({
    nodeId: 'classifier',
    type: 'source',
    handleId: 'class-a',
    label: 'Class 1',
    readOnly: false,
  }), {
    ariaLabel: '从 Class 1 添加后续节点',
    selector: {
      direction: 'after',
      nodeId: 'classifier',
      sourceHandle: 'class-a',
    },
  })
})

test('unconnected target Handle add action creates a predecessor context', () => {
  assert.deepEqual(getNodeHandleAddAction({
    nodeId: 'target',
    type: 'target',
    handleId: 'target',
    readOnly: false,
    connected: false,
  }), {
    ariaLabel: '添加前置节点',
    selector: {
      direction: 'before',
      nodeId: 'target',
      targetHandle: 'target',
    },
  })
})

test('read-only and connected target Handles do not expose add actions', () => {
  assert.equal(getNodeHandleAddAction({
    nodeId: 'target',
    type: 'target',
    handleId: 'target',
    readOnly: false,
    connected: true,
  }), null)
  assert.equal(getNodeHandleAddAction({
    nodeId: 'source',
    type: 'source',
    handleId: 'source',
    readOnly: true,
  }), null)
})
