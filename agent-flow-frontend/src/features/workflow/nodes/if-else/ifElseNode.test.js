import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getEdgesAfterNodeDataUpdate, getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  IF_ELSE_DEFAULTS,
  addIfElseCase,
  createIfElseCondition,
  createIfElseSubCondition,
  deriveIfElseBranches,
  formatIfElseConditionValue,
  getIfElseOperators,
  isIfElseConditionComplete,
  normalizeIfElseData,
  removeIfElseCase,
  resolveIfElseVariable,
} from './ifElseNode.js'

const values = (type, file) => getIfElseOperators(type, file).map(item => item.value)

// 1. Defaults
test('defaults: a new if-else has one empty IF case and an implicit ELSE', () => {
  const { newNode } = generateNewNode({ type: 'if-else', id: 'if-1' })
  assert.deepEqual(newNode.data, { ...IF_ELSE_DEFAULTS, type: 'if-else', title: '条件分支' })
  assert.deepEqual(IF_ELSE_DEFAULTS, {
    _targetBranches: [{ id: 'true', name: 'IF' }, { id: 'false', name: 'ELSE' }],
    cases: [{ case_id: 'true', logical_operator: 'and', conditions: [] }],
  })
})

test('defaults: operator lists match the official Dify matrix', () => {
  assert.deepEqual(values('string'), ['contains', 'not contains', 'start with', 'end with', 'is', 'is not', 'empty', 'not empty'])
  assert.deepEqual(values('number'), ['=', '≠', '>', '<', '≥', '≤', 'empty', 'not empty'])
  assert.deepEqual(values('integer'), ['=', '≠', '>', '<', '≥', '≤', 'empty', 'not empty'])
  assert.deepEqual(values('boolean'), ['is', 'is not'])
  assert.deepEqual(values('file'), ['exists', 'not exists'])
  for (const type of ['arrayString', 'arrayNumber', 'arrayBoolean'])
    assert.deepEqual(values(type), ['contains', 'not contains', 'empty', 'not empty'])
  for (const type of ['array', 'arrayObject'])
    assert.deepEqual(values(type), ['empty', 'not empty'])
  assert.deepEqual(values('arrayFile'), ['contains', 'not contains', 'all of', 'empty', 'not empty'])
})

test('defaults: file attributes use the official Dify operators', () => {
  assert.deepEqual(values('file', { key: 'name' }), ['contains', 'not contains', 'start with', 'end with', 'is', 'is not', 'empty', 'not empty'])
  assert.deepEqual(values('file', { key: 'type' }), ['in', 'not in'])
  assert.deepEqual(values('file', { key: 'size' }), ['>', '≥', '<', '≤'])
  assert.deepEqual(values('file', { key: 'extension' }), ['is', 'is not', 'contains', 'not contains'])
  assert.deepEqual(values('file', { key: 'mime_type' }), ['contains', 'not contains', 'start with', 'end with', 'is', 'is not', 'empty', 'not empty'])
  assert.deepEqual(values('file', { key: 'transfer_method' }), ['in', 'not in'])
  assert.deepEqual(values('file', { key: 'url' }), ['contains', 'not contains', 'start with', 'end with', 'is', 'is not', 'empty', 'not empty'])
  assert.deepEqual(values('file', { key: 'related_id' }), ['is', 'is not', 'contains', 'not contains', 'start with', 'end with', 'empty', 'not empty'])
  assert.deepEqual(values('file', { key: 'unknown' }), [])
})

test('defaults: condition factory writes UUID, varType, selector, operator and typed value', () => {
  const booleanCondition = createIfElseCondition({ variableSelector: ['start', 'flag'], varType: 'boolean' })
  assert.match(booleanCondition.id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i)
  assert.deepEqual(booleanCondition, {
    id: booleanCondition.id,
    varType: 'boolean',
    variable_selector: ['start', 'flag'],
    comparison_operator: 'is',
    value: false,
  })
  assert.equal(createIfElseCondition({ variableSelector: ['sys', 'timestamp'], varType: 'number' }).value, '')
  assert.equal(createIfElseCondition().comparison_operator, '')
})

test('defaults: arrayFile subconditions use UUIDs and file attribute types', () => {
  const condition = createIfElseSubCondition('size')
  assert.match(condition.id, /^[0-9a-f-]{36}$/i)
  assert.deepEqual(condition, {
    id: condition.id,
    key: 'size',
    varType: 'number',
    comparison_operator: '>',
    value: '',
  })
})

// 2. Normalization / legacy / unknown fields
test('normalization: legacy conditions migrate into cases and obsolete fields are removed', () => {
  const conditions = [{ id: 'c1', varType: 'boolean', variable_selector: ['start', 'flag'], comparison_operator: 'is', value: false }]
  const actual = normalizeIfElseData({ type: 'if-else', logical_operator: 'or', conditions })
  assert.deepEqual(actual.cases, [{ case_id: 'true', logical_operator: 'or', conditions }])
  assert.equal(Object.hasOwn(actual, 'conditions'), false)
  assert.equal(Object.hasOwn(actual, 'logical_operator'), false)
})

test('normalization: imported case ids and unknown fields survive while stale branches are rebuilt', () => {
  const actual = normalizeIfElseData({
    type: 'if-else',
    cases: [
      { case_id: 'bd170f64-8f89-40db-9652-69ac9659a68a', logical_operator: 'or', conditions: [] },
      { case_id: 'true', logical_operator: 'and', conditions: [] },
    ],
    _targetBranches: [{ id: 'stale', name: 'Broken' }],
    future: { version: 7 },
  })
  assert.deepEqual(actual.cases.map(item => item.case_id), ['bd170f64-8f89-40db-9652-69ac9659a68a', 'true'])
  assert.deepEqual(actual._targetBranches, [
    { id: 'bd170f64-8f89-40db-9652-69ac9659a68a', name: 'CASE 1' },
    { id: 'true', name: 'CASE 2' },
    { id: 'false', name: 'ELSE' },
  ])
  assert.deepEqual(actual.future, { version: 7 })
})

test('normalization: variable resolution follows special and nested selector paths', () => {
  const groups = [
    { nodeId: 'global', vars: [{ variable: 'sys.timestamp', type: 'number' }] },
    { nodeId: 'code', vars: [{ variable: 'payload', type: 'object', children: [{ variable: 'enabled', type: 'boolean' }] }] },
    { nodeId: 'start', vars: [{ variable: 'file', type: 'file' }] },
  ]
  assert.equal(resolveIfElseVariable(groups, ['sys', 'timestamp']).type, 'number')
  assert.equal(resolveIfElseVariable(groups, ['code', 'payload', 'enabled']).type, 'boolean')
  assert.deepEqual(resolveIfElseVariable(groups, ['start', 'file', 'size']), { variable: 'size', type: 'number', file: { key: 'size' } })
  assert.equal(resolveIfElseVariable(groups, ['missing', 'value']), undefined)
})

test('normalization: adding and removing ELIF uses UUID and derives branches from cases', () => {
  const added = addIfElseCase(IF_ELSE_DEFAULTS)
  assert.equal(added.cases.length, 2)
  assert.match(added.cases[1].case_id, /^[0-9a-f-]{36}$/i)
  assert.deepEqual(added.cases[1].conditions, [])
  assert.deepEqual(added._targetBranches.map(item => item.name), ['CASE 1', 'CASE 2', 'ELSE'])
  assert.deepEqual(removeIfElseCase(added, added.cases[1].case_id), normalizeIfElseData(IF_ELSE_DEFAULTS))
})

// 3. Outputs
test('outputs: if-else exposes no downstream variables', () => {
  assert.deepEqual(getNodeOutputVars({ id: 'branch', data: { type: 'if-else' } }), [])
})

// 4. Handles
test('handles: cases are authoritative and ELSE is always the final false handle', () => {
  const data = {
    type: 'if-else',
    cases: [{ case_id: 'first' }, { case_id: 'second' }],
    _targetBranches: [{ id: 'stale', name: 'Broken' }],
  }
  assert.deepEqual(getNodeOutputBranches(data), [
    { id: 'first', name: 'CASE 1', kind: 'normal' },
    { id: 'second', name: 'CASE 2', kind: 'normal' },
    { id: 'false', name: 'ELSE', kind: 'normal' },
  ])
  assert.deepEqual(deriveIfElseBranches([{ case_id: 'true' }]), [{ id: 'true', name: 'IF' }, { id: 'false', name: 'ELSE' }])
})

test('handles: deleting an ELIF removes only the edge with that case id', () => {
  const previousData = normalizeIfElseData({ type: 'if-else', cases: [{ case_id: 'true' }, { case_id: 'elif-id' }] })
  const nextData = normalizeIfElseData({ type: 'if-else', cases: [{ case_id: 'true' }] })
  const edges = [
    { id: 'if', source: 'branch', sourceHandle: 'true', target: 'end' },
    { id: 'elif', source: 'branch', sourceHandle: 'elif-id', target: 'end' },
    { id: 'else', source: 'branch', sourceHandle: 'false', target: 'end' },
    { id: 'other', source: 'other', sourceHandle: 'elif-id', target: 'end' },
  ]
  const result = getEdgesAfterNodeDataUpdate({ nodeId: 'branch', previousData, nextData, edges })
  assert.deepEqual(result.removedEdgeIds, ['elif'])
  assert.deepEqual(result.edges, [edges[0], edges[2], edges[3]])
})

function graphWithCondition({ value = 'yes', comparisonOperator = 'is', varType = 'string' } = {}) {
  return {
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start', variables: [{ variable: 'input', label: 'Input', type: 'text-input', required: false }] } },
      { id: 'branch', data: { type: 'if-else', title: 'Branch', future: { version: 7 }, cases: [
        { case_id: 'true', logical_operator: 'and', conditions: [
          { id: 'condition-1', varType, variable_selector: ['start', 'input'], comparison_operator: comparisonOperator, value },
        ] },
      ] } },
      { id: 'end', data: { type: 'end', title: 'End', outputs: [{ variable: 'result', value_selector: ['start', 'input'], value_type: 'string' }] } },
    ],
    edges: [
      { source: 'start', target: 'branch', sourceHandle: 'source' },
      { source: 'branch', target: 'end', sourceHandle: 'true' },
      { source: 'branch', target: 'end', sourceHandle: 'false' },
    ],
  }
}

// 5. Round-trip
test('round-trip: official cases, false values, unknown fields and handles survive', () => {
  const graph = graphWithCondition({ value: false, varType: 'boolean' })
  const flow = graphToFlow(graph)
  const exported = flowToGraph(flow.nodes, flow.edges)
  const data = exported.nodes.find(node => node.id === 'branch').data
  assert.equal(data.type, 'if-else')
  assert.deepEqual(data.cases, graph.nodes[1].data.cases)
  assert.deepEqual(data.future, { version: 7 })
  assert.deepEqual(exported.edges.filter(edge => edge.source === 'branch').map(edge => edge.sourceHandle), ['true', 'false'])
})

// 6. Checklist: illegal and legal cases
test('checklist: complete strings, boolean false and numeric string zero are legal', () => {
  for (const graph of [
    graphWithCondition(),
    graphWithCondition({ value: false, varType: 'boolean' }),
    graphWithCondition({ value: '0', comparisonOperator: '=', varType: 'number' }),
  ])
    assert.deepEqual(buildWorkflowChecklist(graph).filter(issue => issue.level === 'error'), [])
})

test('checklist: incomplete selectors, empty cases and missing values are illegal', () => {
  assert.equal(isIfElseConditionComplete({ id: 'c', varType: 'string', variable_selector: ['start'], comparison_operator: 'is', value: 'yes' }), false)
  assert.equal(isIfElseConditionComplete({ id: 'c', varType: 'string', variable_selector: ['start', 'input'], comparison_operator: 'empty', value: '' }), true)
  assert.equal(isIfElseConditionComplete({ id: 'c', varType: 'boolean', variable_selector: ['start', 'input'], comparison_operator: 'is', value: false }), true)
  assert.equal(isIfElseConditionComplete({ id: 'c', varType: 'number', variable_selector: ['start', 'input'], comparison_operator: '=', value: 0 }), false)
  const graph = graphWithCondition({ value: '' })
  assert.ok(buildWorkflowChecklist(graph).some(issue => issue.id === 'ifelse-condition-branch' && issue.level === 'error'))
})

test('checklist: canvas formatting preserves false and marks incomplete conditions as unset', () => {
  assert.equal(formatIfElseConditionValue({ varType: 'boolean', comparison_operator: 'is', value: false }), 'False')
  assert.equal(formatIfElseConditionValue({ varType: 'boolean', comparison_operator: 'is', value: true }), 'True')
  assert.equal(formatIfElseConditionValue({ varType: 'number', comparison_operator: '=', value: '0' }), '0')
  assert.equal(formatIfElseConditionValue({ varType: 'string', comparison_operator: 'is', value: '' }), '未设置')
  assert.equal(formatIfElseConditionValue({ varType: 'boolean', value: false }), '未设置')
  assert.equal(formatIfElseConditionValue({ comparison_operator: 'empty', value: '' }), '')
})
