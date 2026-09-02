import assert from 'node:assert/strict'
import test from 'node:test'

import {
  BlockEnum,
  NESTED_ELEMENT_Z_INDEX,
} from '../../model/constants.js'
import { flowToGraph, graphToFlow, makeIterationStartNode } from '../../model/dsl.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import {
  SELECTABLE_BLOCKS,
  canConnectAsSource,
  canConnectAsTarget,
  getDefaultNodeData,
} from '../../model/nodeMeta.js'
import { getNodePresentation } from '../../model/nodePresentation.js'

test('iteration start uses the official virtual-node contract', () => {
  assert.deepEqual(getDefaultNodeData(BlockEnum.IterationStart), {
    type: BlockEnum.IterationStart,
    title: '',
    desc: '',
    isInIteration: true,
  })

  assert.deepEqual(makeIterationStartNode('iteration-1'), {
    id: 'iteration-1start',
    type: BlockEnum.IterationStart,
    position: { x: 24, y: 68 },
    zIndex: NESTED_ELEMENT_Z_INDEX,
    parentNode: 'iteration-1',
    extent: 'parent',
    selectable: false,
    draggable: false,
    data: {
      type: BlockEnum.IterationStart,
      title: '',
      desc: '',
      isInIteration: true,
    },
  })
})

test('iteration start is source-only and unavailable in ordinary node menus', () => {
  assert.equal(canConnectAsTarget(BlockEnum.IterationStart), false)
  assert.equal(canConnectAsSource(BlockEnum.IterationStart), true)
  assert.equal(SELECTABLE_BLOCKS.includes(BlockEnum.IterationStart), false)
  assert.deepEqual(getNodeOutputBranches({ type: BlockEnum.IterationStart }), [
    { id: 'source', name: '', kind: 'normal' },
  ])
  assert.deepEqual(getNodePresentation(BlockEnum.IterationStart), {
    kind: 'internal-start',
    showEntryShell: false,
    showTargetHandle: false,
    showSourceHandle: true,
    sourceHandleMode: 'header',
  })
})

test('iteration start round-trips as a non-editable custom child node', () => {
  const flow = graphToFlow({
    nodes: [
      {
        id: 'iteration-1',
        type: 'custom',
        position: { x: 100, y: 100 },
        data: { type: BlockEnum.Iteration, title: 'Iteration', start_node_id: 'iteration-1start' },
      },
      {
        id: 'iteration-1start',
        type: 'custom-iteration-start',
        parentId: 'iteration-1',
        position: { x: 24, y: 68 },
        data: { type: BlockEnum.IterationStart },
      },
    ],
    edges: [],
  })

  const start = flow.nodes.find(node => node.id === 'iteration-1start')
  assert.equal(start.type, BlockEnum.IterationStart)
  assert.equal(start.parentNode, 'iteration-1')
  assert.equal(start.extent, 'parent')
  assert.equal(start.selectable, false)
  assert.equal(start.draggable, false)
  assert.equal(start.data.title, '')
  assert.equal(start.data.desc, '')
  assert.equal(start.data.isInIteration, true)

  const graph = flowToGraph(flow.nodes, flow.edges)
  const exportedStart = graph.nodes.find(node => node.id === 'iteration-1start')
  assert.equal(exportedStart.type, 'custom-iteration-start')
  assert.equal(exportedStart.parentId, 'iteration-1')
  assert.deepEqual(exportedStart.data, {
    type: BlockEnum.IterationStart,
    title: '',
    desc: '',
    isInIteration: true,
  })
})

test('legacy first-child start ids migrate to a unique iteration marker and edge', () => {
  const flow = graphToFlow({
    nodes: [
      {
        id: 'iteration-1',
        type: 'custom',
        position: { x: 100, y: 100 },
        data: { type: BlockEnum.Iteration, title: 'Iteration', start_node_id: 'first-child' },
      },
      {
        id: 'first-child',
        type: 'custom',
        parentId: 'iteration-1',
        position: { x: 120, y: 68 },
        data: { type: BlockEnum.Code, title: 'Code' },
      },
    ],
    edges: [],
  })

  const iteration = flow.nodes.find(node => node.id === 'iteration-1')
  const firstChild = flow.nodes.find(node => node.id === 'first-child')
  const starts = flow.nodes.filter(node => node.data.type === BlockEnum.IterationStart)
  assert.equal(new Set(flow.nodes.map(node => node.id)).size, flow.nodes.length)
  assert.equal(firstChild.data.type, BlockEnum.Code)
  assert.equal(starts.length, 1)
  assert.notEqual(starts[0].id, 'first-child')
  assert.equal(starts[0].parentNode, 'iteration-1')
  assert.equal(iteration.data.start_node_id, starts[0].id)
  assert.ok(iteration.data._children.some(child => child.nodeId === starts[0].id))
  assert.ok(iteration.data._children.some(child => child.nodeId === 'first-child'))
  assert.deepEqual(flow.edges.map(edge => ({
    source: edge.source,
    sourceHandle: edge.sourceHandle,
    target: edge.target,
    targetHandle: edge.targetHandle,
  })), [{
    source: starts[0].id,
    sourceHandle: 'source',
    target: 'first-child',
    targetHandle: 'target',
  }])
})
