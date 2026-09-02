import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getNodeErrorStrategy,
  updateNodeErrorStrategy,
} from './nodeErrorStrategy.js'

test('reads compatible failure strategy spellings', () => {
  assert.equal(getNodeErrorStrategy({ error_strategy: 'failBranch' }), 'failBranch')
  assert.equal(getNodeErrorStrategy({ error_handle_mode: 'fail-branch' }), 'fail-branch')
  assert.equal(getNodeErrorStrategy({}), 'none')
})

test('writes the selected strategy into node data without dropping other fields', () => {
  assert.deepEqual(updateNodeErrorStrategy({
    type: 'llm',
    title: '模型',
    model: { name: 'gpt-4o' },
  }, 'failBranch'), {
    type: 'llm',
    title: '模型',
    model: { name: 'gpt-4o' },
    error_strategy: 'failBranch',
  })
})
