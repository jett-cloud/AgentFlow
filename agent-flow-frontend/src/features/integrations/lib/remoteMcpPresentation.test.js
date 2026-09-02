import assert from 'node:assert/strict'
import test from 'node:test'

import {
  filterRemoteMcpTools,
  resolveRemoteMcpIcon,
} from './remoteMcpPresentation.js'
import * as presentation from './remoteMcpPresentation.js'

test('uses provider initials instead of a remote image', () => {
  assert.deepEqual(
    resolveRemoteMcpIcon({ name: 'SocialDataX', icon: 'https://mcp.example.com/icon.png' }),
    { type: 'letters', value: 'SD', variant: 'initials' },
  )
})

test('uses camel-case initials for GitHub', () => {
  assert.deepEqual(
    resolveRemoteMcpIcon({
      name: 'GitHub MCP',
      server_identifier: 'github',
      icon: { content: '🔌' },
    }),
    { type: 'letters', value: 'GH', variant: 'initials' },
  )
})

test('uses the first two letters for a single-word provider name', () => {
  assert.deepEqual(
    resolveRemoteMcpIcon({ name: 'Notion', server_identifier: 'notion' }),
    { type: 'letters', value: 'NO', variant: 'initials' },
  )
})

test('normalizes provider data with the same branded icon used across MCP pages', () => {
  assert.equal(typeof presentation.normalizeRemoteMcpProvider, 'function')

  assert.deepEqual(
    presentation.normalizeRemoteMcpProvider({
      id: 'provider-1',
      name: 'GitHub MCP',
      server_identifier: 'github',
      icon: { content: '🔌' },
      tools: [{ name: 'search_issues' }],
      is_team_authorization: true,
    }),
    {
      id: 'provider-1',
      name: 'GitHub MCP',
      server_identifier: 'github',
      icon: { content: '🔌' },
      tools: [{ name: 'search_issues' }],
      is_team_authorization: true,
      authed: true,
      iconMeta: { type: 'letters', value: 'GH', variant: 'initials' },
    },
  )
})

test('returns to the MCP integrations tab', () => {
  assert.equal(typeof presentation.mcpToolsLocation, 'function')
  assert.deepEqual(presentation.mcpToolsLocation(), {
    path: '/integrations',
    query: { tab: 'mcp' },
  })
})

test('filters tools by localized name, protocol name, and description', () => {
  const tools = [
    { name: 'search_issues', label: { zh_Hans: '搜索问题' }, description: '查找 GitHub Issues' },
    { name: 'create_branch', description: '创建代码分支' },
  ]

  assert.deepEqual(filterRemoteMcpTools(tools, '搜索'), [tools[0]])
  assert.deepEqual(filterRemoteMcpTools(tools, 'branch'), [tools[1]])
  assert.deepEqual(filterRemoteMcpTools(tools, 'issues'), [tools[0]])
  assert.deepEqual(filterRemoteMcpTools(tools, '  '), tools)
})
