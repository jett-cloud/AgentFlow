import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import { HUMAN_INPUT_DEFAULTS, normalizeHumanInputData } from './humanInputNode.js'

test('new human-input nodes use official empty defaults', () => {
  const { newNode } = generateNewNode({ type: 'human-input', id: 'human-1' })
  assert.deepEqual(newNode.data, { type: 'human-input', title: '人工介入', ...HUMAN_INPUT_DEFAULTS })
})

test('normalization migrates legacy delivery strings and preserves unknown fields', () => {
  const normalized = normalizeHumanInputData({ delivery_methods: ['web_app', 'email'], prompt: '确认', future: true })
  assert.deepEqual(normalized.delivery_methods.map(item => [item.type, item.enabled]), [['webapp', true], ['email', true]])
  assert.equal(normalized.form_content, '确认')
  assert.equal(normalized.prompt, undefined)
  assert.equal(normalized.future, true)
})

test('actions expose exact Handles and form fields become outputs', () => {
  const data = normalizeHumanInputData({
    user_actions: [{ id: 'approve', title: '同意', button_style: 'primary' }],
    inputs: [{ type: 'paragraph', output_variable_name: 'comment', default: { type: 'constant', selector: [], value: '' } }],
  })
  assert.deepEqual(getNodeOutputBranches({ type: 'human-input', ...data }).map(branch => branch.id), ['approve', '__timeout'])
  const outputs = getNodeOutputVars({ data: { type: 'human-input', ...data } })
  assert.ok(outputs.some(item => item.variable === 'comment' && item.type === 'string'))
  assert.ok(outputs.some(item => item.variable === '__action_id'))
})

test('DSL round-trip and checklist reject missing delivery and actions', () => {
  const flow = graphToFlow({ nodes: [{ id: 'human-1', type: 'custom', data: { type: 'human-input', delivery_methods: [], user_actions: [], form_content: '', inputs: [], timeout: 3, timeout_unit: 'day', future: 1 } }], edges: [] })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.future, 1)
  const issues = buildWorkflowChecklist({ nodes: [{ id: 'start', data: { type: 'start' } }, { id: 'human-1', data: exported.nodes[0].data }], edges: [{ source: 'start', target: 'human-1' }] })
  assert.ok(issues.some(issue => issue.id === 'human-delivery-human-1'))
  assert.ok(issues.some(issue => issue.id === 'human-actions-human-1'))
})
