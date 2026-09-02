function unwrap(payload) {
  return payload?.data ?? payload
}

function closePopup(popup) {
  if (popup && !popup.closed)
    popup.close()
}

export function validateRemoteMcpForm(form) {
  if (!String(form?.name || '').trim())
    return '请输入 MCP 名称'
  if (!/^[a-z0-9_-]{1,24}$/.test(String(form?.serverIdentifier || '').trim()))
    return '唯一标识仅支持 1–24 位小写字母、数字、下划线或连字符'
  try {
    const url = new URL(String(form?.serverUrl || '').trim())
    if (url.protocol !== 'https:')
      return '远程 MCP URL 必须使用 HTTPS'
  }
  catch {
    return '请输入有效的远程 MCP URL'
  }
  if (form?.authMode === 'bearer_token' && !String(form?.token || '').trim())
    return '请输入 Bearer Token'
  if (form?.authMode === 'client_credentials' && !String(form?.clientId || '').trim())
    return '请输入 Client ID'
  return ''
}

export function buildRemoteMcpPayload(form) {
  const headers = {}
  for (const item of form?.headers || []) {
    const key = String(item?.key || '').trim()
    if (key)
      headers[key] = String(item?.value || '')
  }
  if (form?.authMode === 'bearer_token')
    headers.Authorization = `Bearer ${String(form?.token || '').trim()}`

  const payload = {
    server_url: String(form?.serverUrl || '').trim(),
    name: String(form?.name || '').trim(),
    icon: 'MCP',
    icon_type: 'emoji',
    icon_background: '#eef2ff',
    server_identifier: String(form?.serverIdentifier || '').trim(),
    configuration: {
      timeout: Number(form?.timeout) || 30,
      sse_read_timeout: Number(form?.sseReadTimeout) || 300,
    },
    headers,
    identity_mode: 'off',
  }
  if (form?.authMode === 'client_credentials') {
    payload.authentication = {
      client_id: String(form?.clientId || '').trim(),
      client_secret: String(form?.clientSecret || ''),
    }
  }
  return payload
}

export function openRemoteMcpOAuthWindow(openWindow) {
  const popup = openWindow('about:blank', '_blank')
  if (popup)
    popup.opener = null
  return popup
}

export async function authorizeRemoteMcp({ providerId, authorizeProvider, popup, openWindow }) {
  try {
    const result = unwrap(await authorizeProvider(providerId))
    const authorizationUrl = String(result?.authorization_url || '')
    if (!authorizationUrl) {
      closePopup(popup)
      return { authorizationUrl: '', opened: false }
    }

    const parsedUrl = new URL(authorizationUrl)
    if (parsedUrl.protocol !== 'https:')
      throw new Error('OAuth 授权地址必须使用 HTTPS')

    if (popup && !popup.closed) {
      popup.location.replace(authorizationUrl)
      return { authorizationUrl, opened: true }
    }
    const opened = Boolean(openWindow(authorizationUrl, '_blank', 'noopener,noreferrer'))
    return { authorizationUrl, opened }
  }
  catch (error) {
    closePopup(popup)
    throw error
  }
}
