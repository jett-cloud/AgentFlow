import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { toSandboxNodeData } from './previewToolNodeData.js'

test('sandbox node data marks tool type', () => {
  const data = toSandboxNodeData({
    provider_id: 'acme/demo',
    provider_type: 'plugin',
    tool_name: 'echo',
    parameters_schema: [{ name: 'text', type: 'string' }],
  })

  assert.equal(data.type, 'tool')
  assert.equal(data.tool_name, 'echo')
  assert.deepEqual(data.tool_parameters, {
    text: { type: 'mixed', value: '' },
  })
  assert.deepEqual(data.credentials_schema, [])
  assert.deepEqual(data.credentials, {})
})

test('sandbox node data includes credentials schema fields', () => {
  const data = toSandboxNodeData({
    provider_id: 'acme/image',
    tool_name: 'generate_image',
    parameters_schema: [{ name: 'prompt', type: 'string' }],
    credentials_schema: [{ name: 'api_key', type: 'secret-input', required: true }],
  })

  assert.equal(data.credentials_schema[0].name, 'api_key')
  assert.equal(data.credentials.api_key, '')
})

test('studio does not save workflow drafts', () => {
  const src = readFileSync(new URL('../pages/AiToolPluginStudio.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(src, /saveDraft|persistDraftGraph/)
})

test('studio mounts a local tool sandbox when preview is available', () => {
  const studio = readFileSync(new URL('../pages/AiToolPluginStudio.vue', import.meta.url), 'utf8')
  const sandbox = readFileSync(new URL('./ToolPluginSandbox.vue', import.meta.url), 'utf8')

  assert.match(studio, /<ToolPluginSandbox/)
  assert.match(studio, /sandboxOpen/)
  assert.match(studio, /沙箱预览/)
  assert.match(sandbox, /toSandboxNodeData/)
  assert.match(sandbox, /parameters_schema/)
  assert.match(sandbox, /tool_parameters/)
})

test('sandbox verifies and publishes the current session with ephemeral credentials', () => {
  const studio = readFileSync(new URL('../pages/AiToolPluginStudio.vue', import.meta.url), 'utf8')
  const sandbox = readFileSync(new URL('./ToolPluginSandbox.vue', import.meta.url), 'utf8')
  const api = readFileSync(new URL('../api/difyToolPluginGeneratorApi.js', import.meta.url), 'utf8')

  assert.match(studio, /:can-publish="canPublishPlugin"/)
  assert.match(sandbox, /publishToolPluginSession/)
  assert.match(sandbox, /buildSandboxTestParameters/)
  assert.match(sandbox, /uploadConsoleFile/)
  assert.match(sandbox, /el-upload/)
  assert.match(sandbox, /testResult\.diagnostic\?\.message/)
  assert.match(sandbox, /credentials: currentCredentials\(\)/)
  assert.match(sandbox, /credentials_schema/)
  assert.match(sandbox, /\/integrations\?tab=tools/)
  assert.match(api, /sessions\/\$\{sessionId\}\/publish/)
  assert.match(sandbox, /ElMessageBox\.confirm/)
  assert.match(sandbox, /真实调用外部 API/)
  assert.match(sandbox, /authorization\.token/)
  assert.match(api, /test-authorization/)
})

test('studio wires streaming agent turn with stop support', () => {
  const studio = readFileSync(new URL('../pages/AiToolPluginStudio.vue', import.meta.url), 'utf8')
  const panel = readFileSync(new URL('./AgentChatPanel.vue', import.meta.url), 'utf8')
  const api = readFileSync(new URL('../api/difyToolPluginGeneratorApi.js', import.meta.url), 'utf8')

  assert.match(studio, /AgentChatPanel/)
  assert.match(studio, /agentTurnToolPluginStream/)
  assert.match(studio, /AbortController/)
  assert.match(studio, /handleStopAgent/)
  assert.match(studio, /listToolPluginSessions/)
  assert.match(studio, /session_id/)
  assert.match(studio, /SessionHistoryRail/)
  assert.doesNotMatch(studio, /historyPayload/)
  assert.doesNotMatch(studio, /@bootstrap/)
  assert.doesNotMatch(panel, /初始化生成/)
  assert.match(panel, /messages-scroll/)
  assert.match(panel, /停止/)
  assert.match(panel, /新增工具/)
  assert.match(api, /\/workspaces\/current\/tool-plugin\/agent\/turn\/stream/)
  assert.match(api, /\/workspaces\/current\/tool-plugin\/sessions/)
  assert.match(api, /sessions\/\$\{sessionId\}\/hide/)
  assert.match(api, /timeout:\s*600000/)
  assert.doesNotMatch(studio, /confirmInstallOverwriteIfNeeded/)
  assert.doesNotMatch(studio, /auto_install/)
  assert.doesNotMatch(studio, /payload\.previous_installation_id/)
  assert.match(studio, /expected_revision/)
  assert.match(studio, /identityReady/)
  assert.match(studio, /sessionTitle/)
  assert.doesNotMatch(studio, /同名会话已存在，已为你打开/)
  assert.doesNotMatch(panel, /sanitizePluginIdentityName/)
  assert.match(panel, /pluginIdentityFieldError/)
  assert.match(panel, /identityReady/)
  assert.match(panel, /require-tool-call/)
  assert.match(studio, /forkToolPluginSession/)
  assert.match(studio, /handleForkPick/)
  assert.match(studio, /applyBootstrapQuery/)
  assert.match(studio, /fork-pick/)
  assert.match(api, /\/workspaces\/current\/tool-plugin\/session-fork/)
})

test('session history replaces hiding with persistent renaming', () => {
  const studio = readFileSync(new URL('../pages/AiToolPluginStudio.vue', import.meta.url), 'utf8')
  const rail = readFileSync(new URL('./SessionHistoryRail.vue', import.meta.url), 'utf8')

  assert.match(rail, /重命名/)
  assert.match(rail, /emitAction\('rename', item\)/)
  assert.doesNotMatch(rail, /显示已隐藏|隐藏已归档|取消隐藏/)
  assert.doesNotMatch(rail, /showHidden|is_hidden/)

  assert.match(studio, /@rename="handleRenameSession"/)
  assert.match(studio, /listToolPluginSessions\(\{ includeHidden: true \}\)/)
  assert.match(studio, /ElMessageBox\.prompt/)
  assert.match(studio, /expected_revision: item\.revision/)
  assert.match(studio, /title: nextTitle/)
  assert.doesNotMatch(studio, /hideToolPluginSession|unhideToolPluginSession|showHiddenSessions/)
})

test('studio greeting has no prompt suggestion shortcuts', () => {
  const panel = readFileSync(new URL('./AgentChatPanel.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(panel, /class="suggestions"/)
  assert.doesNotMatch(panel, /useSuggestion/)
  assert.doesNotMatch(panel, /创建 Notion 页面工具|改进错误处理|创建 echo 工具/)
})

test('tools auth panel links into studio open/fork/blank flows', () => {
  const auth = readFileSync(new URL('../ui/ToolsAuthPanel.vue', import.meta.url), 'utf8')
  assert.match(auth, /fetchStudioSessionsByInstallation/)
  assert.match(auth, /forkSourceSessionId/)
  assert.match(auth, /intent: 'add_tool'/)
  assert.match(auth, /空白新建同名/)
  assert.match(auth, /打开对话/)
  assert.match(auth, /新增工具/)
})

test('studio uses workspace ModelSelector provider and model', () => {
  const panel = readFileSync(new URL('./AgentChatPanel.vue', import.meta.url), 'utf8')
  const studio = readFileSync(new URL('../pages/AiToolPluginStudio.vue', import.meta.url), 'utf8')

  assert.match(panel, /ModelSelector/)
  assert.match(studio, /model_provider/)
})
