import test from 'node:test'
import assert from 'node:assert/strict'
import {
  ToolVarKind,
  buildEmptyToolParameters,
  setToolParamValue,
  toToolParamInput,
  toolParamDisplayValue,
} from './toolParamInputs.js'

test('toToolParamInput upgrades plain strings to mixed', () => {
  assert.deepEqual(toToolParamInput('hello'), { type: ToolVarKind.mixed, value: 'hello' })
  assert.deepEqual(toToolParamInput(null), { type: ToolVarKind.mixed, value: '' })
})

test('toToolParamInput preserves typed objects', () => {
  assert.deepEqual(
    toToolParamInput({ type: 'variable', value: ['llm', 'text'] }),
    { type: ToolVarKind.variable, value: ['llm', 'text'] },
  )
})

test('setToolParamValue writes mixed text payload', () => {
  const next = setToolParamValue({}, 'query', '{{#start.query#}}')
  assert.deepEqual(next.query, { type: ToolVarKind.mixed, value: '{{#start.query#}}' })
})

test('buildEmptyToolParameters seeds schema names', () => {
  const params = buildEmptyToolParameters([{ name: 'q' }, { name: 'limit' }, {}])
  assert.deepEqual(params.q, { type: ToolVarKind.mixed, value: '' })
  assert.deepEqual(params.limit, { type: ToolVarKind.mixed, value: '' })
  assert.equal(Object.keys(params).length, 2)
})

test('toolParamDisplayValue reads nested value', () => {
  assert.equal(toolParamDisplayValue({ type: 'constant', value: 3 }), '3')
  assert.equal(toolParamDisplayValue({ type: 'variable', value: ['a', 'b'] }), 'a.b')
})
