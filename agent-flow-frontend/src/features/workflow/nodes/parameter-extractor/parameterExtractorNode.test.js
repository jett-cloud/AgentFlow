import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  PARAMETER_EXTRACTOR_DEFAULTS,
  isParameterExtractorInput,
  normalizeParameterExtractorData,
} from './parameterExtractorNode.js'

test('new parameter-extractor nodes use Dify defaults', () => {
  const { newNode } = generateNewNode({ type: 'parameter-extractor', id: 'pe-1' })
  assert.deepEqual(newNode.data, {
    type: 'parameter-extractor',
    title: '参数提取',
    ...PARAMETER_EXTRACTOR_DEFAULTS,
  })
})

test('query accepts text variables only', () => {
  assert.equal(isParameterExtractorInput({ type: 'string' }), true)
  assert.equal(isParameterExtractorInput({ type: 'number' }), false)
  assert.equal(isParameterExtractorInput({ type: 'arrayString' }), false)
})

test('normalization migrates the legacy query selector and preserves unknown fields', () => {
  const normalized = normalizeParameterExtractorData({
    query_variable_selector: ['start', 'query'],
    reasoning_mode: 'unknown',
    parameters: [{ name: 'tags', type: 'array[string]', description: '标签', required: true }],
    future: true,
  })
  assert.deepEqual(normalized.query, ['start', 'query'])
  assert.equal(normalized.query_variable_selector, undefined)
  assert.equal(normalized.reasoning_mode, 'prompt')
  assert.equal(normalized.future, true)
})

test('parameter outputs retain official array types and common status outputs', () => {
  const outputs = getNodeOutputVars({
    data: {
      type: 'parameter-extractor',
      parameters: [
        { name: 'tags', type: 'array[string]', description: '标签' },
        { name: 'scores', type: 'array[number]', description: '分数' },
      ],
    },
  })
  assert.ok(outputs.some(item => item.variable === 'tags' && item.type === 'arrayString'))
  assert.ok(outputs.some(item => item.variable === 'scores' && item.type === 'arrayNumber'))
  assert.deepEqual(outputs.slice(-3).map(item => item.variable), ['__is_success', '__reason', '__usage'])
})

test('DSL round-trip preserves fields and checklist rejects incomplete parameter definitions', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'pe-1',
      type: 'custom',
      data: {
        type: 'parameter-extractor',
        query: [],
        model: { provider: '', name: '', mode: 'chat', completion_params: { temperature: 0.7 } },
        reasoning_mode: 'prompt',
        parameters: [{ name: 'city', type: 'string', description: '' }],
        vision: { enabled: true },
        future: 1,
      },
    }],
    edges: [],
  })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.future, 1)

  const issues = buildWorkflowChecklist({
    nodes: [{ id: 'start', data: { type: 'start' } }, { id: 'pe-1', data: exported.nodes[0].data }],
    edges: [{ source: 'start', target: 'pe-1' }],
  })
  assert.ok(issues.some(issue => issue.id === 'pe-query-pe-1'))
  assert.ok(issues.some(issue => issue.id === 'pe-parameters-pe-1'))
  assert.ok(issues.some(issue => issue.id === 'pe-vision-pe-1'))
})
