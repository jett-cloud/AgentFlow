import test from 'node:test'
import assert from 'node:assert/strict'
import {
  DEFAULT_AGENT_DECLARED_OUTPUTS,
  addDeclaredOutput,
  declaredOutputsToPanelVars,
  getAgentDeclaredOutputs,
  normalizeAgentMemory,
  normalizeDeclaredOutput,
  removeDeclaredOutput,
} from './agentOutputs.js'

test('getAgentDeclaredOutputs falls back to defaults', () => {
  const outputs = getAgentDeclaredOutputs({})
  assert.equal(outputs.length, DEFAULT_AGENT_DECLARED_OUTPUTS.length)
  assert.equal(outputs[0].name, 'text')
})

test('getAgentDeclaredOutputs keeps custom list', () => {
  const outputs = getAgentDeclaredOutputs({
    agent_declared_outputs: [{ name: 'answer', type: 'string', description: '答' }],
  })
  assert.equal(outputs.length, 1)
  assert.equal(outputs[0].name, 'answer')
})

test('addDeclaredOutput and removeDeclaredOutput', () => {
  let list = getAgentDeclaredOutputs({})
  list = addDeclaredOutput(list, { name: 'score', type: 'number', description: '分' })
  assert.ok(list.some(item => item.name === 'score'))
  list = addDeclaredOutput(list, { name: 'score', type: 'number' })
  assert.equal(list.filter(item => item.name === 'score').length, 1)
  list = removeDeclaredOutput(list, 'text')
  assert.ok(list.some(item => item.name === 'text'), 'default outputs cannot be removed')
  list = removeDeclaredOutput(list, 'score')
  assert.ok(!list.some(item => item.name === 'score'))
})

test('declaredOutputsToPanelVars maps array file', () => {
  const vars = declaredOutputsToPanelVars([
    { name: 'files', type: 'array', array_item: { type: 'file' }, description: 'f' },
  ])
  assert.equal(vars[0].type, 'arrayFile')
})

test('normalizeAgentMemory defaults', () => {
  assert.deepEqual(normalizeAgentMemory(null).window, { enabled: true, size: 50 })
  assert.equal(normalizeAgentMemory({ window: { enabled: false, size: 10 } }).window.size, 10)
})

test('normalizeDeclaredOutput supports file type', () => {
  const fileOut = normalizeDeclaredOutput({ name: 'doc', type: 'file' })
  assert.equal(fileOut.type, 'file')
  assert.ok(fileOut.file)
})

test('normalizeDeclaredOutput preserves nested object and array item children', () => {
  const output = normalizeDeclaredOutput({
    name: 'result',
    type: 'object',
    children: [
      { name: 'answer', type: 'string' },
      {
        name: 'evidence',
        type: 'array',
        array_item: { type: 'object', children: [{ name: 'source', type: 'string' }] },
      },
    ],
  })

  assert.equal(output.children[0].name, 'answer')
  assert.equal(output.children[1].array_item.children[0].name, 'source')
})
