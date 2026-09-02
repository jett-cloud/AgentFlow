import assert from 'node:assert/strict'
import test from 'node:test'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { TOOL_DEFAULTS, isToolConfigured, normalizeToolNodeData } from './toolNode.js'

test('new Tool nodes use Dify provider and parameter defaults', () => {
  const { newNode } = generateNewNode({ type: 'tool', id: 'tool-1' })
  assert.deepEqual(newNode.data, { type: 'tool', title: '工具', ...TOOL_DEFAULTS })
})

test('Tool normalization maps plugin provider_type to builtin', () => {
  const data = normalizeToolNodeData({
    provider_id: 'ghy/doubao-image/doubao-image',
    provider_type: 'plugin',
    tool_name: 'image_gerenate_image',
  })
  assert.equal(data.provider_type, 'builtin')
  assert.equal(data.provider_id, 'ghy/doubao-image/doubao-image')
  assert.equal(data.tool_name, 'image_gerenate_image')
})

test('Tool normalization preserves unknown fields and rejects partial selection', () => {
  const data = normalizeToolNodeData({ provider_id: 'p', toolName: 'search', future_field: { keep: true } })
  assert.equal(data.tool_name, 'search')
  assert.deepEqual(data.future_field, { keep: true })
  assert.equal(isToolConfigured(data), true)
  assert.equal(isToolConfigured({ provider_id: 'p' }), false)
})

test('Tool DSL round-trip preserves catalog and credentials data', () => {
  const flow = graphToFlow({ nodes: [{ id: 'tool-1', type: 'custom', data: { type: 'tool', provider_id: 'p', tool_name: 'search', credential_id: 'c', future: 1 } }], edges: [] })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.credential_id, 'c')
  assert.equal(exported.nodes[0].data.future, 1)
})

test('graph load rewrites leftover plugin provider_type to builtin', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'tool-1',
      type: 'custom',
      data: {
        type: 'tool',
        provider_id: 'ghy/doubao-image/doubao-image',
        provider_type: 'plugin',
        tool_name: 'image_gerenate_image',
      },
    }],
    edges: [],
  })
  assert.equal(flow.nodes[0].data.provider_type, 'builtin')
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.provider_type, 'builtin')
})

test('Checklist catches incomplete Tool catalog selection', () => {
  const nodes = [{ id: 'start', data: { type: 'start' } }, { id: 'tool-1', data: { type: 'tool', title: '工具', provider_id: 'p' } }]
  const issues = buildWorkflowChecklist({ nodes, edges: [{ source: 'start', target: 'tool-1' }] })
  assert.ok(issues.some(issue => issue.id === 'tool-tool-1' && issue.level === 'error'))
})
