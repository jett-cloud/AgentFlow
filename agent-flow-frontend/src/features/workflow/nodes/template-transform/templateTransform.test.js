import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  TEMPLATE_TRANSFORM_DEFAULTS,
  TEMPLATE_TRANSFORM_INPUT_TYPES,
  addTemplateVariable,
  buildTemplateRunInputs,
  normalizeTemplateTransformData,
  renameTemplateVariable,
  updateTemplateVariable,
} from './templateTransform.js'

test('new template-transform nodes use the Dify default contract', () => {
  const { newNode } = generateNewNode({ type: 'template-transform', id: 'template-1' })

  assert.deepEqual(TEMPLATE_TRANSFORM_DEFAULTS, { template: '', variables: [] })
  assert.equal(newNode.data.template, '')
  assert.deepEqual(newNode.data.variables, [])
})

test('normalization preserves unknown Dify fields and clones value selectors', () => {
  const source = {
    type: 'template-transform',
    title: 'Template',
    template: '{{ query }}',
    variables: [{ variable: 'query', value_selector: ['start', 'query'], value_type: 'string' }],
    future_field: { enabled: true },
  }

  const normalized = normalizeTemplateTransformData(source)
  normalized.variables[0].value_selector.push('nested')

  assert.deepEqual(normalized.future_field, { enabled: true })
  assert.deepEqual(source.variables[0].value_selector, ['start', 'query'])
})

test('variable mappings can be added, selected, and renamed in the template', () => {
  const added = addTemplateVariable({ template: '', variables: [] })
  const selected = updateTemplateVariable(added, 0, {
    value_selector: ['start', 'query'],
    value_type: 'string',
  })
  const renamed = renameTemplateVariable(
    { ...selected, template: 'Hello {{ query }} and {{query}}' },
    0,
    'message',
  )

  assert.equal(selected.variables[0].variable, 'query')
  assert.equal(selected.variables[0].value_type, 'string')
  assert.equal(renamed.template, 'Hello {{ message }} and {{ message }}')
  assert.equal(renamed.variables[0].variable, 'message')
})

test('template variables accept Dify interpolation value types but reject files', () => {
  assert.equal(TEMPLATE_TRANSFORM_INPUT_TYPES.has('string'), true)
  assert.equal(TEMPLATE_TRANSFORM_INPUT_TYPES.has('array[object]'), true)
  assert.equal(TEMPLATE_TRANSFORM_INPUT_TYPES.has('arrayObject'), true)
  assert.equal(TEMPLATE_TRANSFORM_INPUT_TYPES.has('file'), false)
  assert.equal(TEMPLATE_TRANSFORM_INPUT_TYPES.has('arrayFile'), false)
})

test('DSL round-trip keeps template mappings and unknown fields', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'template-1',
      type: 'custom',
      position: { x: 0, y: 0 },
      data: {
        type: 'template-transform',
        title: 'Template',
        template: '{{ query }}',
        variables: [{ variable: 'query', value_selector: ['start', 'query'] }],
        future_field: 'keep-me',
      },
    }],
    edges: [],
  })
  const exported = flowToGraph(flow.nodes, flow.edges)

  assert.equal(exported.nodes[0].data.future_field, 'keep-me')
  assert.deepEqual(exported.nodes[0].data.variables[0].value_selector, ['start', 'query'])
})

test('template-transform exposes the official string output', () => {
  assert.deepEqual(getNodeOutputVars({
    id: 'template-1',
    data: { type: 'template-transform', title: 'Template' },
  }), [{ variable: 'output', type: 'string', des: '模板渲染结果' }])
})

test('single-node run only submits declared template variable names', () => {
  const inputs = buildTemplateRunInputs({
    variables: [
      { variable: 'query', value_selector: ['start', 'query'] },
      { variable: 'count', value_selector: ['start', 'count'] },
    ],
  }, { query: 'hello', count: 2, ignored: true })

  assert.deepEqual(inputs, { query: 'hello', count: 2 })
})

test('checklist rejects empty, duplicate, invalid, and unbound template variables', () => {
  const nodes = [
    { id: 'start', data: { type: 'start', title: 'Start', variables: [{ variable: 'query', type: 'text-input' }] } },
    {
      id: 'template-1',
      data: {
        type: 'template-transform',
        title: 'Template',
        template: '{{ query }}',
        variables: [
          { variable: 'query', value_selector: ['start', 'query'] },
          { variable: 'query', value_selector: [] },
          { variable: '1bad', value_selector: ['start', 'query'] },
        ],
      },
    },
    { id: 'end', data: { type: 'end', title: 'End', outputs: [] } },
  ]
  const edges = [
    { id: 'e1', source: 'start', target: 'template-1' },
    { id: 'e2', source: 'template-1', target: 'end' },
  ]
  const issues = buildWorkflowChecklist({ nodes, edges })

  assert.ok(issues.some(issue => issue.id === 'template-variable-name-template-1'))
  assert.ok(issues.some(issue => issue.id === 'template-variable-duplicate-template-1'))
  assert.ok(issues.some(issue => issue.id === 'template-variable-value-template-1'))
})
