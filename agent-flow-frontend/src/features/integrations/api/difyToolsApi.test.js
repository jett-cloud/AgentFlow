import assert from 'node:assert/strict'
import test from 'node:test'

import { fetchAllTools } from './difyToolsApi.js'

test('fetchAllTools loads builtin and MCP catalogs in parallel', async () => {
  const calls = []
  const plugin = { id: 'acme/weather', tools: [{ name: 'forecast' }] }
  const mcp = { id: 'github-official', tools: [{ name: 'get_file_contents' }] }
  const fetchers = {
    builtin: async (config) => {
      calls.push({ type: 'builtin', config })
      return { data: [plugin] }
    },
    api: async () => {
      calls.push({ type: 'api' })
      return { data: [{ id: 'custom-api' }] }
    },
    workflow: async () => {
      calls.push({ type: 'workflow' })
      return { data: [{ id: 'workflow-tool' }] }
    },
    mcp: async () => {
      calls.push({ type: 'mcp' })
      return { data: [mcp] }
    },
  }

  const catalog = await fetchAllTools(fetchers)

  assert.deepEqual(catalog, { builtin: [plugin], mcp: [mcp] })
  assert.deepEqual(calls, [
    { type: 'builtin', config: { silent: true } },
    { type: 'mcp' },
  ])
})

test('fetchAllTools keeps the available catalog when one source fails', async () => {
  const plugin = { id: 'acme/weather', tools: [{ name: 'forecast' }] }

  const catalog = await fetchAllTools({
    builtin: async () => ({ data: [plugin] }),
    mcp: async () => { throw new Error('MCP unavailable') },
  })

  assert.deepEqual(catalog, { builtin: [plugin], mcp: [] })
})
