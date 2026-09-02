import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import {
  END_DEFAULTS,
  getEndValidationErrors,
  isEndAllowedInMode,
  normalizeEndNodeData,
  upsertEndOutput,
} from './endNode.js'

test('new End nodes use Dify outputs default', () => {
  const { newNode } = generateNewNode({ type: 'end', id: 'end-1' })
  assert.deepEqual(newNode.data, { type: 'end', title: '结束', ...END_DEFAULTS })
})

test('End is selectable only in Workflow mode', () => {
  assert.equal(isEndAllowedInMode('workflow'), true)
  assert.equal(isEndAllowedInMode('advanced-chat'), false)
  assert.equal(isEndAllowedInMode('chat'), false)
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

test('End DSL round-trip preserves official fields and checklist rejects incomplete outputs', () => {
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
  assert.deepEqual(exported.nodes[0].data.outputs[0].value_selector, ['knowledge', 'result'])
  assert.equal(exported.nodes[0].data.outputs[0].value_type, 'array[object]')
  assert.equal(exported.nodes[0].data.outputs[0].future, 1)
  assert.equal(exported.nodes[0].data.node_future, true)

  const issues = buildWorkflowChecklist({
    nodes: [{ id: 'end-empty', data: { type: 'end', title: '结束', outputs: [] } }],
    edges: [],
  })
  assert.ok(issues.some(issue => issue.id === 'end-outputs-end-empty'))
})
