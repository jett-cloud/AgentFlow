import assert from 'node:assert/strict'
import test from 'node:test'

const api = await import('./difyToolsApi.js')

test('remote MCP API exposes provider operations without an AI draft endpoint', () => {
  assert.equal(api.draftRemoteMcpConfiguration, undefined)
  assert.equal(typeof api.createMcpProvider, 'function')
  assert.equal(typeof api.fetchMcpProviders, 'function')
  assert.equal(typeof api.refreshMcpProviderTools, 'function')
})
