import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { canConnectAsSource, canConnectAsTarget } from '../../model/nodeMeta.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import { createPayloadForType, InputVarType } from './useStartConfig.js'

test('new Start nodes use the persisted workflow defaults', () => {
  const { newNode } = generateNewNode({ type: 'start', id: 'start-1' })

  assert.deepEqual(newNode.data, {
    type: 'start',
    title: '开始',
    variables: [],
  })
})

test('Start normalization migrates the legacy JSON type and preserves unknown official fields', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'start-1',
      type: 'custom',
      position: { x: 0, y: 0 },
      data: {
        type: 'start',
        title: '开始',
        variables: [{
          variable: 'payload',
          label: 'Payload',
          type: 'json-object',
          required: true,
          json_schema: '{"type":"object","properties":{}}',
          future_variable_field: true,
        }],
        future_node_field: { enabled: true },
      },
    }],
    edges: [],
  })

  assert.equal(flow.nodes[0].data.variables[0].type, 'json_object')
  assert.equal(flow.nodes[0].data.variables[0].future_variable_field, true)
  assert.deepEqual(flow.nodes[0].data.future_node_field, { enabled: true })

  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.variables[0].type, 'json_object')
  assert.equal(JSON.stringify(exported).includes('json-object'), false)
})

test('new JSON Start inputs persist the canonical json_object type', () => {
  const input = createPayloadForType('payload', InputVarType.jsonObject)

  assert.equal(input.type, 'json_object')
})

test('Start exposes backend-declared inputs and system outputs with matching types', () => {
  const vars = getNodeOutputVars({
    id: 'start-1',
    data: {
      type: 'start',
      variables: [
        { variable: 'name', label: 'Name', type: 'text-input' },
        { variable: 'description', label: 'Description', type: 'paragraph' },
        { variable: 'category', label: 'Category', type: 'select', options: ['A'] },
        { variable: 'count', label: 'Count', type: 'number' },
        { variable: 'enabled', label: 'Enabled', type: 'checkbox' },
        { variable: 'document', label: 'Document', type: 'file' },
        { variable: 'attachments', label: 'Attachments', type: 'file-list' },
        {
          variable: 'payload',
          label: 'Payload',
          type: 'json_object',
          json_schema: { type: 'object', properties: { answer: { type: 'string' } } },
        },
      ],
    },
  }, { isChatMode: true })

  assert.deepEqual(vars.map(item => [item.variable, item.type]), [
    ['name', 'string'],
    ['description', 'string'],
    ['category', 'string'],
    ['count', 'number'],
    ['enabled', 'boolean'],
    ['document', 'file'],
    ['attachments', 'arrayFile'],
    ['payload', 'object'],
    ['sys.query', 'string'],
    ['sys.files', 'arrayFile'],
  ])
  assert.deepEqual(vars.find(item => item.variable === 'payload')?.children?.schema, {
    type: 'object',
    properties: { answer: { type: 'string' } },
  })
})

test('Start has only a source connection handle', () => {
  assert.equal(canConnectAsSource('start'), true)
  assert.equal(canConnectAsTarget('start'), false)
})

test('Start DSL round-trip preserves the backend contract and unknown fields', () => {
  const graph = {
    nodes: [{
      id: 'start-1',
      type: 'custom',
      position: { x: 10, y: 20 },
      data: {
        type: 'start',
        title: '开始',
        variables: [{
          variable: 'payload',
          label: 'Payload',
          type: 'json_object',
          required: true,
          json_schema: { type: 'object', properties: {} },
        }],
        future_node_field: 1,
      },
    }],
    edges: [],
  }

  const flow = graphToFlow(graph)
  const exported = flowToGraph(flow.nodes, flow.edges)

  assert.equal(exported.nodes[0].data.variables[0].type, 'json_object')
  assert.deepEqual(exported.nodes[0].data.variables[0].json_schema, {
    type: 'object',
    properties: {},
  })
  assert.equal(exported.nodes[0].data.future_node_field, 1)
})

test('Start checklist rejects invalid inputs and accepts a valid configuration', () => {
  const invalidIssues = buildWorkflowChecklist({
    nodes: [
      {
        id: 'start-1',
        data: {
          type: 'start',
          title: '开始',
          variables: [{
            variable: 'document',
            label: 'Document',
            type: 'file',
            required: true,
            allowed_file_types: [],
          }],
        },
      },
      {
        id: 'end-1',
        data: {
          type: 'end',
          title: '结束',
          outputs: [{ variable: 'document', value_selector: ['start-1', 'document'], value_type: 'file' }],
        },
      },
    ],
    edges: [{ id: 'edge-1', source: 'start-1', target: 'end-1' }],
  })
  assert.ok(invalidIssues.some(issue => issue.id === 'start-config-start-1'))

  const validIssues = buildWorkflowChecklist({
    nodes: [
      {
        id: 'start-1',
        data: {
          type: 'start',
          title: '开始',
          variables: [{
            variable: 'document',
            label: 'Document',
            type: 'file',
            required: true,
            allowed_file_types: ['document'],
            allowed_file_upload_methods: ['local_file'],
          }],
        },
      },
      {
        id: 'end-1',
        data: {
          type: 'end',
          title: '结束',
          outputs: [{ variable: 'document', value_selector: ['start-1', 'document'], value_type: 'file' }],
        },
      },
    ],
    edges: [{ id: 'edge-1', source: 'start-1', target: 'end-1' }],
  })
  assert.equal(validIssues.some(issue => issue.level === 'error'), false)
})

test('Start checklist rejects invalid variable contracts', () => {
  const invalidVariables = [
    { variable: '', label: 'Missing key', type: 'text-input' },
    { variable: 'sys.query', label: 'System query', type: 'text-input' },
    { variable: 'choice', label: 'Choice', type: 'select', options: [] },
    { variable: 'payload', label: 'Payload', type: 'json_object', json_schema: '{not-json}' },
    { variable: 'legacy', label: 'Legacy', type: 'json-object' },
  ]

  for (const variable of invalidVariables) {
    const issues = buildWorkflowChecklist({
      nodes: [{ id: 'start-1', data: { type: 'start', title: '开始', variables: [variable] } }],
      edges: [],
    })
    assert.ok(issues.some(issue => issue.id === 'start-config-start-1'), variable.variable || 'missing key')
  }

  const duplicateIssues = buildWorkflowChecklist({
    nodes: [{
      id: 'start-1',
      data: {
        type: 'start',
        title: '开始',
        variables: [
          { variable: 'query', label: 'Query', type: 'text-input' },
          { variable: 'query', label: 'Query again', type: 'paragraph' },
        ],
      },
    }],
    edges: [],
  })
  assert.ok(duplicateIssues.some(issue => issue.id === 'start-config-start-1'))
})

test('Start checklist reports Document Extractor input type conflicts without rewriting Start', () => {
  const graph = {
    nodes: [
      {
        id: 'start-1',
        data: {
          type: 'start',
          title: '开始',
          variables: [{ variable: 'document', label: 'Document', type: 'paragraph' }],
        },
      },
      {
        id: 'extract-1',
        data: {
          type: 'document-extractor',
          title: '文档提取',
          variable_selector: ['start-1', 'document'],
        },
      },
      { id: 'end-1', data: { type: 'end', title: '结束', outputs: [] } },
    ],
    edges: [
      { id: 'edge-1', source: 'start-1', target: 'extract-1' },
      { id: 'edge-2', source: 'extract-1', target: 'end-1' },
    ],
  }

  const invalidIssues = buildWorkflowChecklist(graph)
  assert.ok(invalidIssues.some(issue => issue.id === 'start-extractor-type-extract-1'))
  assert.equal(graph.nodes[0].data.variables[0].type, 'paragraph')

  for (const type of ['file', 'file-list']) {
    graph.nodes[0].data.variables[0] = {
      variable: 'document',
      label: 'Document',
      type,
      allowed_file_types: ['document'],
      allowed_file_upload_methods: ['local_file'],
    }
    const issues = buildWorkflowChecklist(graph)
    assert.equal(issues.some(issue => issue.id === 'start-extractor-type-extract-1'), false)
  }
})
