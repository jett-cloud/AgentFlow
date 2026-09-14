import assert from 'node:assert/strict'
import test from 'node:test'
import { flattenToolCatalog, groupSelectableTools, toolIdentityMatches } from './toolCatalog.js'

const groups = {
  builtin: [{
    id: 'time',
    label: 'Time',
    tools: [{ name: 'now', label: 'Now', parameters: [{ name: 'tz' }], output_schema: { type: 'object' } }],
  }],
  api: [{
    id: 'crm',
    name: 'CRM',
    tools: [{ name: 'lookup', label: 'Lookup' }],
  }],
  workflow: [{
    id: 'wf-1',
    name: 'Summarizer',
    tools: [{ name: 'summarize', label: 'Summarize' }],
  }],
  mcp: [{
    id: 'github',
    name: 'GitHub',
    tools: [{ name: 'get_file', label: 'Get file' }],
  }],
}

test('flattenToolCatalog preserves api and workflow provider_type', () => {
  const tools = flattenToolCatalog(groups)
  const byName = Object.fromEntries(tools.filter(item => item.tool_name).map(item => [item.tool_name, item]))
  assert.equal(byName.now.provider_type, 'builtin')
  assert.equal(byName.lookup.provider_type, 'api')
  assert.equal(byName.summarize.provider_type, 'workflow')
  assert.equal(byName.get_file.provider_type, 'mcp')
  assert.equal(tools.some(item => item.provider_type === 'mcp' && item.tool_name === null), true)
})

test('groupSelectableTools keeps four catalogue groups', () => {
  const grouped = groupSelectableTools(flattenToolCatalog(groups))
  assert.deepEqual(grouped.map(group => group.type), ['builtin', 'api', 'workflow', 'mcp'])
})

test('toolIdentityMatches treats plugin as builtin for catalogue lookup', () => {
  const item = flattenToolCatalog(groups).find(tool => tool.tool_name === 'now')
  assert.equal(toolIdentityMatches(item, { provider_type: 'plugin', provider_id: 'time', tool_name: 'now' }), true)
  assert.equal(toolIdentityMatches(item, { provider_type: 'api', provider_id: 'time', tool_name: 'now' }), false)
})
