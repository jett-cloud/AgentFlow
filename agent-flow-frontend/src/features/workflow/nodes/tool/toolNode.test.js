import assert from 'node:assert/strict'
import test from 'node:test'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  TOOL_DEFAULTS,
  applyToolSelection,
  applyToolParamUpdate,
  isToolConfigured,
  normalizeToolNodeData,
  setToolErrorStrategy,
} from './toolNode.js'

const SEARCH_TOOL = {
  provider_id: 'search-provider',
  provider_type: 'mcp',
  provider_name: 'Search',
  tool_name: 'search',
  tool_label: 'Search',
  plugin_unique_identifier: 'mcp.search@1',
  parameters: [
    { name: 'query', type: 'string', form: 'llm', required: true },
    { name: 'limit', type: 'number', form: 'form', required: false, default: 0 },
    { name: 'enabled', type: 'boolean', form: 'form', required: false, default: false },
    { name: 'doc', type: 'file', form: 'llm', required: true },
  ],
  output_schema: {
    type: 'object',
    properties: {
      text: { type: 'string' },
      files: { type: 'array', items: { type: 'file' } },
    },
  },
}

function completeToolData(overrides = {}) {
  return {
    type: 'tool',
    title: '搜索',
    provider_id: 'search-provider',
    provider_type: 'mcp',
    provider_name: 'Search',
    tool_name: 'search',
    tool_label: 'Search',
    credential_id: 'cred-1',
    plugin_unique_identifier: 'mcp.search@1',
    tool_configurations: { limit: 0 },
    tool_parameters: {
      query: { type: 'mixed', value: 'find {{#start.query#}}', extra: 1 },
      selector: { type: 'variable', value: ['start', 'query'] },
      enabled: { type: 'constant', value: false },
    },
    parameters: SEARCH_TOOL.parameters,
    output_schema: SEARCH_TOOL.output_schema,
    future_node_field: true,
    ...overrides,
  }
}

test('new Tool nodes use Dify provider and parameter defaults', () => {
  const { newNode } = generateNewNode({ type: 'tool', id: 'tool-1' })
  assert.deepEqual(newNode.data, { type: 'tool', title: '工具', ...TOOL_DEFAULTS })
})

test('Tool normalization keeps legal provider_type and nested parameter extras', () => {
  const draft = {
    type: 'tool',
    provider_id: 'provider',
    provider_type: 'mcp',
    tool_name: 'search',
    tool_parameters: {
      query: { type: 'variable', value: ['start', 'query'], future: true },
    },
    tool_configurations: { limit: 0 },
    future_node_field: true,
  }
  const original = structuredClone(draft)
  const normalized = normalizeToolNodeData(draft)
  assert.deepEqual(normalized.tool_parameters.query.value, ['start', 'query'])
  assert.equal(normalized.tool_parameters.query.future, true)
  assert.equal(normalized.future_node_field, true)
  assert.equal(normalized.provider_type, 'mcp')
  assert.equal(normalized.tool_configurations.limit, 0)
  assert.deepEqual(draft, original)
  assert.equal(isToolConfigured(normalized), true)
  assert.equal(isToolConfigured({ provider_id: 'p' }), false)
})

test('Tool normalization does not rewrite persisted plugin provider_type', () => {
  const data = normalizeToolNodeData({
    provider_id: 'ghy/doubao-image/doubao-image',
    provider_type: 'plugin',
    tool_name: 'image_gerenate_image',
  })
  assert.equal(data.provider_type, 'plugin')
  assert.equal(data.provider_id, 'ghy/doubao-image/doubao-image')
})

test('Tool outputs come from catalogue schema and are empty when unknown', () => {
  assert.deepEqual(getNodeOutputVars({ data: { type: 'tool' } }), [])
  const outputs = getNodeOutputVars({ data: { type: 'tool', output_schema: SEARCH_TOOL.output_schema } })
  assert.equal(outputs[0].variable, 'text')
  assert.equal(outputs[0].type, 'string')
  assert.equal(outputs[1].variable, 'files')
  assert.equal(outputs[1].type, 'arrayFile')
  assert.ok(outputs[1].children.some(child => child.variable === 'url' && child.type === 'string'))
})

test('Tool node exposes the normal and failure Handles only when configured', () => {
  assert.deepEqual(getNodeOutputBranches({ type: 'tool' }), [{ id: 'source', name: '', kind: 'normal' }])
  assert.deepEqual(getNodeOutputBranches({ type: 'tool', error_strategy: 'fail-branch' }), [
    { id: 'source', name: '', kind: 'normal' },
    { id: 'fail-branch', name: '失败', kind: 'failure' },
  ])
  const cleared = setToolErrorStrategy({ type: 'tool', error_strategy: 'fail-branch' }, 'none')
  assert.equal(cleared.error_strategy, undefined)
})

test('graphToFlow and flowToGraph retain the complete Tool contract', () => {
  const data = completeToolData()
  const flow = graphToFlow({ nodes: [{ id: 'tool-1', type: 'custom', data }], edges: [] })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.provider_type, 'mcp')
  assert.equal(exported.nodes[0].data.credential_id, 'cred-1')
  assert.equal(exported.nodes[0].data.plugin_unique_identifier, 'mcp.search@1')
  assert.deepEqual(exported.nodes[0].data.tool_parameters.query, data.tool_parameters.query)
  assert.deepEqual(exported.nodes[0].data.tool_parameters.selector.value, ['start', 'query'])
  assert.equal(exported.nodes[0].data.tool_parameters.enabled.value, false)
  assert.equal(exported.nodes[0].data.tool_configurations.limit, 0)
  assert.equal(exported.nodes[0].data.tool_configurations.enabled, false)
  assert.deepEqual(exported.nodes[0].data.output_schema, SEARCH_TOOL.output_schema)
  assert.equal(exported.nodes[0].data.future_node_field, true)
})

test('selecting a tool seeds form defaults into tool_configurations', () => {
  const selected = applyToolSelection({}, SEARCH_TOOL)
  assert.equal(selected.provider_icon, null)
  assert.deepEqual(selected.tool_parameters.limit, { type: 'constant', value: 0 })
  assert.equal(selected.tool_parameters.enabled.value, false)
  assert.deepEqual(selected.tool_configurations, { limit: 0, enabled: false })
  assert.equal(selected.tool_configurations.query, undefined)
})

test('form parameter edits sync tool_configurations without dropping false or 0', () => {
  const selected = applyToolSelection({}, SEARCH_TOOL)
  const limited = applyToolParamUpdate(selected, SEARCH_TOOL.parameters[1], { type: 'constant', value: 5 })
  assert.deepEqual(limited.tool_parameters.limit, { type: 'constant', value: 5 })
  assert.equal(limited.tool_configurations.limit, 5)
  const disabled = applyToolParamUpdate(limited, SEARCH_TOOL.parameters[2], { type: 'constant', value: false })
  assert.equal(disabled.tool_parameters.enabled.value, false)
  assert.equal(disabled.tool_configurations.enabled, false)
  const query = applyToolParamUpdate(disabled, SEARCH_TOOL.parameters[0], { type: 'mixed', value: 'q' })
  assert.equal(query.tool_parameters.query.value, 'q')
  assert.equal(query.tool_configurations.query, undefined)
})

test('changing tools does not inherit old parameters, configurations, or credentials', () => {
  const previous = applyToolSelection(completeToolData({ provider_type: 'builtin' }), SEARCH_TOOL)
  const next = applyToolSelection(previous, {
    provider_id: 'other',
    provider_type: 'builtin',
    provider_name: 'Other',
    tool_name: 'echo',
    tool_label: 'Echo',
    parameters: [{ name: 'query', type: 'string', form: 'llm', required: true }],
    output_schema: {},
  })
  assert.equal(next.provider_id, 'other')
  assert.equal(next.tool_name, 'echo')
  assert.equal(next.credential_id, '')
  assert.deepEqual(next.tool_configurations, {})
  assert.equal(next.tool_parameters.query.value, '')
  assert.equal(next.tool_parameters.enabled, undefined)
})

test('reselecting the same tool keeps same-named parameters and credentials', () => {
  const previous = completeToolData({ credential_id: 'keep-me' })
  const next = applyToolSelection(previous, SEARCH_TOOL)
  assert.equal(next.credential_id, 'keep-me')
  assert.equal(next.tool_parameters.query.value, 'find {{#start.query#}}')
  assert.equal(next.tool_configurations.limit, 0)
})

test('Checklist catches incomplete Tool catalog selection, invalid envelopes, and missing required params', () => {
  const incomplete = buildWorkflowChecklist({
    nodes: [{ id: 'start', data: { type: 'start' } }, { id: 'tool-1', data: { type: 'tool', title: '工具', provider_id: 'p' } }],
    edges: [{ source: 'start', target: 'tool-1' }],
  })
  assert.ok(incomplete.some(issue => issue.id === 'tool-tool-1' && issue.level === 'error'))

  const invalid = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start' } },
      {
        id: 'tool-1',
        data: completeToolData({
          tool_parameters: {
            query: { type: 'variable', value: 'start.query' },
            enabled: { type: 'constant', value: false },
          },
        }),
      },
    ],
    edges: [{ source: 'start', target: 'tool-1' }],
  })
  assert.ok(invalid.some(issue => issue.id === 'tool-parameter-tool-1-query'))

  const missing = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start' } },
      {
        id: 'tool-1',
        data: completeToolData({
          tool_parameters: { enabled: { type: 'constant', value: false } },
        }),
      },
    ],
    edges: [{ source: 'start', target: 'tool-1' }],
  })
  assert.ok(missing.some(issue => issue.id === 'tool-parameter-tool-1-query'))
  assert.equal(missing.some(issue => issue.id === 'tool-parameter-tool-1-doc'), false)
})

test('Checklist accepts a configured Tool node including false and 0 constants', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      { id: 'tool-1', data: completeToolData() },
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { source: 'start', target: 'tool-1' },
      { source: 'tool-1', target: 'end' },
    ],
  })
  assert.equal(issues.some(issue => String(issue.id).startsWith('tool-')), false)
})

test('Checklist flags missing required form configurations separately from llm parameters', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start' } },
      {
        id: 'tool-1',
        data: {
          type: 'tool',
          title: '工具',
          provider_id: 'p',
          tool_name: 'search',
          tool_parameters: { query: { type: 'mixed', value: 'q' } },
          tool_configurations: {},
          parameters: [
            { name: 'query', type: 'string', form: 'llm', required: true },
            { name: 'mode', type: 'select', form: 'form', required: true },
          ],
        },
      },
    ],
    edges: [{ source: 'start', target: 'tool-1' }],
  })
  assert.equal(issues.some(issue => issue.id === 'tool-parameter-tool-1-query'), false)
  assert.ok(issues.some(issue => issue.id === 'tool-configuration-tool-1-mode'))
})
