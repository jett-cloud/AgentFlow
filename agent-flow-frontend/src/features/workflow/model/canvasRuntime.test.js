import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyContainerStartedToGraph,
  applyHistoryTracingToGraph,
  applyHumanInputRequiredToGraph,
  applyIterationNextToGraph,
  applyLoopNextToGraph,
  applyNodeFinishedToGraph,
  applyNodeRetryToGraph,
  applyNodeStartedToGraph,
  applyWorkflowFinishedToGraph,
  applyWorkflowStartedToGraph,
  buildHistoryRunView,
  clearGraphRuntime,
  computeFollowViewport,
  FAIL_BRANCH,
  getEdgeColor,
  refreshGraphRuntimeBindings,
  resolveEdgeStroke,
  resolveRunningBranchId,
} from './canvasRuntime.js'

function sampleGraph() {
  const nodes = [
    { id: 'start', data: { type: 'start', title: '开始' } },
    {
      id: 'if',
      data: { type: 'if-else', title: '条件' },
      position: { x: 300, y: 100 },
    },
    { id: 'a', data: { type: 'llm', title: 'A' }, position: { x: 600, y: 40 } },
    { id: 'b', data: { type: 'llm', title: 'B' }, position: { x: 600, y: 200 } },
  ]
  const edges = [
    { id: 'e1', source: 'start', target: 'if', sourceHandle: 'source', data: {} },
    { id: 'e2', source: 'if', target: 'a', sourceHandle: 'true', data: {} },
    { id: 'e3', source: 'if', target: 'b', sourceHandle: 'false', data: {} },
  ]
  return { nodes, edges }
}

test('getEdgeColor maps statuses to CSS vars', () => {
  assert.match(getEdgeColor('succeeded'), /success/)
  assert.match(getEdgeColor('failed'), /error/)
  assert.match(getEdgeColor('running'), /handle/)
  assert.match(getEdgeColor(), /normal/)
})

test('workflow_started dims all nodes and edges', () => {
  const { nodes, edges } = sampleGraph()
  applyWorkflowStartedToGraph(nodes, edges)
  assert.equal(nodes.every(n => n.data._waitingRun === true), true)
  assert.equal(edges.every(e => e.data._waitingRun === true), true)
  assert.equal(nodes[1].data._runningBranchId, undefined)
})

test('node_started activates taken path only after branch finish', () => {
  const { nodes, edges } = sampleGraph()
  applyWorkflowStartedToGraph(nodes, edges)

  applyNodeStartedToGraph(nodes, edges, 'start')
  assert.equal(nodes[0].data._runningStatus, 'running')
  assert.equal(nodes[0].data._waitingRun, false)

  applyNodeFinishedToGraph(nodes, edges, {
    nodeId: 'start',
    status: 'succeeded',
    nodeType: 'start',
  })
  applyNodeStartedToGraph(nodes, edges, 'if')
  assert.equal(edges[0].data._waitingRun, false)
  assert.equal(edges[0].data._targetRunningStatus, 'running')

  applyNodeFinishedToGraph(nodes, edges, {
    nodeId: 'if',
    status: 'succeeded',
    nodeType: 'if-else',
    outputs: { selected_case_id: 'true' },
  })
  assert.equal(nodes[1].data._runningBranchId, 'true')

  applyNodeStartedToGraph(nodes, edges, 'a')
  assert.equal(edges[1].data._waitingRun, false)
  assert.equal(edges[1].data._targetRunningStatus, 'running')
  // Untaken false branch stays waiting
  assert.equal(edges[2].data._waitingRun, true)
})

test('resolveRunningBranchId covers if-else / fail-branch', () => {
  assert.equal(
    resolveRunningBranchId({
      nodeType: 'if-else',
      status: 'succeeded',
      outputs: { selected_case_id: 'case-2' },
    }),
    'case-2',
  )
  assert.equal(
    resolveRunningBranchId({
      status: 'exception',
      executionMetadata: { error_strategy: FAIL_BRANCH },
    }),
    FAIL_BRANCH,
  )
})

test('clearGraphRuntime strips runtime fields', () => {
  const { nodes, edges } = sampleGraph()
  applyWorkflowStartedToGraph(nodes, edges)
  applyNodeStartedToGraph(nodes, edges, 'start')
  clearGraphRuntime(nodes, edges)
  assert.equal(nodes[0].data._runningStatus, undefined)
  assert.equal(nodes[0].data._waitingRun, undefined)
  assert.equal(edges[0].data._waitingRun, undefined)
})

test('refreshGraphRuntimeBindings replaces data refs for Vue Flow', () => {
  const { nodes, edges } = sampleGraph()
  applyWorkflowStartedToGraph(nodes, edges)
  const nodeData = nodes[0].data
  const edgeData = edges[0].data
  refreshGraphRuntimeBindings(nodes, edges)
  assert.notEqual(nodes[0].data, nodeData)
  assert.notEqual(edges[0].data, edgeData)
  assert.equal(nodes[0].data._waitingRun, true)
})

test('computeFollowViewport centers node with panel offset', () => {
  const vp = computeFollowViewport({
    position: { x: 100, y: 50 },
    width: 240,
    height: 100,
    zoom: 1,
    clientWidth: 1400,
    clientHeight: 800,
    panelOffset: 400,
  })
  assert.equal(vp.x, (1400 - 400 - 240) / 2 - 100)
  assert.equal(vp.y, (800 - 100) / 2 - 50)
  assert.equal(vp.zoom, 1)
})

test('resolveEdgeStroke prefers running/selected colors', () => {
  assert.match(resolveEdgeStroke({ selected: true }), /handle/)
  assert.match(resolveEdgeStroke({
    sourceRunningStatus: 'succeeded',
    targetRunningStatus: 'running',
  }), /handle/)
  assert.match(resolveEdgeStroke({
    sourceRunningStatus: 'succeeded',
    targetRunningStatus: 'succeeded',
  }), /success/)
})

test('iteration/loop container runtime fields and child waiting', () => {
  const nodes = [
    { id: 'iter', data: { type: 'iteration', title: '迭代' }, position: { x: 0, y: 0 } },
    { id: 'child', parentNode: 'loop-1', data: { type: 'llm', title: '子' } },
    { id: 'loop-1', data: { type: 'loop', title: '循环' }, position: { x: 100, y: 0 } },
  ]
  const edges = [
    { id: 'e1', source: 'start', target: 'iter', sourceHandle: 'source', data: {} },
  ]
  nodes.unshift({ id: 'start', data: { type: 'start', _runningStatus: 'succeeded' } })

  applyContainerStartedToGraph(nodes, edges, { nodeId: 'iter', iterationLength: 3 })
  assert.equal(nodes.find(n => n.id === 'iter').data._iterationLength, 3)
  assert.equal(nodes.find(n => n.id === 'iter').data._runningStatus, 'running')
  assert.equal(edges[0].data._waitingRun, false)

  applyIterationNextToGraph(nodes, 'iter', 2)
  assert.equal(nodes.find(n => n.id === 'iter').data._iterationIndex, 2)

  applyContainerStartedToGraph(nodes, edges, { nodeId: 'loop-1', loopLength: 5 })
  applyLoopNextToGraph(nodes, { nodeId: 'loop-1', loopIndex: 2 })
  assert.equal(nodes.find(n => n.id === 'loop-1').data._loopIndex, 2)
  const child = nodes.find(n => n.id === 'child')
  assert.equal(child.data._waitingRun, true)
  assert.equal(child.data._runningStatus, 'waiting')

  applyNodeRetryToGraph(nodes, { nodeId: 'child', retryIndex: 2 })
  assert.equal(child.data._retryIndex, 2)

  applyHumanInputRequiredToGraph(nodes, 'child')
  assert.equal(child.data._runningStatus, 'paused')
})

test('applyHistoryTracingToGraph replays statuses and taken branch', () => {
  const { nodes, edges } = sampleGraph()
  applyHistoryTracingToGraph(nodes, edges, [
    { nodeId: 'start', status: 'succeeded', nodeType: 'start', index: 0 },
    {
      nodeId: 'if',
      status: 'succeeded',
      nodeType: 'if-else',
      outputs: { selected_case_id: 'true' },
      index: 1,
    },
    { nodeId: 'a', status: 'failed', nodeType: 'llm', index: 2 },
  ])
  assert.equal(nodes.find(n => n.id === 'start').data._runningStatus, 'succeeded')
  assert.equal(nodes.find(n => n.id === 'if').data._runningBranchId, 'true')
  assert.equal(nodes.find(n => n.id === 'a').data._runningStatus, 'failed')
  assert.equal(nodes.find(n => n.id === 'b').data._waitingRun, true)
  assert.equal(edges.find(e => e.id === 'e2').data._waitingRun, false)
})

test('buildHistoryRunView extracts result text from outputs', () => {
  const view = buildHistoryRunView({
    id: 'r1',
    status: 'succeeded',
    outputs: { text: 'hello' },
    total_tokens: 12,
  })
  assert.equal(view.resultText, 'hello')
  assert.equal(view.status, 'succeeded')
  assert.equal(view.id, 'r1')
})

test('applyWorkflowFinishedToGraph finalizes running nodes but keeps waiting path', () => {
  const { nodes, edges } = sampleGraph()
  applyWorkflowStartedToGraph(nodes, edges)
  applyNodeStartedToGraph(nodes, edges, 'start')
  applyNodeFinishedToGraph(nodes, edges, { nodeId: 'start', status: 'succeeded', nodeType: 'start' })
  applyNodeStartedToGraph(nodes, edges, 'if')
  // Simulate stream ending while if-else still running.
  applyWorkflowFinishedToGraph(nodes, edges, { status: 'failed' })
  assert.equal(nodes.find(n => n.id === 'if').data._runningStatus, 'failed')
  assert.equal(nodes.find(n => n.id === 'if').data._waitingRun, false)
  assert.equal(nodes.find(n => n.id === 'start').data._runningStatus, 'succeeded')
  assert.equal(nodes.find(n => n.id === 'a').data._waitingRun, true)
  assert.equal(nodes.find(n => n.id === 'b').data._waitingRun, true)
})
