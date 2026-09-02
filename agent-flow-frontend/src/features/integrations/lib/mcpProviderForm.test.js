import assert from 'node:assert/strict'
import test from 'node:test'

async function loadSubject() {
  return import('./mcpProviderForm.js').catch(() => ({}))
}

test('GitHub template is read-only by default and limits exposed toolsets', async () => {
  const { createGitHubMcpForm } = await loadSubject()
  assert.equal(typeof createGitHubMcpForm, 'function')

  const form = createGitHubMcpForm()

  assert.equal(form.serverUrl, 'https://api.githubcopilot.com/mcp/')
  assert.equal(form.readonly, true)
  assert.deepEqual(form.toolsets, ['repos', 'issues', 'pull_requests'])
})

test('GitHub payload puts the token only in encrypted backend headers', async () => {
  const { buildMcpProviderPayload, createGitHubMcpForm } = await loadSubject()
  assert.equal(typeof buildMcpProviderPayload, 'function')

  const form = createGitHubMcpForm()
  form.token = 'github_pat_secret'
  const payload = buildMcpProviderPayload(form)

  assert.equal(payload.server_identifier, 'github-official')
  assert.equal(payload.headers.Authorization, 'Bearer github_pat_secret')
  assert.equal(payload.headers['X-MCP-Readonly'], 'true')
  assert.equal(payload.headers['X-MCP-Toolsets'], 'repos,issues,pull_requests')
  assert.equal('token' in payload, false)
})

test('clearing MCP secrets removes plaintext values after submission', async () => {
  const { clearMcpFormSecrets, createGitHubMcpForm } = await loadSubject()
  assert.equal(typeof clearMcpFormSecrets, 'function')
  const form = createGitHubMcpForm()
  form.token = 'github_pat_secret'
  form.clientSecret = 'oauth_secret'
  form.headers = [{ key: 'X-Key', value: 'header_secret' }]

  clearMcpFormSecrets(form)

  assert.equal(form.token, '')
  assert.equal(form.clientSecret, '')
  assert.deepEqual(form.headers, [{ key: 'X-Key', value: '' }])
})

test('remote MCP form requires HTTPS URLs', async () => {
  const { createCustomMcpForm, validateMcpForm } = await loadSubject()
  const form = createCustomMcpForm()
  form.name = 'Remote MCP'
  form.serverIdentifier = 'remote_mcp'
  form.serverUrl = 'http://example.com/mcp'

  assert.match(validateMcpForm(form), /HTTPS/)
})
