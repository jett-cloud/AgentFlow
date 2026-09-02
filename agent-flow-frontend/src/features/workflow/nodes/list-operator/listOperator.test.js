import assert from 'node:assert/strict'
import test from 'node:test'

import { getDefaultNodeData } from '../../model/nodeMeta.js'
import { flowToGraph, graphToFlow } from '../../model/dsl.js'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  setListOperatorVariable,
  updateListOperatorSection,
  getListItemType,
  getListFilterOperators,
  listOperatorRequiresConditionValue,
  isListVariableType,
  normalizeListOperatorData,
} from './listOperator.js'

test('new list operator nodes use the complete Dify default contract', () => {
  assert.deepEqual(getDefaultNodeData('list-operator'), {
    type: 'list-operator',
    title: '列表操作',
    variable: [],
    filter_by: { enabled: false, conditions: [] },
    extract_by: { enabled: false, serial: '1' },
    order_by: { enabled: false, key: '', value: 'asc' },
    limit: { enabled: false, size: 10 },
  })
})

test('legacy list operator selectors migrate without silently converting free-text filters', () => {
  assert.deepEqual(normalizeListOperatorData({
    type: 'list-operator',
    title: '旧列表操作',
    variable_selector: ['start', 'items'],
    filter_condition: 'item.score > 0.8',
    custom_dify_field: { keep: true },
  }), {
    type: 'list-operator',
    title: '旧列表操作',
    variable: ['start', 'items'],
    filter_condition: 'item.score > 0.8',
    filter_by: { enabled: false, conditions: [] },
    extract_by: { enabled: false, serial: '1' },
    order_by: { enabled: false, key: '', value: 'asc' },
    limit: { enabled: false, size: 10 },
    custom_dify_field: { keep: true },
  })
})

test('list operator accepts Dify list types and derives item/output types', () => {
  assert.equal(isListVariableType('arrayString'), true)
  assert.equal(isListVariableType('arrayObject'), true)
  assert.equal(isListVariableType('string'), false)
  assert.equal(getListItemType('arrayNumber'), 'number')
  assert.equal(getListItemType('arrayFile'), 'file')

  assert.deepEqual(getNodeOutputVars({
    id: 'list',
    data: {
      type: 'list-operator',
      var_type: 'arrayNumber',
      item_var_type: 'number',
    },
  }), [
    { variable: 'result', type: 'arrayNumber', des: '过滤后的列表' },
    { variable: 'first_record', type: 'number' },
    { variable: 'last_record', type: 'number' },
  ])
})

test('list operator legacy selectors migrate on import and export with official fields', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'list',
      type: 'custom',
      position: { x: 100, y: 100 },
      data: {
        type: 'list-operator',
        title: '列表操作',
        variable_selector: ['start', 'items'],
        filter_condition: 'item != ""',
      },
    }],
    edges: [],
  })

  assert.deepEqual(flow.nodes[0].data.variable, ['start', 'items'])
  assert.equal(flow.nodes[0].data.variable_selector, undefined)
  assert.equal(flow.nodes[0].data.filter_condition, 'item != ""')

  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.deepEqual(exported.nodes[0].data.variable, ['start', 'items'])
  assert.deepEqual(exported.nodes[0].data.extract_by, { enabled: false, serial: '1' })
  assert.deepEqual(exported.nodes[0].data.order_by, { enabled: false, key: '', value: 'asc' })
})

test('list operator panel updates preserve unknown Dify fields and clear resolved legacy filters', () => {
  const selected = setListOperatorVariable({
    type: 'list-operator',
    custom_dify_field: { keep: true },
    filter_condition: 'item != ""',
  }, ['start', 'scores'], 'arrayNumber')

  assert.deepEqual(selected.variable, ['start', 'scores'])
  assert.equal(selected.var_type, 'arrayNumber')
  assert.equal(selected.item_var_type, 'number')
  assert.deepEqual(selected.filter_by.conditions, [{
    key: '',
    comparison_operator: '=',
    value: '',
  }])
  assert.deepEqual(selected.custom_dify_field, { keep: true })

  const configured = updateListOperatorSection(selected, 'filter_by', {
    enabled: true,
    conditions: [{ key: '', comparison_operator: '>', value: 0 }],
  })
  assert.equal(configured.filter_condition, undefined)
  assert.deepEqual(configured.filter_by, {
    enabled: true,
    conditions: [{ key: '', comparison_operator: '>', value: 0 }],
  })
  assert.deepEqual(configured.custom_dify_field, { keep: true })
})

test('list filter operators follow the selected Dify item type', () => {
  assert.deepEqual(getListFilterOperators('number'), ['=', '≠', '>', '<', '≥', '≤', 'empty', 'not empty'])
  assert.deepEqual(getListFilterOperators('boolean'), ['=', '≠', 'empty', 'not empty'])
  assert.ok(getListFilterOperators('string').includes('contains'))
  assert.equal(listOperatorRequiresConditionValue('empty'), false)
  assert.equal(listOperatorRequiresConditionValue('contains'), true)
})

function buildListWorkflow(listData) {
  return {
    nodes: [
      {
        id: 'start',
        data: {
          type: 'start',
          title: '开始',
          variables: [{ variable: 'files', type: 'file-list', label: '文件' }],
        },
      },
      { id: 'list', data: { type: 'list-operator', title: '列表操作', ...listData } },
      { id: 'end', data: { type: 'end', title: '结束' } },
    ],
    edges: [
      { id: 'start-list', source: 'start', target: 'list' },
      { id: 'list-end', source: 'list', target: 'end' },
    ],
  }
}

test('checklist blocks incomplete and unresolved legacy list operator configuration', () => {
  const missing = buildWorkflowChecklist(buildListWorkflow({
    ...getDefaultNodeData('list-operator'),
  }))
  assert.ok(missing.some(issue => issue.id === 'list-variable-list' && issue.level === 'error'))

  const legacy = buildWorkflowChecklist(buildListWorkflow({
    ...getDefaultNodeData('list-operator'),
    variable: ['start', 'files'],
    var_type: 'arrayFile',
    item_var_type: 'file',
    filter_condition: 'item.size > 0',
  }))
  assert.ok(legacy.some(issue => issue.id === 'list-legacy-filter-list' && issue.level === 'error'))
})

test('checklist accepts a complete official list operator configuration', () => {
  const issues = buildWorkflowChecklist(buildListWorkflow({
    ...getDefaultNodeData('list-operator'),
    variable: ['start', 'files'],
    var_type: 'arrayFile',
    item_var_type: 'file',
    filter_by: {
      enabled: true,
      conditions: [{ key: 'size', comparison_operator: '>', value: 0 }],
    },
    order_by: { enabled: true, key: 'size', value: 'desc' },
    limit: { enabled: true, size: 5 },
  }))
  assert.equal(issues.filter(issue => issue.id.startsWith('list-')).length, 0)
})
