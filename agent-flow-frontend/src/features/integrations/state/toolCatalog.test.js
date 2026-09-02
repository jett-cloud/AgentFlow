import assert from 'node:assert/strict'
import test from 'node:test'

async function loadSubject() {
  return import('./toolCatalog.js').catch(() => ({}))
}

test('tool catalog keeps MCP provider type and runtime provider identifier', async () => {
  const { flattenToolCatalog } = await loadSubject()
  assert.equal(typeof flattenToolCatalog, 'function')

  const tools = flattenToolCatalog({
    builtin: [],
    mcp: [{
      id: 'github-official',
      name: 'GitHub MCP',
      label: { zh_Hans: 'GitHub MCP' },
      tools: [{ name: 'get_file_contents', label: { zh_Hans: '读取文件' } }],
    }],
  })

  assert.deepEqual(tools.map(tool => ({
    provider_id: tool.provider_id,
    provider_type: tool.provider_type,
    tool_name: tool.tool_name,
    tool_label: tool.tool_label,
  })), [{
    provider_id: 'github-official',
    provider_type: 'mcp',
    tool_name: null,
    tool_label: '全部工具',
  }, {
    provider_id: 'github-official',
    provider_type: 'mcp',
    tool_name: 'get_file_contents',
    tool_label: '读取文件',
  }])
})

test('groupSelectableTools exposes builtin and MCP as separate groups', async () => {
  const { groupSelectableTools } = await loadSubject()
  assert.equal(typeof groupSelectableTools, 'function')

  const groups = groupSelectableTools([
    { provider_type: 'builtin', provider_id: 'weather', tool_name: 'forecast' },
    { provider_type: 'mcp', provider_id: 'github-official', tool_name: 'get_file_contents' },
  ])

  assert.deepEqual(groups.map(group => ({ type: group.type, label: group.label })), [
    { type: 'builtin', label: '工具插件' },
    { type: 'mcp', label: 'MCP 工具' },
  ])
})

test('plugin provider type matches builtin catalog tools', async () => {
  const { normalizeToolProviderType, toolIdentityMatches } = await loadSubject()
  assert.equal(normalizeToolProviderType('plugin'), 'builtin')
  assert.equal(toolIdentityMatches(
    { provider_type: 'builtin', provider_id: 'ghy/doubao-image/doubao-image', tool_name: 'image_gerenate_image' },
    { provider_type: 'plugin', provider_id: 'ghy/doubao-image/doubao-image', tool_name: 'image_gerenate_image' },
  ), true)
  assert.equal(toolIdentityMatches(
    { provider_type: 'mcp', provider_id: 'github-official', tool_name: 'get_file_contents' },
    { provider_type: 'plugin', provider_id: 'github-official', tool_name: 'get_file_contents' },
  ), false)
})
