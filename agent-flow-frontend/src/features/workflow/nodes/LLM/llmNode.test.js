import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import {
  LLM_DEFAULTS,
  hasInvalidLLMJinjaMapping,
  isLLMPromptEmpty,
  isLLMVisionFileVariable,
  normalizeLLMNodeData,
} from './llmNode.js'

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

test('DSL round-trip preserves official and unknown fields', () => {
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
  assert.equal(exported.nodes[0].data.type, 'llm')
  assert.deepEqual(exported.nodes[0].data.prompt_template, [{ role: 'system', text: '' }])
})

test('checklist rejects incomplete LLM config', () => {
  const issues = buildWorkflowChecklist({
    nodes: [{ id: 'start', data: { type: 'start' } }, { id: 'llm-1', data: { type: 'llm', ...LLM_DEFAULTS, vision: { enabled: true } } }],
    edges: [{ source: 'start', target: 'llm-1' }],
  })
  assert.ok(issues.some(issue => issue.id === 'model-config-llm-1'))
  assert.ok(issues.some(issue => issue.id === 'llm-prompt-llm-1'))
  assert.ok(issues.some(issue => issue.id === 'llm-vision-llm-1'))
})

test('vision configs round-trip and old vision data without configs still opens', () => {
  const withSelector = normalizeLLMNodeData({
    type: 'llm',
    vision: {
      enabled: true,
      configs: { detail: 'low', variable_selector: ['sys', 'files'], extra: true },
    },
    future: 1,
  })
  assert.deepEqual(withSelector.vision.configs.variable_selector, ['sys', 'files'])
  assert.equal(withSelector.vision.configs.detail, 'low')
  assert.equal(withSelector.vision.configs.extra, true)

  const legacy = normalizeLLMNodeData({ type: 'llm', vision: { enabled: true } })
  assert.equal(legacy.vision.enabled, true)
  assert.equal(legacy.vision.configs, undefined)

  const flow = graphToFlow({
    nodes: [{ id: 'llm-1', type: 'custom', data: { type: 'llm', ...withSelector } }],
    edges: [],
  })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.deepEqual(exported.nodes[0].data.vision.configs.variable_selector, ['sys', 'files'])
  assert.equal(exported.nodes[0].data.vision.configs.detail, 'low')
  assert.equal(exported.nodes[0].data.future, 1)
})

test('checklist accepts vision when a file variable is selected', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', variables: [] } },
      {
        id: 'llm-1',
        data: normalizeLLMNodeData({
          type: 'llm',
          model: { provider: 'openai', name: 'gpt-4o', mode: 'chat' },
          prompt_template: [{ role: 'user', text: 'Describe the image.' }],
          vision: { enabled: true, configs: { detail: 'high', variable_selector: ['sys', 'files'] } },
        }),
      },
      { id: 'end', data: { type: 'end', outputs: [{ variable: 'result', value_selector: ['llm-1', 'text'], value_type: 'string' }] } },
    ],
    edges: [{ source: 'start', target: 'llm-1' }, { source: 'llm-1', target: 'end' }],
  })
  assert.equal(issues.some(issue => issue.id === 'llm-vision-llm-1'), false)
  assert.equal(issues.some(issue => issue.level === 'error'), false)
})

test('vision picker only accepts file variables', () => {
  assert.equal(isLLMVisionFileVariable({ type: 'file' }), true)
  assert.equal(isLLMVisionFileVariable({ type: 'arrayFile' }), true)
  assert.equal(isLLMVisionFileVariable({ type: 'array[file]' }), true)
  assert.equal(isLLMVisionFileVariable({ selector: ['sys', 'files'] }), true)
  assert.equal(isLLMVisionFileVariable({ type: 'string' }), false)
})

test('Handles expose source and optional failure branch; retry is not a branch', () => {
  assert.deepEqual(getNodeOutputBranches({ type: 'llm' }).map(item => item.id), ['source'])
  assert.deepEqual(getNodeOutputBranches({ type: 'llm', retry_config: { retry_enabled: true } }).map(item => item.id), ['source'])
  assert.deepEqual(getNodeOutputBranches({ type: 'llm', error_strategy: 'fail-branch' }).map(item => item.id), ['source', 'fail-branch'])
})

test('DSL round-trip preserves retry, failure strategy, nested extensions and migrates prompt', () => {
  const data = {
    type: 'llm', title: 'Summarize', prompt: 'Summarize the input.',
    model: { provider: 'openai', name: 'gpt-4o', mode: 'chat', future_model: 1 },
    retry_config: { retry_enabled: true, max_retries: 3, retry_interval: 1000 },
    error_strategy: 'fail-branch', future: { preserved: true },
  }
  const flow = graphToFlow({ nodes: [{ id: 'llm-1', data }], edges: [] })
  const saved = flowToGraph(flow.nodes, flow.edges).nodes[0].data
  assert.equal(saved.prompt, undefined)
  assert.deepEqual(saved.prompt_template, [{ role: 'user', text: data.prompt }])
  assert.deepEqual(saved.retry_config, data.retry_config)
  assert.equal(saved.error_strategy, 'fail-branch')
  assert.equal(saved.model.future_model, 1)
  assert.deepEqual(saved.future, data.future)
})

test('checklist accepts a complete Start to LLM to End workflow', () => {
  const nodes = [
    { id: 'start', data: { type: 'start', variables: [] } },
    { id: 'llm-1', data: normalizeLLMNodeData({ type: 'llm', model: { provider: 'openai', name: 'gpt-4o', mode: 'chat' }, prompt_template: [{ role: 'user', text: 'Write a greeting.' }] }) },
    { id: 'end', data: { type: 'end', outputs: [{ variable: 'result', value_selector: ['llm-1', 'text'], value_type: 'string' }] } },
  ]
  const edges = [{ source: 'start', target: 'llm-1' }, { source: 'llm-1', target: 'end' }]
  assert.deepEqual(buildWorkflowChecklist({ nodes, edges }).filter(issue => issue.level === 'error'), [])
})

test('Jinja prompts use jinja2_text and reject incomplete variable mappings', () => {
  const jinja = {
    prompt_template: [{ role: 'user', edition_type: 'jinja2', text: 'stale basic text', jinja2_text: 'Hello {{ name }}' }],
    prompt_config: { jinja2_variables: [{ variable: 'name', value_selector: ['start', 'name'] }] },
  }
  assert.equal(isLLMPromptEmpty(jinja), false)
  assert.equal(hasInvalidLLMJinjaMapping(jinja), false)
  assert.equal(hasInvalidLLMJinjaMapping({
    ...jinja,
    prompt_config: { jinja2_variables: [{ variable: '', value_selector: ['start'] }] },
  }), true)
})

test('structured properties are nested outputs and enabled empty schemas still expose structured_output', () => {
  const data = { type: 'llm', structured_output_enabled: true, structured_output: { schema: { type: 'object', properties: { summary: { type: 'string' } } } } }
  const names = getNodeOutputVars({ data }).map(item => item.variable)
  assert.equal(names.includes('summary'), false)
  assert.equal(names.includes('structured_output'), true)
  assert.equal(getNodeOutputVars({
    data: { type: 'llm', structured_output_enabled: true, structured_output: { schema: { type: 'object', properties: {} } } },
  }).some(item => item.variable === 'structured_output'), true)
  assert.equal(getNodeOutputVars({ data: { ...data, structured_output_enabled: false } }).some(item => item.variable === 'structured_output'), false)
})

test('checklist treats whitespace-only model provider and name as missing', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start' } },
      { id: 'llm-1', data: { type: 'llm', ...LLM_DEFAULTS, model: { provider: ' ', name: ' ', mode: 'chat' }, prompt_template: [{ role: 'user', text: 'Hi' }] } },
    ],
    edges: [{ source: 'start', target: 'llm-1' }],
  })
  assert.ok(issues.some(issue => issue.id === 'model-config-llm-1'))
})
