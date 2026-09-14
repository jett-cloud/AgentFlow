import assert from 'node:assert/strict'
import test from 'node:test'
import { graphToFlow } from '../../model/dsl.js'
import { canConnectAsSource, canConnectAsTarget, SELECTABLE_BLOCKS } from '../../model/nodeMeta.js'

test('import preserves a valid non-default loop start id', () => {
  const flow = graphToFlow({
    nodes: [
      { id: 'loop-1', type: 'custom', data: { type: 'loop', start_node_id: 'entry_uuid_1' } },
      { id: 'entry_uuid_1', type: 'custom-loop-start', parentId: 'loop-1', data: { type: 'loop-start' } },
      { id: 'child', type: 'custom', parentId: 'loop-1', data: { type: 'code' } },
    ],
    edges: [{ source: 'entry_uuid_1', sourceHandle: 'source', target: 'child', targetHandle: 'target' }],
  })
  assert.equal(flow.nodes.find(node => node.id === 'loop-1').data.start_node_id, 'entry_uuid_1')
})

test('a shared loop-start is not reparented onto a later container', () => {
  const flow = graphToFlow({
    nodes: [
      { id: 'loop-a', type: 'custom', data: { type: 'loop', start_node_id: 'shared-start' } },
      { id: 'loop-b', type: 'custom', data: { type: 'loop', start_node_id: 'shared-start' } },
      { id: 'shared-start', type: 'custom-loop-start', parentId: 'loop-a', data: { type: 'loop-start' } },
      { id: 'child-a', type: 'custom', parentId: 'loop-a', data: { type: 'code' } },
      { id: 'child-b', type: 'custom', parentId: 'loop-b', data: { type: 'code' } },
    ],
    edges: [],
  })
  const loopA = flow.nodes.find(node => node.id === 'loop-a')
  const loopB = flow.nodes.find(node => node.id === 'loop-b')
  const shared = flow.nodes.find(node => node.id === 'shared-start')
  assert.equal(shared.parentNode || shared.parentId, 'loop-a')
  assert.equal(loopA.data.start_node_id, 'shared-start')
  assert.notEqual(loopB.data.start_node_id, 'shared-start')
  const startB = flow.nodes.find(node => node.id === loopB.data.start_node_id)
  assert.equal(startB?.data?.type, 'loop-start')
  assert.equal(startB.parentNode || startB.parentId, 'loop-b')
})

test('loop-start stays source-only and hidden from selectable blocks', () => {
  assert.equal(canConnectAsTarget('loop-start'), false)
  assert.equal(canConnectAsSource('loop-start'), true)
  assert.equal(SELECTABLE_BLOCKS.includes('loop-start'), false)
})
