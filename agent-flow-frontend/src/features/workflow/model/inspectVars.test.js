import assert from 'node:assert/strict'
import test from 'node:test'
import {
  canMutateInspectItem,
  formatInspectVarLabel,
  groupInspectVarsByNode,
  mapNodeExecutionsToTracing,
  normalizeWorkflowRunList,
  parseInspectEditValue,
  serializeInspectEditText,
  toInspectPanelItem,
} from './inspectVars.js'

test('groupInspectVarsByNode groups by selector node id', () => {
  const groups = groupInspectVarsByNode([
    { id: '1', selector: ['llm', 'text'], name: 'text' },
    { id: '2', selector: ['llm', 'usage'], name: 'usage' },
    { id: '3', selector: ['start', 'query'], name: 'query' },
  ])
  assert.equal(groups.get('llm').length, 2)
  assert.equal(groups.get('start').length, 1)
})

test('mapNodeExecutionsToTracing preserves I/O fields', () => {
  const tracing = mapNodeExecutionsToTracing({
    data: [{
      node_id: 'n1',
      node_type: 'llm',
      title: 'LLM',
      status: 'succeeded',
      inputs: { a: 1 },
      outputs: { text: 'x' },
      process_data: { m: 1 },
      elapsed_time: 0.5,
      execution_metadata: { total_tokens: 3 },
    }],
  })
  assert.equal(tracing[0].nodeId, 'n1')
  assert.equal(tracing[0].nodeType, 'llm')
  assert.deepEqual(tracing[0].outputs, { text: 'x' })
  assert.equal(tracing[0].executionMetadata.total_tokens, 3)
})

test('normalizeWorkflowRunList and label helpers', () => {
  assert.equal(normalizeWorkflowRunList({ data: [{ id: 'r1' }] }).length, 1)
  assert.equal(formatInspectVarLabel({ name: 'foo' }), 'foo')
  assert.equal(formatInspectVarLabel({ selector: ['n', 'a', 'b'] }), 'a.b')
})

test('toInspectPanelItem keeps id/edited for CRUD', () => {
  const item = toInspectPanelItem({
    id: 'v1',
    name: 'text',
    value_type: 'string',
    value: 'hello',
    edited: true,
  }, 'node-llm', 0)
  assert.equal(item.id, 'v1')
  assert.equal(item.edited, true)
  assert.equal(item.mutable, true)
  assert.equal(item.rawValue, 'hello')
})

test('canMutateInspectItem blocks env/tracing/secret/file', () => {
  assert.equal(canMutateInspectItem({ id: '1', kind: 'env', valueType: 'string' }), false)
  assert.equal(canMutateInspectItem({ id: '1', kind: 'tracing', valueType: 'string' }), false)
  assert.equal(canMutateInspectItem({ id: '1', kind: 'node', valueType: 'secret' }), false)
  assert.equal(canMutateInspectItem({ id: '1', kind: 'node', valueType: 'file' }), false)
  assert.equal(canMutateInspectItem({ kind: 'node', valueType: 'string' }), false)
  assert.equal(canMutateInspectItem({ id: '1', kind: 'node', valueType: 'number' }), true)
})

test('parseInspectEditValue and serializeInspectEditText', () => {
  assert.equal(serializeInspectEditText('hi', 'string'), 'hi')
  assert.equal(serializeInspectEditText(3, 'number'), '3')
  assert.deepEqual(parseInspectEditValue('12.5', 'number'), { ok: true, value: 12.5 })
  assert.equal(parseInspectEditValue('x', 'number').ok, false)
  assert.deepEqual(parseInspectEditValue('true', 'boolean'), { ok: true, value: true })
  assert.deepEqual(parseInspectEditValue('{"a":1}', 'object'), { ok: true, value: { a: 1 } })
  assert.equal(parseInspectEditValue('{', 'object').ok, false)
})
