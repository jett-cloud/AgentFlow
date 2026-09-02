import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { QUESTION_CLASSIFIER_DEFAULTS, isQuestionClassifierInput, normalizeQuestionClassifierData } from './questionClassifierNode.js'

test('new question classifier nodes use Dify defaults', () => {
  const { newNode } = generateNewNode({ type: 'question-classifier', id: 'qc-1' })
  assert.deepEqual(newNode.data, { type: 'question-classifier', title: '问题分类器', ...QUESTION_CLASSIFIER_DEFAULTS })
})

test('query input accepts text variables only', () => {
  assert.equal(isQuestionClassifierInput({ type: 'string' }), true)
  assert.equal(isQuestionClassifierInput({ type: 'number' }), false)
  assert.equal(isQuestionClassifierInput({ type: 'arrayString' }), false)
})

test('normalization preserves class ids, exact Handles, and unknown fields', () => {
  const normalized = normalizeQuestionClassifierData({ classes: [{ id: 'refund', name: '退款' }, { id: 'sales', name: '售前' }], future: true })
  assert.deepEqual(normalized._targetBranches, [{ id: 'refund', name: '退款' }, { id: 'sales', name: '售前' }])
  assert.deepEqual(getNodeOutputBranches({ type: 'question-classifier', ...normalized }).map(branch => branch.id), ['refund', 'sales'])
  assert.equal(normalized.future, true)
})

test('DSL round-trip and checklist keep official data and reject incomplete configuration', () => {
  const flow = graphToFlow({ nodes: [{ id: 'qc-1', type: 'custom', data: { type: 'question-classifier', query_variable_selector: [], model: {}, classes: [{ id: '1', name: '' }, { id: '2', name: '' }], future: 1 } }], edges: [] })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.future, 1)
  const issues = buildWorkflowChecklist({ nodes: [{ id: 'start', data: { type: 'start' } }, { id: 'qc-1', data: exported.nodes[0].data }], edges: [{ source: 'start', target: 'qc-1' }] })
  assert.ok(issues.some(issue => issue.id === 'qc-query-qc-1'))
  assert.ok(issues.some(issue => issue.id === 'qc-classes-qc-1'))
})
