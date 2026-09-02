import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { ITERATION_DEFAULTS, isIterationArrayVariable, normalizeIterationData } from './iterationNode.js'

test('new iteration nodes use official container fields and internal start', () => {
  const { newNode, extraNodes } = generateNewNode({ type: 'iteration', id: 'iter-1' })
  assert.deepEqual(ITERATION_DEFAULTS, { start_node_id: '', iterator_selector: [], iterator_input_type: 'array', output_selector: [], output_type: 'array', is_parallel: false, parallel_nums: 10, error_handle_mode: 'terminated', flatten_output: false, _children: [] })
  assert.equal(newNode.data.start_node_id, 'iter-1start')
  assert.equal(extraNodes[0].parentNode, 'iter-1')
})

test('iteration normalization preserves unknown fields and clamps parallelism', () => {
  const data = normalizeIterationData({ iterator_selector: ['start', 'items'], parallel_nums: 99, future: true })
  assert.deepEqual(data.iterator_selector, ['start', 'items'])
  assert.equal(data.parallel_nums, 10)
  assert.equal(data.future, true)
  assert.equal(isIterationArrayVariable({ type: 'arrayFile' }), true)
  assert.equal(isIterationArrayVariable({ type: 'string' }), false)
})

test('iteration DSL round-trip keeps container fields and children', () => {
  const flow = graphToFlow({ nodes: [{ id: 'iter-1', type: 'custom', data: { type: 'iteration', start_node_id: 'iter-1start', iterator_selector: ['start', 'items'], output_selector: ['child', 'text'], flatten_output: true, _children: [{ nodeId: 'child' }], future: 1 } }], edges: [] })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.deepEqual(exported.nodes[0].data.iterator_selector, ['start', 'items'])
  assert.equal(exported.nodes[0].data.flatten_output, true)
  assert.equal(exported.nodes[0].data.future, 1)
})

test('checklist requires an iteration array input and valid parallel count', () => {
  const nodes = [{ id: 'start', data: { type: 'start' } }, { id: 'iter-1', data: { type: 'iteration', title: '迭代', iterator_selector: [], parallel_nums: 0 } }]
  const issues = buildWorkflowChecklist({ nodes, edges: [{ source: 'start', target: 'iter-1' }] })
  assert.ok(issues.some(issue => issue.id === 'iteration-variable-iter-1'))
  assert.ok(issues.some(issue => issue.id === 'iteration-parallel-iter-1'))
})
