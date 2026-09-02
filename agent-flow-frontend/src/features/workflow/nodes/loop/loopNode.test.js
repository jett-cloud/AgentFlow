import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { LOOP_DEFAULTS, normalizeLoopData } from './loopNode.js'

test('new loop nodes use Dify defaults and create an internal start node', () => {
  const { newNode, extraNodes } = generateNewNode({ type: 'loop', id: 'loop-1' })
  assert.deepEqual(LOOP_DEFAULTS, {
    start_node_id: '', loop_count: 10, loop_variables: [], break_conditions: [], logical_operator: 'and', _children: [],
  })
  assert.equal(newNode.data.start_node_id, 'loop-1start')
  assert.equal(extraNodes[0].data.type, 'loop-start')
  assert.equal(extraNodes[0].parentNode, 'loop-1')
})

test('loop normalization migrates max_iterations and preserves unknown fields', () => {
  const normalized = normalizeLoopData({ max_iterations: 7, logical_operator: 'or', future: true })
  assert.equal(normalized.loop_count, 7)
  assert.equal(normalized.logical_operator, 'or')
  assert.equal(normalized.max_iterations, undefined)
  assert.equal(normalized.future, true)
})

test('loop DSL round-trip keeps variables, conditions, and unknown fields', () => {
  const flow = graphToFlow({ nodes: [{ id: 'loop-1', type: 'custom', data: {
    type: 'loop', start_node_id: 'loop-1start', loop_count: 4,
    loop_variables: [{ id: 'v1', label: 'count', var_type: 'number', value_type: 'constant', value: 0 }],
    break_conditions: [{ id: 'c1', variable_selector: ['loop-1', 'count'], comparison_operator: '≥', value: '3' }],
    logical_operator: 'and', future: 1,
  } }], edges: [] })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.loop_variables[0].label, 'count')
  assert.equal(exported.nodes[0].data.break_conditions[0].comparison_operator, '≥')
  assert.equal(exported.nodes[0].data.future, 1)
})

test('checklist rejects invalid loop count, unnamed variables, and incomplete conditions', () => {
  const nodes = [{ id: 'start', data: { type: 'start' } }, { id: 'loop-1', data: {
    type: 'loop', title: '循环', loop_count: 0,
    loop_variables: [{ id: 'v1', label: '', var_type: 'number', value_type: 'constant', value: 0 }],
    break_conditions: [{ id: 'c1', variable_selector: [], comparison_operator: '', value: '' }],
  } }]
  const issues = buildWorkflowChecklist({ nodes, edges: [{ source: 'start', target: 'loop-1' }] })
  assert.ok(issues.some(issue => issue.id === 'loop-count-loop-1'))
  assert.ok(issues.some(issue => issue.id === 'loop-variable-loop-1'))
  assert.ok(issues.some(issue => issue.id === 'loop-condition-loop-1'))
})
