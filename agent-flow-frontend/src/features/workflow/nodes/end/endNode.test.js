import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { CONTAINER_SELECTABLE_BLOCKS } from '../../model/nodeMeta.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  END_DEFAULTS,
  getEndValidationErrors,
  isEndAllowedInMode,
  normalizeEndNodeData,
  upsertEndOutput,
} from './endNode.js'

// 1. Defaults and availability
test('new End nodes use Dify outputs default', () => {
  const { newNode } = generateNewNode({ type: 'end', id: 'end-1' })
  assert.deepEqual(newNode.data, { type: 'end', title: '结束', ...END_DEFAULTS })
})

test('End is selectable only in Workflow mode', () => {
  assert.equal(isEndAllowedInMode('workflow'), true)
  assert.equal(isEndAllowedInMode('advanced-chat'), false)
  assert.equal(isEndAllowedInMode('chat'), false)
})

// 2. Normalization, migration, and unknown-field preservation
test('End normalization always writes the canonical backend type', () => {
  const normalized = normalizeEndNodeData({ type: 'future-end-alias', future: true })
  assert.equal(normalized.type, 'end')
  assert.equal(normalized.future, true)
})

test('normalization migrates selector strings and preserves official unknown fields', () => {
  const normalized = normalizeEndNodeData({
    outputs: [{
      variable: 'result',
      value_selector: 'llm.text',
      value_type: 'arrayObject',
      future: true,
    }],
    node_future: 1,
  })
  assert.deepEqual(normalized.outputs[0], {
    variable: 'result',
    value_selector: ['llm', 'text'],
    value_type: 'array[object]',
    future: true,
  })
  assert.equal(normalized.node_future, 1)
})

test('output editing stores selector type and rejects duplicate names', () => {
  const first = upsertEndOutput({ outputs: [] }, -1, {
    variable: 'result',
    value_selector: ['llm', 'text'],
    value_type: 'string',
  })
  assert.equal(first.ok, true)
  assert.deepEqual(first.data.outputs[0], {
    variable: 'result',
    value_selector: ['llm', 'text'],
    value_type: 'string',
  })
  const duplicate = upsertEndOutput(first.data, -1, {
    variable: 'result',
    value_selector: ['code', 'value'],
    value_type: 'number',
  })
  assert.equal(duplicate.ok, false)

  const knowledgeResult = upsertEndOutput({ outputs: [] }, -1, {
    variable: 'records',
    value_selector: ['knowledge', 'result'],
    value_type: 'arrayObject',
  })
  assert.equal(knowledgeResult.ok, true)
  assert.equal(knowledgeResult.data.outputs[0].value_type, 'array[object]')
})

test('End validation requires valid unique names and bound selectors', () => {
  assert.deepEqual(getEndValidationErrors({ outputs: [] }), ['至少添加一个输出变量'])
  const errors = getEndValidationErrors({
    outputs: [
      { variable: '1 invalid', value_selector: [] },
      { variable: 'same', value_selector: ['llm', 'text'] },
      { variable: 'same', value_selector: ['code', 'result'] },
    ],
  })
  assert.ok(errors.includes('输出变量名“1 invalid”不合法'))
  assert.ok(errors.includes('输出变量“1 invalid”未绑定上游变量'))
  assert.ok(errors.includes('输出变量名“same”重复'))

  const invalidTypeErrors = getEndValidationErrors({
    outputs: [{
      variable: 'result',
      value_selector: ['knowledge', 'result'],
      value_type: 'arrayObjectTypo',
    }],
  })
  assert.ok(invalidTypeErrors.includes('输出变量“result”的类型“arrayObjectTypo”不是 Dify 支持的类型'))
})

// 3. Selectable outputs
test('End exposes no selectable outputs', () => {
  assert.deepEqual(getNodeOutputVars({ id: 'end', data: { type: 'end', outputs: [] } }), [])
})

// 4. Handles and container placement
test('End has no source branch and is excluded from containers', () => {
  assert.deepEqual(getNodeOutputBranches({ type: 'end' }), [])
  assert.equal(CONTAINER_SELECTABLE_BLOCKS.includes('end'), false)
})

// 5. DSL round-trip
test('End DSL round-trip preserves official fields', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'end-1',
      type: 'custom',
      data: {
        type: 'end',
        outputs: [{
          variable: 'result',
          value_selector: 'knowledge.result',
          value_type: 'arrayObject',
          future: 1,
        }],
        node_future: true,
      },
    }],
    edges: [],
  })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.type, 'end')
  assert.deepEqual(exported.nodes[0].data.outputs[0].value_selector, ['knowledge', 'result'])
  assert.equal(exported.nodes[0].data.outputs[0].value_type, 'array[object]')
  assert.equal(exported.nodes[0].data.outputs[0].future, 1)
  assert.equal(exported.nodes[0].data.node_future, true)
})

// 6. Checklist: invalid and valid graphs
test('End checklist rejects incomplete outputs', () => {
  const issues = buildWorkflowChecklist({
    nodes: [{ id: 'end-empty', data: { type: 'end', title: '结束', outputs: [] } }],
    edges: [],
  })
  assert.ok(issues.some(issue => issue.id === 'end-outputs-end-empty'))
})

test('Workflow checklist requires End and rejects End outgoing edges', () => {
  const missing = buildWorkflowChecklist({
    nodes: [{ id: 'start', data: { type: 'start', title: '开始', variables: [] } }],
    edges: [],
  })
  assert.ok(missing.some(issue => issue.id === 'end-required' && issue.level === 'error'))

  const outgoing = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: '开始', variables: [] } },
      {
        id: 'end',
        data: {
          type: 'end',
          title: '结束',
          outputs: [{ variable: 'result', value_selector: ['start', 'query'], value_type: 'string' }],
        },
      },
      { id: 'next', data: { type: 'template-transform', title: '模板', template: 'x', variables: [] } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'end' },
      { id: 'e2', source: 'end', target: 'next' },
    ],
  })
  assert.ok(outgoing.some(issue => issue.id === 'end-outgoing-end'))
})

test('complete End checklist has no errors', () => {
  const validGraph = {
    nodes: [
      {
        id: 'start',
        data: {
          type: 'start',
          title: '开始',
          variables: [{ variable: 'query', label: 'Query', type: 'paragraph', required: true }],
        },
      },
      {
        id: 'end',
        data: {
          type: 'end',
          title: '结束',
          outputs: [{ variable: 'result', value_selector: ['start', 'query'], value_type: 'string' }],
        },
      },
    ],
    edges: [{ id: 'e1', source: 'start', target: 'end' }],
  }
  assert.deepEqual(buildWorkflowChecklist(validGraph).filter(issue => issue.level === 'error'), [])
})
