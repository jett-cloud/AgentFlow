import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  HTTP_REQUEST_DEFAULTS,
  normalizeHttpRequestData,
  buildHttpRequestRunInputs,
} from './httpRequest.js'

test('new HTTP request nodes use Dify defaults', () => {
  const { newNode } = generateNewNode({ type: 'http-request', id: 'http-1' })
  assert.deepEqual(newNode.data, { type: 'http-request', title: 'HTTP 请求', ...HTTP_REQUEST_DEFAULTS })
})

test('normalization preserves unknown fields and official body payload', () => {
  const normalized = normalizeHttpRequestData({
    type: 'http-request', method: 'POST', body: { type: 'json', data: [{ key: 'x', type: 'text', value: '1' }] }, future: true,
  })
  assert.equal(normalized.method, 'post')
  assert.deepEqual(normalized.body.data, [{ key: 'x', type: 'text', value: '1' }])
  assert.equal(normalized.future, true)
})

test('HTTP outputs and checklist follow the official contract', () => {
  const outputs = getNodeOutputVars({ data: { type: 'http-request' } })
  assert.deepEqual(outputs.slice(0, 3), [
    { variable: 'body', type: 'string' }, { variable: 'status_code', type: 'number' }, { variable: 'headers', type: 'object' },
  ])
  assert.equal(outputs[3].variable, 'files')
  assert.equal(outputs[3].type, 'arrayFile')
  const nodes = [{ id: 'start', data: { type: 'start' } }, { id: 'http-1', data: { type: 'http-request', title: 'HTTP' } }]
  const issues = buildWorkflowChecklist({ nodes, edges: [{ source: 'start', target: 'http-1' }] })
  assert.ok(issues.some(issue => issue.id === 'http-url-http-1' && issue.level === 'error'))
})

test('DSL round-trip and run inputs retain official fields', () => {
  const flow = graphToFlow({ nodes: [{ id: 'http-1', type: 'custom', data: { type: 'http-request', url: 'https://x', future: 1 } }], edges: [] })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.future, 1)
  assert.deepEqual(buildHttpRequestRunInputs({ query: 'x', ignored: true }, ['query']), { query: 'x' })
})
