import assert from 'node:assert/strict'
import test from 'node:test'

import { addDifyTool, catalogToolToDifyTool, difyToolKey, isCatalogToolSelected } from './agentTools.js'

test('Agent tool conversion preserves MCP runtime identity', () => {
  const tool = catalogToolToDifyTool({
    provider_type: 'mcp',
    provider_id: 'github-official',
    provider_name: 'GitHub MCP',
    tool_name: 'get_file_contents',
  })

  assert.equal(tool.provider_type, 'mcp')
  assert.equal(tool.provider_id, 'github-official')
  assert.equal(tool.tool_name, 'get_file_contents')
})

test('Agent tool identity does not collide across provider types', () => {
  const builtin = difyToolKey({ provider_type: 'builtin', provider_id: 'shared', tool_name: 'search' })
  const mcp = difyToolKey({ provider_type: 'mcp', provider_id: 'shared', tool_name: 'search' })

  assert.notEqual(builtin, mcp)
})

test('MCP provider-level catalog entry keeps tool_name null', () => {
  const tool = catalogToolToDifyTool({
    provider_type: 'mcp',
    provider_id: 'github-official',
    provider_name: 'GitHub MCP',
    tool_name: null,
  })

  assert.equal(tool.provider_type, 'mcp')
  assert.equal(tool.provider_id, 'github-official')
  assert.equal(tool.tool_name, null)
  assert.equal(difyToolKey(tool), 'mcp::github-official::*')
})

test('builtin catalog entry still requires a tool name', () => {
  assert.equal(catalogToolToDifyTool({
    provider_type: 'builtin',
    provider_id: 'weather',
    tool_name: null,
  }), null)
})

test('adding an MCP provider-level entry replaces that provider’s single tools', () => {
  const single = catalogToolToDifyTool({
    provider_type: 'mcp',
    provider_id: 'github-official',
    tool_name: 'get_file_contents',
  })
  const other = catalogToolToDifyTool({
    provider_type: 'mcp',
    provider_id: 'other-mcp',
    tool_name: 'search',
  })
  const next = addDifyTool([single, other], {
    provider_type: 'mcp',
    provider_id: 'github-official',
    tool_name: null,
  })

  assert.deepEqual(next.map(tool => difyToolKey(tool)), [
    'mcp::other-mcp::search',
    'mcp::github-official::*',
  ])
})

test('adding a single MCP tool is skipped when the whole provider is already selected', () => {
  const all = catalogToolToDifyTool({
    provider_type: 'mcp',
    provider_id: 'github-official',
    tool_name: null,
  })
  const next = addDifyTool([all], {
    provider_type: 'mcp',
    provider_id: 'github-official',
    tool_name: 'get_file_contents',
  })

  assert.deepEqual(next.map(tool => difyToolKey(tool)), ['mcp::github-official::*'])
})

test('provider-level selection covers every tool of that MCP server', () => {
  const selected = [catalogToolToDifyTool({
    provider_type: 'mcp',
    provider_id: 'github-official',
    tool_name: null,
  })]

  assert.equal(isCatalogToolSelected(selected, {
    provider_type: 'mcp',
    provider_id: 'github-official',
    tool_name: null,
  }), true)
  assert.equal(isCatalogToolSelected(selected, {
    provider_type: 'mcp',
    provider_id: 'github-official',
    tool_name: 'get_file_contents',
  }), true)
  assert.equal(isCatalogToolSelected(selected, {
    provider_type: 'mcp',
    provider_id: 'other-mcp',
    tool_name: 'search',
  }), false)
})
