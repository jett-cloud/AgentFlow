import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildNestedValueSelector,
  getRootSelectorPath,
  hasNestedChildren,
  listTreeFields,
  normalizeRagPipelineVariables,
  getTreeRootLabel,
} from './objectChildTree.js'
import { OUTPUT_FILE_SUB_VARIABLES } from './variableOutputs.js'

test('getRootSelectorPath splits special vars and keeps normal names', () => {
  assert.deepEqual(getRootSelectorPath({ variable: 'sys.files' }), ['sys', 'files'])
  assert.deepEqual(getRootSelectorPath({ variable: 'rag.shared.query', isRagVariable: true }), ['rag', 'shared', 'query'])
  assert.deepEqual(getRootSelectorPath({ variable: 'text' }), ['text'])
})

test('buildNestedValueSelector builds Dify-compatible selectors', () => {
  assert.deepEqual(
    buildNestedValueSelector('http-1', ['files'], ['name']),
    ['http-1', 'files', 'name'],
  )
  assert.deepEqual(
    buildNestedValueSelector('start', ['sys', 'files'], ['url']),
    ['sys', 'files', 'url'],
  )
  assert.deepEqual(
    buildNestedValueSelector('start', ['sys', 'files'], []),
    ['sys', 'files'],
  )
})

test('hasNestedChildren / listTreeFields work with file sub vars', () => {
  const variable = { variable: 'files', type: 'arrayFile', children: OUTPUT_FILE_SUB_VARIABLES }
  assert.equal(hasNestedChildren(variable), true)
  const fields = listTreeFields(variable.children)
  assert.ok(fields.some(f => f.name === 'name'))
  assert.ok(fields.some(f => f.name === 'url'))
})

test('normalizeRagPipelineVariables fills defaults', () => {
  const list = normalizeRagPipelineVariables([
    { variable: 'query', type: 'text-input', label: 'Query' },
    { foo: 'bar' },
  ])
  assert.equal(list.length, 1)
  assert.equal(list[0].belong_to_node_id, 'shared')
  assert.equal(list[0].variable, 'query')
  assert.equal(getTreeRootLabel({ variable: 'sys.files' }), 'files')
})
