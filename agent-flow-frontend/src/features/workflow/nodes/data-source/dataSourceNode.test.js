import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  DATA_SOURCE_DEFAULTS,
  applyDataSourceSelection,
  flattenDataSourceCatalog,
  getDataSourceValidationErrors,
  normalizeDataSourceData,
} from './dataSourceNode.js'

const provider = {
  plugin_id: 'langgenius/notion',
  plugin_unique_identifier: 'langgenius/notion:1.0.0@dify',
  provider: 'notion',
  is_authorized: true,
  declaration: {
    provider_type: 'online_document',
    identity: { name: 'notion', label: { zh_Hans: 'Notion' } },
    datasources: [{
      identity: { name: 'pages', label: { zh_Hans: '页面' } },
      parameters: [{ name: 'workspace', type: 'string', required: true }],
      output_schema: {
        type: 'object',
        properties: {
          documents: { type: 'array', items: { type: 'object' }, description: '文档' },
        },
      },
    }],
  },
}

test('new datasource nodes use Dify defaults', () => {
  const { newNode } = generateNewNode({ type: 'datasource', id: 'ds-1' })
  assert.deepEqual(newNode.data, {
    type: 'datasource',
    title: '数据源',
    ...DATA_SOURCE_DEFAULTS,
  })
})

test('catalog selection writes official fields and seeds declared parameters', () => {
  const options = flattenDataSourceCatalog([provider])
  assert.equal(options.length, 1)
  const selected = applyDataSourceSelection({ future: true }, options[0])
  assert.equal(selected.plugin_id, 'langgenius/notion')
  assert.equal(selected.provider_type, 'online_document')
  assert.equal(selected.provider_name, 'notion')
  assert.equal(selected.datasource_name, 'pages')
  assert.equal(selected.datasource_label, '页面')
  assert.deepEqual(selected.datasource_parameters.workspace, { type: 'mixed', value: '' })
  assert.equal(selected.future, true)
})

test('normalization migrates legacy fields and preserves unknown official fields', () => {
  const normalized = normalizeDataSourceData({
    source_name: 'pages',
    config: { recursive: true },
    datasource_parameters: { workspace: 'main' },
    future: { keep: true },
  })
  assert.equal(normalized.datasource_name, 'pages')
  assert.deepEqual(normalized.datasource_configurations, { recursive: true })
  assert.deepEqual(normalized.datasource_parameters.workspace, { type: 'mixed', value: 'main' })
  assert.equal(normalized.source_name, undefined)
  assert.equal(normalized.config, undefined)
  assert.deepEqual(normalized.future, { keep: true })
})

test('validation checks selection, authorization, and required declared parameters', () => {
  const option = flattenDataSourceCatalog([provider])[0]
  const selected = applyDataSourceSelection({}, option)
  assert.deepEqual(getDataSourceValidationErrors(selected), ['必填参数“workspace”未填写'])
  assert.deepEqual(getDataSourceValidationErrors({
    ...selected,
    datasource_parameters: { workspace: { type: 'constant', value: 'main' } },
  }), [])
  assert.ok(getDataSourceValidationErrors({ ...selected, _datasourceAuthorized: false }).includes('数据源尚未授权'))
})

test('DSL keeps official fields, strips catalog metadata, and checklist rejects incomplete selection', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'ds-1',
      type: 'custom',
      data: {
        type: 'datasource',
        plugin_id: 'langgenius/notion',
        provider_type: 'online_document',
        provider_name: 'notion',
        datasource_name: 'pages',
        datasource_label: '页面',
        datasource_parameters: {},
        datasource_configurations: {},
        future: 1,
        _datasourceAuthorized: true,
      },
    }],
    edges: [],
  })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.future, 1)
  assert.equal(exported.nodes[0].data._datasourceAuthorized, undefined)

  const issues = buildWorkflowChecklist({
    nodes: [{ id: 'ds-empty', data: { type: 'datasource', title: '数据源' } }],
    edges: [],
  })
  assert.ok(issues.some(issue => issue.id === 'datasource-ds-empty'))
})

test('datasource exposes common, local file, and declared schema outputs', () => {
  const vars = getNodeOutputVars({
    id: 'ds-1',
    data: {
      type: 'datasource',
      provider_type: 'local_file',
      _datasourceOutputSchema: provider.declaration.datasources[0].output_schema,
    },
  })
  assert.equal(vars.find(item => item.variable === 'datasource_type')?.type, 'string')
  assert.equal(vars.find(item => item.variable === 'file')?.type, 'file')
  assert.equal(vars.find(item => item.variable === 'documents')?.type, 'arrayObject')
})
