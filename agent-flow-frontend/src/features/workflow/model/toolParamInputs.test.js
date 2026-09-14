import test from 'node:test'
import assert from 'node:assert/strict'
import {
  ToolVarKind,
  buildEmptyToolParameters,
  cloneToolValue,
  isFilledNonFileToolParam,
  isValidToolParameterEnvelope,
  setToolParamEnvelope,
  setToolParamValue,
  toToolParamInput,
  toolParamDisplayValue,
  normalizeToolParameter,
} from './toolParamInputs.js'

test('toToolParamInput upgrades plain strings to mixed', () => {
  assert.deepEqual(toToolParamInput('hello'), { type: ToolVarKind.mixed, value: 'hello' })
  assert.deepEqual(toToolParamInput(null), { type: ToolVarKind.mixed, value: '' })
})

test('toToolParamInput preserves typed objects and extra envelope fields', () => {
  const raw = { type: 'variable', value: ['llm', 'text'], future: true }
  const original = structuredClone(raw)
  assert.deepEqual(
    toToolParamInput(raw),
    { future: true, type: ToolVarKind.variable, value: ['llm', 'text'] },
  )
  assert.deepEqual(raw, original)
})

test('normalizeToolParameter keeps false, 0, empty string, and nested extras', () => {
  assert.equal(normalizeToolParameter({ type: 'constant', value: false }).value, false)
  assert.equal(normalizeToolParameter({ type: 'constant', value: 0 }).value, 0)
  assert.equal(normalizeToolParameter({ type: 'constant', value: '' }).value, '')
  assert.deepEqual(normalizeToolParameter({ type: 'constant', value: [] }).value, [])
  const nested = { type: 'mixed', value: 'x', extra: { keep: 1 } }
  const copy = normalizeToolParameter(nested)
  copy.extra.keep = 2
  assert.equal(nested.extra.keep, 1)
})

test('setToolParamValue writes a selector for a complete reference', () => {
  const next = setToolParamValue({}, 'query', '{{#start.query#}}')
  assert.deepEqual(next.query, { type: ToolVarKind.variable, value: ['start', 'query'] })
})

test('setToolParamValue keeps mixed prefixes and constant false/0', () => {
  const text = 'prefix {{#start.query#}}'
  assert.deepEqual(setToolParamValue({}, 'query', text).query, { type: 'mixed', value: text })
  assert.deepEqual(setToolParamEnvelope({}, 'flag', { type: 'constant', value: false }).flag, {
    type: 'constant',
    value: false,
  })
  assert.equal(isFilledNonFileToolParam({ type: 'constant', value: false }), true)
  assert.equal(isFilledNonFileToolParam({ type: 'constant', value: 0 }), true)
  assert.equal(isFilledNonFileToolParam({ type: 'mixed', value: '' }), false)
})

test('buildEmptyToolParameters seeds schema names without leaking secret defaults', () => {
  const params = buildEmptyToolParameters([
    { name: 'q' },
    { name: 'limit', type: 'number', form: 'form', default: 0 },
    { name: 'token', type: 'secret-input', default: 'hidden' },
    {},
  ])
  assert.deepEqual(params.q, { type: ToolVarKind.mixed, value: '' })
  assert.deepEqual(params.limit, { type: ToolVarKind.constant, value: 0 })
  assert.deepEqual(params.token, { type: ToolVarKind.mixed, value: '' })
  assert.equal(Object.keys(params).length, 3)
})

test('toolParamDisplayValue reads nested value', () => {
  assert.equal(toolParamDisplayValue({ type: 'constant', value: 3 }), '3')
  assert.equal(toolParamDisplayValue({ type: 'variable', value: ['a', 'b'] }), '{{#a.b#}}')
})

test('image selectors survive an editor round trip and replacement', () => {
  const params = { image: { type: 'variable', value: ['1788868519196002', 'image'] } }
  assert.deepEqual(setToolParamValue(params, 'image', toolParamDisplayValue(params.image)), params)
  assert.deepEqual(setToolParamValue(params, 'image', '{{#cutout.files#}}').image,
    { type: 'variable', value: ['cutout', 'files'] })
})

test('mixed prompts retain references and model constants are not inferred as selectors', () => {
  const text = '根据 {{#start.description#}} 处理 {{#cutout.text#}}'
  assert.deepEqual(setToolParamValue({}, 'prompt', text).prompt, { type: 'mixed', value: text })
  assert.deepEqual(setToolParamValue({ prompt: { type: 'constant', value: '处理图片' } }, 'prompt', text).prompt,
    { type: 'mixed', value: text })
  const params = { model: { type: 'constant', value: 'v1.0' } }
  assert.deepEqual(setToolParamValue(params, 'model', 'v2.0').model, { type: 'constant', value: 'v2.0' })
  assert.deepEqual(setToolParamValue({}, 'prompt', 'start.description').prompt,
    { type: 'mixed', value: 'start.description' })
})

test('cloneToolValue copies arrays and objects without mutating the original', () => {
  const original = { items: [1, { n: 2 }] }
  const cloned = cloneToolValue(original)
  cloned.items[1].n = 9
  assert.equal(original.items[1].n, 2)
})

test('envelope validation requires typed Graphon values', () => {
  assert.equal(isValidToolParameterEnvelope({ type: 'variable', value: ['start', 'query'] }), true)
  assert.equal(isValidToolParameterEnvelope({ type: 'variable', value: ['start'] }), false)
  assert.equal(isValidToolParameterEnvelope({ type: 'mixed', value: 'x' }), true)
  assert.equal(isValidToolParameterEnvelope({ type: 'mixed', value: 1 }), false)
  assert.equal(isValidToolParameterEnvelope({ type: 'constant', value: { k: 1 } }), true)
  assert.equal(isValidToolParameterEnvelope({ type: 'constant', value: { optional: null } }), true)
  assert.equal(isValidToolParameterEnvelope({ type: 'constant', value: [null, { nested: null }] }), true)
  assert.equal(isValidToolParameterEnvelope({ type: 'constant', value: null }), false)
  assert.equal(isValidToolParameterEnvelope({ type: 'constant', value: Number.NaN }), false)
  assert.equal(isValidToolParameterEnvelope({ type: 'constant', value: Number.POSITIVE_INFINITY }), false)
})
