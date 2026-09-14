import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import {
  buildBreakConditionPatch,
  canonicalizeLoopVarType,
  createLoopEntityId,
  defaultLoopConstant,
  getLoopOperators,
  isLoopConditionComplete,
  isLoopConstantValueValid,
  isLoopVariableSource,
  isValidLoopVariableLabel,
  normalizeLoopData,
} from './loopNode.js'

test('loop variable aliases persist as Graphon types', () => {
  assert.equal(canonicalizeLoopVarType('arrayString'), 'array[string]')
  assert.equal(canonicalizeLoopVarType('arrayNumber'), 'array[number]')
  assert.equal(canonicalizeLoopVarType('arrayBoolean'), 'array[boolean]')
  assert.equal(canonicalizeLoopVarType('arrayObject'), 'array[object]')
  assert.equal(canonicalizeLoopVarType('integer'), 'number')
})

test('loop operators follow the official type mapping', () => {
  assert.deepEqual(getLoopOperators('number')[0], '=')
  assert.ok(getLoopOperators('string').includes('contains'))
  assert.deepEqual(getLoopOperators('object'), ['empty', 'not empty'])
  assert.deepEqual(getLoopOperators('array[string]'), ['contains', 'not contains', 'empty', 'not empty'])
  assert.deepEqual(getLoopOperators('file'), ['exists', 'not exists'])
  assert.equal(getLoopOperators('arrayFile').includes('all of'), false)
})

test('normalizeLoopData migrates max_iterations and keeps 0/false', () => {
  const normalized = normalizeLoopData({
    max_iterations: 4,
    loop_variables: [
      { id: 'n', label: 'count', var_type: 'number', value_type: 'constant', value: 0 },
      { id: 'b', label: 'ok', var_type: 'boolean', value_type: 'constant', value: false },
    ],
    future: true,
  })
  assert.equal(normalized.loop_count, 4)
  assert.equal(normalized.max_iterations, undefined)
  assert.equal(normalized.loop_variables[0].value, 0)
  assert.equal(normalized.loop_variables[1].value, false)
  assert.equal(normalized.future, true)
})

test('normalizeLoopData does not disguise illegal constants or names', () => {
  const normalized = normalizeLoopData({
    loop_count: 0,
    loop_variables: [
      { label: '1bad', var_type: 'number', value_type: 'constant', value: 'nope' },
      { label: 'dup', var_type: 'arrayString', value_type: 'constant', value: { x: 1 } },
    ],
  })
  assert.equal(normalized.loop_count, 0)
  assert.equal(normalized.loop_variables[0].label, '1bad')
  assert.equal(normalized.loop_variables[0].value, 'nope')
  assert.equal(normalized.loop_variables[1].var_type, 'array[string]')
  assert.deepEqual(normalized.loop_variables[1].value, { x: 1 })
})

test('normalizeLoopData only defaults a missing value_type to constant', () => {
  const normalized = normalizeLoopData({
    loop_variables: [
      { label: 'legacy', var_type: 'string', value: 'ok' },
      { label: 'dirty', var_type: 'number', value_type: 'bogus', value: 1 },
      { label: 'ref', var_type: 'string', value_type: 'variable', value: ['start', 'q'] },
    ],
  })
  assert.equal(normalized.loop_variables[0].value_type, 'constant')
  assert.equal(normalized.loop_variables[1].value_type, 'bogus')
  assert.equal(normalized.loop_variables[2].value_type, 'variable')
})

test('loop constant values must match the declared Graphon type', () => {
  assert.equal(isLoopConstantValueValid('number', 1), true)
  assert.equal(isLoopConstantValueValid('number', 'nope'), false)
  assert.equal(isLoopConstantValueValid('boolean', false), true)
  assert.equal(isLoopConstantValueValid('boolean', 'no'), false)
  assert.equal(isLoopConstantValueValid('array[string]', { x: 1 }), false)
  assert.equal(isLoopConstantValueValid('array[string]', ['ok']), true)
  assert.equal(isLoopConstantValueValid('object', []), false)
})

test('unknown break-condition types do not inherit default operators', () => {
  assert.deepEqual(getLoopOperators('bogus'), [])
  assert.equal(isLoopConditionComplete({
    variable_selector: ['loop', 'count'],
    varType: 'bogus',
    comparison_operator: '>',
    value: 1,
  }), false)
})

test('LoopPanel controls expose stable accessible names', () => {
  const source = readFileSync(new URL('./LoopPanel.vue', import.meta.url), 'utf8')
  assert.match(source, /aria-label="最大循环上限次数"/)
  assert.match(source, /:aria-label="`循环变量 \$\{variableName\(variable, index\)\} 的名称`"/)
  assert.match(source, /:aria-label="`循环变量 \$\{variableName\(variable, index\)\} 的类型`"/)
  assert.match(source, /:aria-label="`循环变量 \$\{variableName\(variable, index\)\} 的值来源`"/)
  assert.match(source, /aria-label="退出条件逻辑"/)
  assert.match(source, /:aria-label="`退出条件 \$\{index \+ 1\} 的运算符`"/)
})

test('zero and false complete numeric and boolean conditions', () => {
  assert.equal(isLoopConditionComplete({
    variable_selector: ['loop', 'count'],
    varType: 'number',
    comparison_operator: '=',
    value: 0,
  }), true)
  assert.equal(isLoopConditionComplete({
    variable_selector: ['loop', 'ok'],
    varType: 'boolean',
    comparison_operator: 'is',
    value: false,
  }), true)
  assert.equal(isLoopConditionComplete({
    variable_selector: ['loop', 'count'],
    varType: 'number',
    comparison_operator: 'contains',
    value: 1,
  }), false)
})

test('break condition patch writes selector type operator and value together', () => {
  assert.deepEqual(buildBreakConditionPatch(['child', 'score'], { type: 'number' }), {
    variable_selector: ['child', 'score'],
    varType: 'number',
    comparison_operator: '=',
    value: 0,
  })
  assert.equal(isLoopVariableSource({ type: 'arrayNumber' }, 'array[number]'), true)
  assert.equal(isValidLoopVariableLabel('count'), true)
  assert.equal(isValidLoopVariableLabel('1bad'), false)
  assert.equal(defaultLoopConstant('boolean'), false)
  assert.match(createLoopEntityId(), /^[0-9a-f-]{36}$/i)
})
