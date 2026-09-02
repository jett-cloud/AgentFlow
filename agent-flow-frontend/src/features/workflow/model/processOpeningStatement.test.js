import test from 'node:test'
import assert from 'node:assert/strict'
import {
  processOpeningStatement,
  processOpeningSuggestedQuestions,
} from './processOpeningStatement.js'

test('processOpeningStatement returns empty string if falsy', () => {
  assert.equal(processOpeningStatement('', {}, []), '')
})

test('processOpeningStatement replaces variables with input values', () => {
  assert.equal(
    processOpeningStatement('Hello {{name}}', { name: 'Alice' }, []),
    'Hello Alice',
  )
})

test('processOpeningStatement falls back to form label when input empty', () => {
  assert.equal(
    processOpeningStatement('Hello {{user_name}}', {}, [
      { variable: 'user_name', label: 'Name Label' },
    ]),
    'Hello {{Name Label}}',
  )
})

test('processOpeningStatement keeps original match when unknown', () => {
  assert.equal(
    processOpeningStatement('Hello {{unknown}}', {}, []),
    'Hello {{unknown}}',
  )
})

test('processOpeningSuggestedQuestions maps each chip', () => {
  assert.deepEqual(
    processOpeningSuggestedQuestions(
      ['Ask {{name}}', 'About {{topic}}'],
      { name: 'Ada' },
      [{ variable: 'topic', label: '主题' }],
    ),
    ['Ask Ada', 'About {{主题}}'],
  )
})
