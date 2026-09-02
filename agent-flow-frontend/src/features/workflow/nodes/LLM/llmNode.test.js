import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import { LLM_DEFAULTS, normalizeLLMNodeData } from './llmNode.js'

test('new LLM nodes use the official empty configuration', () => {
  const { newNode } = generateNewNode({ type: 'llm', id: 'llm-1' })
  assert.deepEqual(newNode.data, { type: 'llm', title: 'LLM', ...LLM_DEFAULTS })
  assert.equal(newNode.data.memory, undefined)
})

test('normalization migrates legacy prompt and schema strings while preserving unknown fields', () => {
  const normalized = normalizeLLMNodeData({
    prompt: '总结上文',
    structured_output_enabled: true,
    structured_output: { schema: '{"type":"object","properties":{"summary":{"type":"string"}},"required":["summary"],"additionalProperties":false}' },
    future: true,
  })

  assert.deepEqual(normalized.prompt_template, [{ role: 'user', text: '总结上文' }])
  assert.equal(normalized.prompt, undefined)
  assert.equal(normalized.structured_output.schema.properties.summary.type, 'string')
  assert.equal(normalized.future, true)
})

test('structured output is exposed with official common LLM outputs', () => {
  const outputs = getNodeOutputVars({
    data: normalizeLLMNodeData({
      type: 'llm',
      structured_output_enabled: true,
      structured_output: {
        schema: {
          type: 'object',
          properties: { summary: { type: 'string' } },
          required: ['summary'],
          additionalProperties: false,
        },
      },
    }),
  })

  assert.deepEqual(outputs.slice(0, 3).map(item => item.variable), ['text', 'reasoning_content', 'usage'])
  assert.ok(outputs.some(item => item.variable === 'structured_output' && item.children.schema.properties.summary.type === 'string'))
})

test('DSL round-trip preserves official and unknown fields and checklist rejects incomplete LLM config', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'llm-1',
      type: 'custom',
      data: {
        type: 'llm',
        model: { provider: '', name: '', mode: 'chat', completion_params: { temperature: 0.7 } },
        prompt_template: [{ role: 'system', text: '' }],
        context: { enabled: false, variable_selector: [] },
        vision: { enabled: true },
        future: 1,
      },
    }],
    edges: [],
  })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.future, 1)

  const issues = buildWorkflowChecklist({
    nodes: [{ id: 'start', data: { type: 'start' } }, { id: 'llm-1', data: exported.nodes[0].data }],
    edges: [{ source: 'start', target: 'llm-1' }],
  })
  assert.ok(issues.some(issue => issue.id === 'model-config-llm-1'))
  assert.ok(issues.some(issue => issue.id === 'llm-prompt-llm-1'))
  assert.ok(issues.some(issue => issue.id === 'llm-vision-llm-1'))
})
