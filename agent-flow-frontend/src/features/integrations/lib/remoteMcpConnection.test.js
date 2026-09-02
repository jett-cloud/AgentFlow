import assert from 'node:assert/strict'
import test from 'node:test'

async function loadSubject() {
  return import('./remoteMcpConnection.js').catch(() => ({}))
}

function notionForm() {
  return {
    serverUrl: 'https://mcp.notion.com/mcp',
    name: 'Notion',
    serverIdentifier: 'notion',
    authMode: 'oauth',
    token: '',
    clientId: '',
    clientSecret: '',
    headers: [{ key: '', value: '' }],
    timeout: 30,
    sseReadTimeout: 300,
  }
}

test('dynamic OAuth accepts an empty client id and omits static client credentials', async () => {
  const { buildRemoteMcpPayload, validateRemoteMcpForm } = await loadSubject()
  assert.equal(typeof validateRemoteMcpForm, 'function')
  assert.equal(typeof buildRemoteMcpPayload, 'function')

  const form = notionForm()
  assert.equal(validateRemoteMcpForm(form), '')
  assert.equal('authentication' in buildRemoteMcpPayload(form), false)
})

test('client credentials still requires and submits a client id', async () => {
  const { buildRemoteMcpPayload, validateRemoteMcpForm } = await loadSubject()
  const form = { ...notionForm(), authMode: 'client_credentials' }

  assert.match(validateRemoteMcpForm(form), /Client ID/)
  form.clientId = 'service-client'
  form.clientSecret = 'service-secret'

  assert.deepEqual(buildRemoteMcpPayload(form).authentication, {
    client_id: 'service-client',
    client_secret: 'service-secret',
  })
})

test('automatic OAuth reserves a window before the request and navigates it to the authorization URL', async () => {
  const { authorizeRemoteMcp, openRemoteMcpOAuthWindow } = await loadSubject()
  assert.equal(typeof openRemoteMcpOAuthWindow, 'function')
  assert.equal(typeof authorizeRemoteMcp, 'function')

  const calls = []
  const popup = {
    closed: false,
    opener: {},
    location: { replace: url => calls.push(['navigate', url]) },
    close: () => calls.push(['close']),
  }
  const openWindow = (...args) => {
    calls.push(['open', ...args])
    return popup
  }
  const reserved = openRemoteMcpOAuthWindow(openWindow)

  assert.deepEqual(calls, [['open', 'about:blank', '_blank']])
  assert.equal(popup.opener, null)

  const outcome = await authorizeRemoteMcp({
    providerId: 'provider-1',
    authorizeProvider: async () => ({ authorization_url: 'https://notion.so/oauth/authorize' }),
    popup: reserved,
    openWindow,
  })

  assert.deepEqual(outcome, {
    authorizationUrl: 'https://notion.so/oauth/authorize',
    opened: true,
  })
  assert.deepEqual(calls.at(-1), ['navigate', 'https://notion.so/oauth/authorize'])
})
