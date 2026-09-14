import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  HTTP_REQUEST_DEFAULTS,
  applyHttpRequestField,
  convertHttpBody,
  createHttpBodyItem,
  isHttpFileVariable,
  normalizeHttpRequestData,
  setHttpErrorStrategy,
  updateHttpDefaultValue,
  buildHttpRequestRunInputs,
} from './httpRequest.js'

test('new HTTP request nodes use Dify defaults', () => {
  const { newNode } = generateNewNode({ type: 'http-request', id: 'http-1' })
  assert.deepEqual(newNode.data, { type: 'http-request', title: 'HTTP 请求', ...HTTP_REQUEST_DEFAULTS })
})

test('normalization migrates legacy payloads and preserves unknown node fields', () => {
  const normalized = normalizeHttpRequestData({
    type: 'http-request', method: 'OPTIONS', body: { type: 'json', data: '{"x":1}' }, future: true,
  })
  assert.equal(normalized.method, 'options')
  assert.deepEqual(normalized.body.data, [{ type: 'text', key: '', value: '{"x":1}' }])
  assert.equal(normalized.future, true)

  const authorized = normalizeHttpRequestData({ authorization: { type: 'api-key', config: null } })
  assert.deepEqual(authorized.authorization, {
    type: 'api-key',
    config: { type: 'basic', api_key: '', header: '' },
  })
})

test('HTTP outputs match the backend declaration', () => {
  const outputs = getNodeOutputVars({ data: { type: 'http-request' } })
  assert.deepEqual(outputs.slice(0, 3), [
    { variable: 'body', type: 'string' }, { variable: 'status_code', type: 'number' }, { variable: 'headers', type: 'object' },
  ])
  assert.equal(outputs[3].variable, 'files')
  assert.equal(outputs[3].type, 'arrayFile')
  assert.ok(outputs[3].children.some(child => child.variable === 'url' && child.type === 'string'))
})

test('HTTP request exposes the normal and failure Handles only when configured', () => {
  assert.deepEqual(getNodeOutputBranches({ type: 'http-request' }), [{ id: 'source', name: '', kind: 'normal' }])
  assert.deepEqual(getNodeOutputBranches({ type: 'http-request', error_strategy: 'fail-branch' }), [
    { id: 'source', name: '', kind: 'normal' },
    { id: 'fail-branch', name: '失败', kind: 'failure' },
  ])
})

test('graphToFlow and flowToGraph retain the complete HTTP contract', () => {
  const data = {
    type: 'http-request', title: 'HTTP', variables: [{ variable: 'token', value_selector: ['start', 'token'] }],
    method: 'post', url: 'https://example.com',
    authorization: { type: 'api-key', config: { type: 'bearer', api_key: '{{#start.token#}}', header: 'Authorization' } },
    headers: 'Accept: application/json', params: 'page=1', body: { type: 'json', data: [{ key: '', type: 'text', value: '{"ok":true}' }] },
    ssl_verify: false, timeout: { connect: 2, read: 3, write: 4, max_connect_timeout: 0, max_read_timeout: 30, max_write_timeout: 0 },
    retry_config: { retry_enabled: true, max_retries: 2, retry_interval: 250 }, future: 1,
  }
  const flow = graphToFlow({ nodes: [{ id: 'http-1', type: 'custom', data }], edges: [] })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.deepEqual(exported.nodes[0].data, data)
  assert.deepEqual(buildHttpRequestRunInputs({ query: 'x', ignored: true }, ['query']), { query: 'x' })
})

test('form-data and urlencoded keep keyed items; binary keeps the file selector', () => {
  const keyed = convertHttpBody({
    type: 'json',
    charset: 'utf-8',
    data: [{ type: 'text', key: '', value: '{"ok":true}', extra_item: true }],
  }, 'form-data')
  assert.equal(keyed.type, 'form-data')
  assert.equal(keyed.charset, 'utf-8')
  assert.equal(keyed.data[0].key, '')
  assert.equal(keyed.data[0].value, '{"ok":true}')
  assert.equal(keyed.data[0].extra_item, true)

  const switched = convertHttpBody({
    type: 'form-data',
    data: [{ type: 'text', key: 'q', value: '1', extra_item: true }, { type: 'file', key: 'doc', file: ['start', 'file'] }],
  }, 'x-www-form-urlencoded')
  assert.deepEqual(switched.data.map(item => [item.key, item.type, item.value || item.file, item.extra_item]), [
    ['q', 'text', '1', true],
    ['doc', 'file', ['start', 'file'], undefined],
  ])

  const binary = convertHttpBody({
    type: 'form-data',
    data: [{ type: 'file', key: 'doc', file: ['start', 'file'], extra_item: true }],
  }, 'binary')
  assert.equal(binary.type, 'binary')
  assert.deepEqual(binary.data[0].file, ['start', 'file'])
  assert.equal(binary.data[0].extra_item, true)
  assert.deepEqual(createHttpBodyItem('file'), { type: 'file', key: '', file: [] })
  assert.equal(isHttpFileVariable({ type: 'file' }), true)
  assert.equal(isHttpFileVariable({ type: 'string' }), false)
})

test('editing URL does not drop unknown fields inside body or authorization', () => {
  const patched = applyHttpRequestField({
    type: 'http-request',
    url: 'https://a.example',
    authorization: {
      type: 'api-key',
      realm: 'keep-auth',
      config: { type: 'bearer', api_key: 'secret', header: 'Authorization', extra_auth: 1 },
    },
    body: {
      type: 'form-data',
      charset: 'utf-8',
      data: [{ type: 'text', key: 'q', value: '1', extra_item: true }],
    },
  }, 'url', 'https://b.example')

  assert.equal(patched.url, 'https://b.example')
  assert.equal(patched.authorization.realm, 'keep-auth')
  assert.equal(patched.authorization.config.extra_auth, 1)
  assert.equal(patched.body.charset, 'utf-8')
  assert.equal(patched.body.data[0].key, 'q')
  assert.equal(patched.body.data[0].extra_item, true)
})

test('error strategy can open fail-branch without dropping HTTP body extras', () => {
  const withBranch = setHttpErrorStrategy({
    type: 'http-request',
    url: 'https://example.com',
    body: { type: 'json', charset: 'utf-8', data: [{ type: 'text', value: '{}' }] },
  }, 'fail-branch')
  assert.equal(withBranch.error_strategy, 'fail-branch')
  assert.equal(withBranch.body.charset, 'utf-8')
  assert.equal(setHttpErrorStrategy(withBranch, 'none').error_strategy, undefined)

  const withDefaults = setHttpErrorStrategy(withBranch, 'default-value')
  assert.deepEqual(withDefaults.default_value.map(item => item.key), ['body', 'status_code', 'headers', 'files'])
  assert.equal(updateHttpDefaultValue(withDefaults, 'body', 'fallback').default_value[0].value, 'fallback')
})

test('checklist rejects incomplete HTTP requests and accepts a complete one', () => {
  const start = { id: 'start', data: { type: 'start' } }
  const invalid = {
    id: 'http-1',
    data: {
      type: 'http-request', title: 'HTTP', url: '',
      authorization: { type: 'api-key', config: { type: 'basic', api_key: '' } },
      body: { type: 'binary', data: [] },
    },
  }
  const invalidIssues = buildWorkflowChecklist({ nodes: [start, invalid], edges: [{ source: 'start', target: 'http-1' }] })
  assert.ok(invalidIssues.some(issue => issue.id === 'http-url-http-1'))
  assert.ok(invalidIssues.some(issue => issue.id === 'http-auth-http-1'))
  assert.ok(invalidIssues.some(issue => issue.id === 'http-binary-http-1'))

  const valid = {
    id: 'http-2',
    data: {
      ...HTTP_REQUEST_DEFAULTS, type: 'http-request', title: 'HTTP', url: 'https://example.com',
      authorization: { type: 'api-key', config: { type: 'bearer', api_key: 'secret', header: 'Authorization' } },
    },
  }
  const validIssues = buildWorkflowChecklist({ nodes: [start, valid], edges: [{ source: 'start', target: 'http-2' }] })
  assert.equal(validIssues.filter(issue => issue.nodeId === 'http-2').length, 0)
})
