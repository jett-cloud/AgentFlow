import assert from 'node:assert/strict'
import test from 'node:test'
import { filterFunctionCallingProviders, supportsFunctionCalling } from './modelCapabilities.js'

test('supports single and multi native tool calling models', () => {
  assert.equal(supportsFunctionCalling({ features: ['tool-call'] }), true)
  assert.equal(supportsFunctionCalling({ features: ['multi-tool-call'] }), true)
  assert.equal(supportsFunctionCalling({ features: ['vision'] }), false)
})

test('filters providers down to function calling models', () => {
  const providers = filterFunctionCallingProviders([
    {
      provider: 'acme',
      models: [
        { model: 'plain', features: [] },
        { model: 'agent', features: ['tool-call'] },
      ],
    },
    { provider: 'empty', models: [{ model: 'vision', features: ['vision'] }] },
  ])

  assert.deepEqual(providers, [
    {
      provider: 'acme',
      models: [{ model: 'agent', features: ['tool-call'] }],
    },
  ])
})
