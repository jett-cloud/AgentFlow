import assert from 'node:assert/strict'
import test from 'node:test'
import { canRunBySingle } from './canRunBySingle.js'
import { BlockEnum } from './constants.js'

test('canRunBySingle allows common runnable nodes', () => {
  assert.equal(canRunBySingle(BlockEnum.LLM), true)
  assert.equal(canRunBySingle(BlockEnum.Code), true)
  assert.equal(canRunBySingle(BlockEnum.Start), true)
  assert.equal(canRunBySingle(BlockEnum.IfElse), true)
})

test('canRunBySingle rejects End/Answer and child Assigner', () => {
  assert.equal(canRunBySingle(BlockEnum.End), false)
  assert.equal(canRunBySingle(BlockEnum.Answer), false)
  assert.equal(canRunBySingle(BlockEnum.Assigner, true), false)
  assert.equal(canRunBySingle(BlockEnum.Assigner, false), true)
  assert.equal(canRunBySingle(BlockEnum.VariableAssigner, true), true)
})
