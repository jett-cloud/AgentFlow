import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  TEMPLATE_TRANSFORM_DEFAULTS,
  TEMPLATE_TRANSFORM_INPUT_TYPES,
  addTemplateVariable,
  buildTemplateRunInputs,
  isValidTemplateVariableSelector,
  normalizeTemplateTransformData,
  renameTemplateVariable,
  updateTemplateVariable,
} from './templateTransform.js'

// 1. generateNewNode 默认合同
test('new template-transform nodes use the Dify default contract', () => {
  const { newNode } = generateNewNode({ type: 'template-transform', id: 'template-1' })

  assert.deepEqual(TEMPLATE_TRANSFORM_DEFAULTS, { template: '', variables: [] })
  assert.deepEqual(newNode.data, {
    ...TEMPLATE_TRANSFORM_DEFAULTS,
    type: 'template-transform',
    title: '模板转换',
  })
})

// 2. 归一化、面板更新与旧/未知字段保留
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

// 3. 输出变量
test('template-transform exposes the official string output', () => {
  assert.deepEqual(getNodeOutputVars({
    id: 'template-1',
    data: { type: 'template-transform', title: 'Template' },
  }), [{ variable: 'output', type: 'string', des: '模板渲染结果' }])
})

// 4. Handle
test('template-transform exposes only the ordinary source Handle', () => {
  assert.deepEqual(getNodeOutputBranches({ type: 'template-transform' }), [
    { id: 'source', name: '', kind: 'normal' },
  ])
})

// 5. DSL round-trip 与单节点运行参数
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

test('single-node run only submits declared template variable names', () => {
  const inputs = buildTemplateRunInputs({
    variables: [
      { variable: 'query', value_selector: ['start', 'query'] },
      { variable: 'count', value_selector: ['start', 'count'] },
    ],
  }, { query: 'hello', count: 2, ignored: true })

  assert.deepEqual(inputs, { query: 'hello', count: 2 })
})

function buildTemplateWorkflow(data) {
  return {
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start', variables: [{ variable: 'query', type: 'text-input' }] } },
      { id: 'template-1', data: { type: 'template-transform', title: 'Template', ...data } },
      { id: 'end', data: { type: 'end', title: 'End', outputs: [] } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'template-1' },
      { id: 'e2', source: 'template-1', target: 'end' },
    ],
  }
}

// 6. checklist 非法与合法配置
test('checklist rejects empty, duplicate, invalid, and unbound template variables', () => {
  const issues = buildWorkflowChecklist(buildTemplateWorkflow({
    template: '{{ query }}',
    variables: [
      { variable: 'query', value_selector: ['start', 'query'] },
      { variable: 'query', value_selector: [] },
      { variable: '1bad', value_selector: ['start', 'query'] },
    ],
  }))

  assert.ok(issues.some(issue => issue.id === 'template-variable-name-template-1'))
  assert.ok(issues.some(issue => issue.id === 'template-variable-duplicate-template-1'))
  assert.ok(issues.some(issue => issue.id === 'template-variable-value-template-1'))
})

test('checklist rejects a single-part template variable selector', () => {
  const issues = buildWorkflowChecklist(buildTemplateWorkflow({
    template: 'Hello {{ name }}',
    variables: [{ variable: 'name', value_selector: ['start'] }],
  }))
  assert.ok(issues.some(issue => issue.id === 'template-variable-value-template-1'))
})

test('checklist rejects a template variable selector with an empty path segment', () => {
  const issues = buildWorkflowChecklist(buildTemplateWorkflow({
    template: 'Hello {{ name }}',
    variables: [{ variable: 'name', value_selector: ['start', ''] }],
  }))
  assert.ok(issues.some(issue => issue.id === 'template-variable-value-template-1'))
})

test('checklist rejects whitespace, null, and numeric selector segments', () => {
  assert.equal(isValidTemplateVariableSelector(['start', '  ']), false)
  assert.equal(isValidTemplateVariableSelector(['start', null]), false)
  assert.equal(isValidTemplateVariableSelector(['start', 123]), false)

  for (const value_selector of [['start', '  '], ['start', null], ['start', 123]]) {
    const issues = buildWorkflowChecklist(buildTemplateWorkflow({
      template: 'Hello {{ name }}',
      variables: [{ variable: 'name', value_selector }],
    }))
    assert.ok(issues.some(issue => issue.id === 'template-variable-value-template-1'))
  }
})

test('normalization keeps illegal selector types for checklist instead of stringifying them', () => {
  const normalized = normalizeTemplateTransformData({
    template: 'Hello {{ name }}',
    variables: [{ variable: 'name', value_selector: ['start', null, 123] }],
  })

  assert.deepEqual(normalized.variables[0].value_selector, ['start', null, 123])
})

test('checklist rejects a template variable name with leading or trailing spaces', () => {
  const issues = buildWorkflowChecklist(buildTemplateWorkflow({
    template: 'Hello {{ name }}',
    variables: [{ variable: ' name ', value_selector: ['start', 'query'] }],
  }))
  assert.ok(issues.some(issue => issue.id === 'template-variable-name-template-1'))
})

test('checklist accepts a 30-character template variable name and rejects 31', () => {
  const valid = buildWorkflowChecklist(buildTemplateWorkflow({
    template: 'Hello {{ name }}',
    variables: [{ variable: 'n'.repeat(30), value_selector: ['start', 'query'] }],
  }))
  assert.equal(valid.filter(issue => issue.nodeId === 'template-1').length, 0)

  const invalid = buildWorkflowChecklist(buildTemplateWorkflow({
    template: 'Hello {{ name }}',
    variables: [{ variable: 'n'.repeat(31), value_selector: ['start', 'query'] }],
  }))
  assert.ok(invalid.some(issue => issue.id === 'template-variable-name-template-1'))
})

test('auto-generated template variable names stay within 30 characters including suffixes', () => {
  const longName = 'n'.repeat(31)
  const named = updateTemplateVariable({ template: '', variables: [{ variable: '', value_selector: [] }] }, 0, {
    value_selector: ['start', longName],
  })
  assert.equal(named.variables[0].variable, 'n'.repeat(30))
  assert.ok(named.variables[0].variable.length <= 30)

  const conflicted = updateTemplateVariable({
    template: '',
    variables: [
      { variable: 'n'.repeat(30), value_selector: ['start', 'query'] },
      { variable: '', value_selector: [] },
    ],
  }, 1, {
    value_selector: ['start', longName],
  })
  assert.equal(conflicted.variables[1].variable.length, 30)
  assert.equal(conflicted.variables[1].variable, `${'n'.repeat(28)}_1`)
  assert.notEqual(conflicted.variables[1].variable, conflicted.variables[0].variable)
})

test('checklist accepts a complete template-transform configuration', () => {
  const issues = buildWorkflowChecklist(buildTemplateWorkflow({
    template: 'Hello {{ query }}',
    variables: [{ variable: 'query', value_selector: ['start', 'query'], value_type: 'string' }],
  }))

  assert.equal(issues.filter(issue => issue.nodeId === 'template-1').length, 0)
})
