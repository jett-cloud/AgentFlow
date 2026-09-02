import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const page = readFileSync(new URL('./McpRemoteAssistant.vue', import.meta.url), 'utf8')

test('remote MCP connection page has no AI configuration flow', () => {
  assert.match(page, /createMcpProvider/)
  assert.match(page, /fetchMcpProviders/)
  assert.match(page, /refreshMcpProviderTools/)
  assert.match(page, /authorizeMcpProvider/)
  assert.doesNotMatch(page, /draftRemoteMcpConfiguration|生成连接建议|连接需求|AI 只生成|告诉我你要连接什么/)
  assert.doesNotMatch(page, /下载 ZIP|MCP Server 文件|生成服务代码/)
})

test('remote MCP page keeps the back button inside the main viewport', () => {
  assert.match(page, /\.remote-mcp-page\{[^}]*box-sizing:border-box[^}]*min-height:100%/)
})

test('remote MCP assistant clears secrets after connection attempts', () => {
  assert.match(page, /clearSecrets\(\)/)
  assert.match(page, /已完成握手，工具列表已获取/)
  assert.match(page, /完成授权后即可获取工具/)
  assert.match(page, /type="password"/)
  assert.match(page, /必须使用 HTTPS/)
})

test('remote MCP page supports automatic OAuth discovery without client credentials', () => {
  assert.match(page, /OAuth 2\.0（自动发现）/)
  assert.match(page, /openRemoteMcpOAuthWindow/)
  assert.match(page, /authorizeRemoteMcp/)
  assert.doesNotMatch(page, /\['oauth', 'client_credentials'\]\.includes\(form\.authMode\)/)
})

test('remote MCP connection actions remain visible below a scrolling form', () => {
  assert.match(page, /class="connection-form-body"/)
  assert.match(page, /class="connection-actions"/)
  assert.match(page, /确认并连接/)
  assert.match(page, /重置/)
  assert.match(page, /\.assistant-card\{[^}]*overflow:hidden/)
  assert.match(page, /\.connection-form-body\{[^}]*overflow:auto/)
})

test('remote MCP services and tools use independent full-height panes', () => {
  assert.match(page, /\.providers-card\{[^}]*display:flex[^}]*max-height:calc\(100vh - 238px\)[^}]*overflow:hidden/)
  assert.match(page, /class="providers-workspace"/)
  assert.match(page, /class="provider-rail"/)
  assert.match(page, /\.providers-workspace\{[^}]*display:grid[^}]*min-height:0[^}]*flex:1[^}]*grid-template-columns:minmax\(190px,220px\) minmax\(0,1fr\)[^}]*overflow:hidden/)
  assert.match(page, /\.providers-workspace \.provider-list\{[^}]*min-height:0[^}]*max-height:none[^}]*flex:1[^}]*overflow:auto/)
  assert.match(page, /\.providers-workspace \.provider-detail\{[^}]*min-width:0[^}]*min-height:0[^}]*overflow:auto/)
  assert.match(page, /@media\(max-width:1100px\)\{\.providers-workspace\{[^}]*grid-template-columns:1fr[^}]*grid-template-rows:minmax\(120px,220px\) minmax\(0,1fr\)/)
})

test('remote MCP detail metadata fits inside the narrower tool pane', () => {
  assert.match(page, /\.providers-workspace \.server-meta-row\.compact\{[^}]*grid-template-columns:76px minmax\(0,1fr\)/)
})

test('remote MCP providers use branded icons and searchable tool cards', () => {
  assert.match(page, /filterRemoteMcpTools/)
  assert.match(page, /v-model="toolQuery"/)
  assert.match(page, /filteredTools/)
  assert.match(page, /referrerpolicy="no-referrer"/)
  assert.doesNotMatch(page, /'\ud83d\udd0c'/)
})
