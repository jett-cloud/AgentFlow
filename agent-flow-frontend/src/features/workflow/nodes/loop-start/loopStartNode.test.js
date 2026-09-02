import assert from 'node:assert/strict'
import test from 'node:test'

import {
  BlockEnum,
  NESTED_ELEMENT_Z_INDEX,
} from '../../model/constants.js'
import { flowToGraph, graphToFlow, makeLoopStartNode } from '../../model/dsl.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import {
  SELECTABLE_BLOCKS,
  canConnectAsSource,
  canConnectAsTarget,
  getDefaultNodeData,
} from '../../model/nodeMeta.js'
import { getNodePresentation } from '../../model/nodePresentation.js'

test('loop start uses the official virtual-node contract', () => {
  assert.deepEqual(getDefaultNodeData(BlockEnum.LoopStart), {
    type: BlockEnum.LoopStart,
    title: '',
    desc: '',
    isInLoop: true,
  })

  assert.deepEqual(makeLoopStartNode('loop-1'), {
    id: 'loop-1start',
    type: BlockEnum.LoopStart,
    position: { x: 24, y: 68 },
    zIndex: NESTED_ELEMENT_Z_INDEX,
    parentNode: 'loop-1',
    extent: 'parent',
    selectable: false,
    draggable: false,
    data: {
      type: BlockEnum.LoopStart,
      title: '',
      desc: '',
      isInLoop: true,
    },
  })
})

test('loop start is source-only and unavailable in ordinary node menus', () => {
  assert.equal(canConnectAsTarget(BlockEnum.LoopStart), false)
  assert.equal(canConnectAsSource(BlockEnum.LoopStart), true)
  assert.equal(SELECTABLE_BLOCKS.includes(BlockEnum.LoopStart), false)
  assert.deepEqual(getNodeOutputBranches({ type: BlockEnum.LoopStart }), [
    { id: 'source', name: '', kind: 'normal' },
  ])
  assert.deepEqual(getNodePresentation(BlockEnum.LoopStart), {
    kind: 'internal-start',
    showEntryShell: false,
    showTargetHandle: false,
    showSourceHandle: true,
    sourceHandleMode: 'header',
  })
})

test('loop start round-trips as a non-editable custom child node', () => {
  const flow = graphToFlow({
    nodes: [
      {
        id: 'loop-1',
        type: 'custom',
        position: { x: 100, y: 100 },
        data: { type: BlockEnum.Loop, title: 'Loop', start_node_id: 'loop-1start' },
      },
      {
        id: 'loop-1start',
        type: 'custom-loop-start',
        parentId: 'loop-1',
        position: { x: 24, y: 68 },
        data: { type: BlockEnum.LoopStart },
      },
    ],
    edges: [],
  })

  const start = flow.nodes.find(node => node.id === 'loop-1start')
  assert.equal(start.type, BlockEnum.LoopStart)
  assert.equal(start.parentNode, 'loop-1')
  assert.equal(start.extent, 'parent')
  assert.equal(start.selectable, false)
  assert.equal(start.draggable, false)
  assert.equal(start.data.title, '')
  assert.equal(start.data.desc, '')
  assert.equal(start.data.isInLoop, true)

  const graph = flowToGraph(flow.nodes, flow.edges)
  const exportedStart = graph.nodes.find(node => node.id === 'loop-1start')
  assert.equal(exportedStart.type, 'custom-loop-start')
  assert.equal(exportedStart.parentId, 'loop-1')
  assert.deepEqual(exportedStart.data, {
    type: BlockEnum.LoopStart,
    title: '',
    desc: '',
    isInLoop: true,
  })
})

test('legacy first-child start ids migrate to a unique loop marker and edge', () => {
  const flow = graphToFlow({
    nodes: [
      {
        id: 'loop-1',
        type: 'custom',
        position: { x: 100, y: 100 },
        data: { type: BlockEnum.Loop, title: 'Loop', start_node_id: 'first-child' },
      },
      {
        id: 'first-child',
        type: 'custom',
        parentId: 'loop-1',
        position: { x: 120, y: 68 },
        data: { type: BlockEnum.Code, title: 'Code' },
      },
    ],
    edges: [],
  })

  const loop = flow.nodes.find(node => node.id === 'loop-1')
  const firstChild = flow.nodes.find(node => node.id === 'first-child')
  const starts = flow.nodes.filter(node => node.data.type === BlockEnum.LoopStart)
  assert.equal(new Set(flow.nodes.map(node => node.id)).size, flow.nodes.length)
  assert.equal(firstChild.data.type, BlockEnum.Code)
  assert.equal(starts.length, 1)
  assert.notEqual(starts[0].id, 'first-child')
  assert.equal(starts[0].parentNode, 'loop-1')
  assert.equal(loop.data.start_node_id, starts[0].id)
  assert.ok(loop.data._children.some(child => child.nodeId === starts[0].id))
  assert.ok(loop.data._children.some(child => child.nodeId === 'first-child'))
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
