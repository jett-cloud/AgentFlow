import assert from 'node:assert/strict'
import test from 'node:test'
import { graphToFlow } from '../../model/dsl.js'
import { canConnectAsSource, canConnectAsTarget, SELECTABLE_BLOCKS } from '../../model/nodeMeta.js'

function validIterationGraph({ startId = 'iter-1start' } = {}) {
  return {
    nodes: [
      { id: 'iter-1', type: 'custom', data: { type: 'iteration', start_node_id: startId } },
      { id: startId, type: 'custom-iteration-start', parentId: 'iter-1', data: { type: 'iteration-start' } },
      { id: 'child', type: 'custom', parentId: 'iter-1', data: { type: 'code' } },
    ],
    edges: [{ source: startId, sourceHandle: 'source', target: 'child', targetHandle: 'target' }],
  }
}

function conflictingIterationGraph() {
  return {
    nodes: [
      { id: 'iter-1', type: 'custom', data: { type: 'iteration', start_node_id: 'business-child' } },
      { id: 'business-child', type: 'custom', parentId: 'iter-1', data: { type: 'code' } },
    ],
    edges: [],
  }
}

test('import preserves a valid non-default iteration start id', () => {
  const flow = graphToFlow(validIterationGraph({ startId: 'entry_uuid_1' }))
  assert.equal(flow.nodes.find(node => node.id === 'iter-1').data.start_node_id, 'entry_uuid_1')
})

test('a conflicting business child id is not duplicated as iteration-start', () => {
  const flow = graphToFlow(conflictingIterationGraph())
  assert.equal(new Set(flow.nodes.map(node => node.id)).size, flow.nodes.length)
  assert.equal(flow.nodes.filter(node => node.data.type === 'iteration-start').length, 1)
})

test('a shared iteration-start is not reparented onto a later container', () => {
  const flow = graphToFlow({
    nodes: [
      { id: 'iter-a', type: 'custom', data: { type: 'iteration', start_node_id: 'shared-start' } },
      { id: 'iter-b', type: 'custom', data: { type: 'iteration', start_node_id: 'shared-start' } },
      { id: 'shared-start', type: 'custom-iteration-start', parentId: 'iter-a', data: { type: 'iteration-start' } },
      { id: 'child-a', type: 'custom', parentId: 'iter-a', data: { type: 'code' } },
      { id: 'child-b', type: 'custom', parentId: 'iter-b', data: { type: 'code' } },
    ],
    edges: [],
  })
  const iterA = flow.nodes.find(node => node.id === 'iter-a')
  const iterB = flow.nodes.find(node => node.id === 'iter-b')
  const shared = flow.nodes.find(node => node.id === 'shared-start')
  const ownedByA = shared.parentNode || shared.parentId
  assert.equal(ownedByA, 'iter-a')
  assert.equal(iterA.data.start_node_id, 'shared-start')
  assert.notEqual(iterB.data.start_node_id, 'shared-start')
  const startB = flow.nodes.find(node => node.id === iterB.data.start_node_id)
  assert.equal(startB?.data?.type, 'iteration-start')
  assert.equal(startB.parentNode || startB.parentId, 'iter-b')
})

test('iteration-start stays source-only and hidden from selectable blocks', () => {
  assert.equal(canConnectAsTarget('iteration-start'), false)
  assert.equal(canConnectAsSource('iteration-start'), true)
  assert.equal(SELECTABLE_BLOCKS.includes('iteration-start'), false)
})
