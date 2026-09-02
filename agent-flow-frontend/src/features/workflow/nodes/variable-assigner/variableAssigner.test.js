import assert from 'node:assert/strict'
import test from 'node:test'

import { BlockEnum } from '../../model/constants.js'
import { getDefaultNodeData, SELECTABLE_BLOCKS } from '../../model/nodeMeta.js'
import {
  createVariableAssignment,
  getAssignmentSourceSelector,
  getAssignmentTargetSelector,
  normalizeVariableAssignment,
} from './variableAssigner.js'

test('normalizes the legacy text fields into Dify v2 selector fields', () => {
  const normalized = normalizeVariableAssignment({
    target_variable: 'history',
    value: '{{#llm-node.text#}}',
  })

  assert.deepEqual(normalized, {
    variable_selector: ['conversation', 'history'],
    input_type: 'variable',
    operation: 'over-write',
    value: ['llm-node', 'text'],
    write_mode: 'over-write',
  })
  assert.deepEqual(getAssignmentTargetSelector(normalized), ['conversation', 'history'])
  assert.deepEqual(getAssignmentSourceSelector(normalized), ['llm-node', 'text'])
})

test('creates an overwrite assignment from the two picker selections', () => {
  assert.deepEqual(
    createVariableAssignment(['conversation', 'history'], ['llm-node', 'text']),
    {
      variable_selector: ['conversation', 'history'],
      input_type: 'variable',
      operation: 'over-write',
      value: ['llm-node', 'text'],
      write_mode: 'over-write',
    },
  )
})

test('keeps existing constant assignments intact while normalizing stored items', () => {
  assert.deepEqual(normalizeVariableAssignment({
    variable_selector: ['conversation', 'count'],
    input_type: 'constant',
    operation: 'set',
    value: 3,
  }), {
    variable_selector: ['conversation', 'count'],
    input_type: 'constant',
    operation: 'set',
    value: 3,
    write_mode: 'set',
  })
})

test('new variable assignment and aggregator nodes use the two official Dify types', () => {
  assert.equal(BlockEnum.Assigner, 'assigner')
  assert.equal(BlockEnum.VariableAssigner, 'variable-assigner')
  assert.equal(SELECTABLE_BLOCKS.includes(BlockEnum.Assigner), true)
  assert.equal(SELECTABLE_BLOCKS.includes(BlockEnum.VariableAssigner), true)
  assert.deepEqual(getDefaultNodeData(BlockEnum.Assigner), {
    type: 'assigner',
    title: '变量赋值',
    version: '2',
    items: [],
  })
  assert.deepEqual(getDefaultNodeData(BlockEnum.VariableAssigner), {
    type: 'variable-assigner',
    title: '变量聚合器',
    output_type: 'any',
    variables: [],
    advanced_settings: {
      group_enabled: false,
      groups: [],
    },
  })
})
