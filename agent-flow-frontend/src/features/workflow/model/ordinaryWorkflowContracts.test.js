import assert from 'node:assert/strict'
import test from 'node:test'

import { flowToGraph, graphToFlow } from './dsl.js'
import { BlockEnum } from './constants.js'
import { CONTAINER_SELECTABLE_BLOCKS } from './nodeMeta.js'
import { buildWorkflowChecklist } from './checklist.js'

test('container allows Human Input and excludes unsupported node types', () => {
  assert.equal(CONTAINER_SELECTABLE_BLOCKS.includes(BlockEnum.HumanInput), true)
  assert.equal(CONTAINER_SELECTABLE_BLOCKS.includes(BlockEnum.Iteration), false)
  assert.equal(CONTAINER_SELECTABLE_BLOCKS.includes(BlockEnum.Loop), false)
  assert.equal(CONTAINER_SELECTABLE_BLOCKS.includes(BlockEnum.End), false)
  assert.equal(CONTAINER_SELECTABLE_BLOCKS.includes(BlockEnum.DataSource), false)
  assert.equal(CONTAINER_SELECTABLE_BLOCKS.includes(BlockEnum.KnowledgeBase), false)
  assert.equal(CONTAINER_SELECTABLE_BLOCKS.includes(BlockEnum.LoopEnd), true)
})

test('Loop with Human Input preserves container ownership and exact action handles', () => {
  const source = {
    nodes: [
      { id: 'start', type: 'custom', position: { x: 0, y: 0 }, data: { type: 'start', title: '开始', variables: [] } },
      { id: 'loop-1', type: 'custom', position: { x: 200, y: 0 }, width: 640, height: 340, data: { type: 'loop', title: '循环', start_node_id: 'loop-1start', loop_count: 10, loop_variables: [], break_conditions: [] } },
      { id: 'loop-1start', type: 'custom-loop-start', parentId: 'loop-1', position: { x: 24, y: 68 }, data: { type: 'loop-start', title: '循环开始' } },
      { id: 'human', type: 'custom', parentId: 'loop-1', position: { x: 180, y: 68 }, data: { type: 'human-input', title: '人工介入', delivery_methods: [{ id: '6ba7b810-9dad-41d1-80b4-00c04fd430c8', type: 'webapp', enabled: true }], user_actions: [{ id: 'approve', title: '同意', button_style: 'primary' }], form_content: '审批', inputs: [], timeout: 3, timeout_unit: 'day' } },
      { id: 'loop-end', type: 'custom-simple', parentId: 'loop-1', position: { x: 420, y: 68 }, data: { type: 'loop-end', title: '退出循环' } },
    ],
    edges: [
      { id: 'start-loop', source: 'start', target: 'loop-1', sourceHandle: 'source', targetHandle: 'target' },
      { id: 'loopstart-human', source: 'loop-1start', target: 'human', sourceHandle: 'source', targetHandle: 'target' },
      { id: 'approve-edge', source: 'human', target: 'loop-end', sourceHandle: 'approve', targetHandle: 'target' },
      { id: 'timeout-edge', source: 'human', target: 'loop-end', sourceHandle: '__timeout', targetHandle: 'target' },
    ],
  }

  const flow = graphToFlow(source)
  const human = flow.nodes.find(node => node.id === 'human')
  assert.equal(human.parentNode, 'loop-1')

  const roundTrip = flowToGraph(flow.nodes, flow.edges)
  assert.equal(roundTrip.nodes.find(node => node.id === 'loop-1').data.start_node_id, 'loop-1start')
  assert.equal(roundTrip.nodes.find(node => node.id === 'human').parentId, 'loop-1')
  assert.equal(roundTrip.edges.find(edge => edge.id === 'approve-edge').sourceHandle, 'approve')
  assert.equal(roundTrip.edges.find(edge => edge.id === 'timeout-edge').sourceHandle, '__timeout')
})

test('ordinary workflow round-trip preserves Human Input inside Iteration contracts', () => {
  const graph = {
    nodes: [
      { id: 'start', type: 'custom', position: { x: 0, y: 0 }, data: { type: 'start', title: '开始', variables: [] } },
      { id: 'iter-1', type: 'custom', position: { x: 200, y: 0 }, width: 640, height: 340, data: { type: 'iteration', title: '迭代', start_node_id: 'iter-1start', iterator_selector: ['sys', 'files'], output_selector: ['human', 'comment'], output_type: 'array[string]', is_parallel: false, parallel_nums: 10, error_handle_mode: 'terminated', flatten_output: true } },
      { id: 'iter-1start', type: 'custom-iteration-start', parentId: 'iter-1', position: { x: 24, y: 68 }, data: { type: 'iteration-start', title: '迭代开始' } },
      { id: 'human', type: 'custom', parentId: 'iter-1', position: { x: 190, y: 68 }, data: { type: 'human-input', title: '人工介入', delivery_methods: [{ id: '6ba7b810-9dad-41d1-80b4-00c04fd430c8', type: 'webapp', enabled: true }], user_actions: [{ id: 'approve', title: '同意', button_style: 'primary' }], form_content: '请确认', inputs: [{ type: 'paragraph', output_variable_name: 'comment', default: { type: 'constant', selector: [], value: '' } }], timeout: 3, timeout_unit: 'day' } },
      { id: 'note', type: 'custom-note', parentId: 'iter-1', position: { x: 420, y: 68 }, data: { type: 'note', title: '分支终点', text: '' } },
      { id: 'end', type: 'custom', position: { x: 900, y: 0 }, data: { type: 'end', title: '结束', outputs: [{ variable: 'result', value_selector: ['iter-1', 'output'], value_type: 'array[string]' }] } },
    ],
    edges: [
      { id: 'start-iter', source: 'start', target: 'iter-1', sourceHandle: 'source', targetHandle: 'target' },
      { id: 'iter-end', source: 'iter-1', target: 'end', sourceHandle: 'source', targetHandle: 'target' },
      { id: 'iterstart-human', source: 'iter-1start', target: 'human', sourceHandle: 'source', targetHandle: 'target' },
      { id: 'approve-note', source: 'human', target: 'note', sourceHandle: 'approve', targetHandle: 'target' },
      { id: 'timeout-note', source: 'human', target: 'note', sourceHandle: '__timeout', targetHandle: 'target' },
    ],
  }

  const flow = graphToFlow(graph)
  const exported = flowToGraph(flow.nodes, flow.edges)
  const iteration = exported.nodes.find(node => node.id === 'iter-1')
  const human = exported.nodes.find(node => node.id === 'human')
  assert.equal(iteration.data.start_node_id, 'iter-1start')
  assert.deepEqual(iteration.data.output_selector, ['human', 'comment'])
  assert.equal(iteration.data.flatten_output, true)
  assert.equal(human.parentId, 'iter-1')
  assert.deepEqual(human.data.inputs[0], {
    type: 'paragraph',
    output_variable_name: 'comment',
    default: { type: 'constant', selector: [], value: '' },
  })
  assert.equal(exported.edges.find(edge => edge.id === 'approve-note').sourceHandle, 'approve')
  assert.equal(exported.edges.find(edge => edge.id === 'timeout-note').sourceHandle, '__timeout')

  const issues = buildWorkflowChecklist({ nodes: flow.nodes, edges: flow.edges })
  const contractPrefixes = ['human-', 'iteration-variable-', 'iteration-input-type-', 'iteration-output-', 'iteration-parallel-']
  assert.deepEqual(issues.filter(issue => contractPrefixes.some(prefix => issue.id.startsWith(prefix))), [])
})
