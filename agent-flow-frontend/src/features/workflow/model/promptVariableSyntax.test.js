import test from 'node:test'
import assert from 'node:assert/strict'
import {
  detectBraceTrigger,
  filterVarGroups,
  formatWorkflowVarToken,
  insertAtRange,
} from './promptVariableSyntax.js'

test('formatWorkflowVarToken builds Dify selector token', () => {
  assert.equal(formatWorkflowVarToken(['llm-1', 'text']), '{{#llm-1.text#}}')
  assert.equal(formatWorkflowVarToken(['env', 'API_KEY']), '{{#env.API_KEY#}}')
  assert.equal(formatWorkflowVarToken([]), '')
})

test('detectBraceTrigger finds open brace and query', () => {
  assert.deepEqual(detectBraceTrigger('Hello {que', 10), { start: 6, query: 'que' })
  assert.equal(detectBraceTrigger('Hello {{#x#}}', 13), null)
  assert.equal(detectBraceTrigger('no brace', 8), null)
})

test('insertAtRange replaces trigger with token', () => {
  const result = insertAtRange('Say {na', 4, 7, '{{#start.name#}}')
  assert.equal(result.text, 'Say {{#start.name#}}')
  assert.equal(result.caret, 20)
})

test('insertAtRange inserts at start, middle, selection, and end', () => {
  assert.deepEqual(insertAtRange('world', 0, 0, 'hello '), { text: 'hello world', caret: 6 })
  assert.deepEqual(insertAtRange('ac', 1, 1, 'b'), { text: 'abc', caret: 2 })
  assert.deepEqual(insertAtRange('aXXXc', 1, 4, 'b'), { text: 'abc', caret: 2 })
  assert.deepEqual(insertAtRange('ab', 2, 2, 'c'), { text: 'abc', caret: 3 })
})

test('filterVarGroups filters by query', () => {
  const groups = [
    {
      nodeId: 'start',
      title: 'Start',
      vars: [
        { variable: 'query', type: 'string' },
        { variable: 'user_name', type: 'string' },
      ],
    },
  ]
  const filtered = filterVarGroups(groups, 'user')
  assert.equal(filtered.length, 1)
  assert.deepEqual(filtered[0].vars.map(v => v.variable), ['user_name'])
})
