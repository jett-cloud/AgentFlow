import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { IF_ELSE_DEFAULTS, getIfElseOperators, normalizeIfElseData } from './ifElseNode.js'

test('new if-else nodes use Dify defaults without invented conditions', () => {
  const { newNode } = generateNewNode({ type: 'if-else', id: 'if-1' })
  assert.deepEqual(IF_ELSE_DEFAULTS, {
    _targetBranches: [{ id: 'true', name: 'IF' }, { id: 'false', name: 'ELSE' }],
    cases: [{ case_id: 'true', logical_operator: 'and', conditions: [] }],
  })
  assert.deepEqual(newNode.data.cases[0].conditions, [])
})

test('operators follow the selected variable type', () => {
  assert.deepEqual(getIfElseOperators('number').map(item => item.value), ['=', '≠', '>', '<', '≥', '≤', 'is null', 'is not null'])
  assert.deepEqual(getIfElseOperators('boolean').map(item => item.value), ['is', 'is not', 'is null', 'is not null'])
  assert.ok(getIfElseOperators('string').some(item => item.value === 'contains'))
})

test('normalization derives exact branch Handle ids and preserves unknown fields', () => {
  const normalized = normalizeIfElseData({
    cases: [{ case_id: 'true', logical_operator: 'and', conditions: [] }, { case_id: 'elif-1', logical_operator: 'or', conditions: [] }],
    future: true,
  })
  assert.deepEqual(normalized._targetBranches.map(branch => branch.id), ['true', 'elif-1', 'false'])
  assert.deepEqual(getNodeOutputBranches({ type: 'if-else', ...normalized }).map(branch => branch.id), ['true', 'elif-1', 'false'])
  assert.equal(normalized.future, true)
})

test('DSL round-trip and checklist retain official cases and reject empty branches', () => {
  const flow = graphToFlow({ nodes: [{ id: 'if-1', type: 'custom', data: { type: 'if-else', cases: [{ case_id: 'true', logical_operator: 'and', conditions: [] }], future: 1 } }], edges: [] })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.cases[0].case_id, 'true')
  assert.equal(exported.nodes[0].data.future, 1)
  const issues = buildWorkflowChecklist({ nodes: [{ id: 'start', data: { type: 'start' } }, { id: 'if-1', data: exported.nodes[0].data }], edges: [{ source: 'start', target: 'if-1' }] })
  assert.ok(issues.some(issue => issue.id === 'ifelse-empty-if-1' && issue.level === 'error'))
})
