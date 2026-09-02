export const GITHUB_MCP_URL = 'https://api.githubcopilot.com/mcp/'
export const GITHUB_TOOLSETS = Object.freeze(['repos', 'issues', 'pull_requests'])

export function createGitHubMcpForm() {
  return {
    mode: 'github',
    name: 'GitHub MCP',
    serverUrl: GITHUB_MCP_URL,
    serverIdentifier: 'github-official',
    icon: '🐙',
    iconBackground: '#24292f',
    token: '',
    readonly: true,
    toolsets: [...GITHUB_TOOLSETS],
    authMode: 'headers',
    headers: [],
    clientId: '',
    clientSecret: '',
    timeout: 30,
    sseReadTimeout: 300,
  }
}

export function createCustomMcpForm() {
  return {
    mode: 'custom',
    name: '',
    serverUrl: '',
    serverIdentifier: '',
    icon: '🔌',
    iconBackground: '#eff4ff',
    token: '',
    readonly: true,
    toolsets: [],
    authMode: 'headers',
    headers: [{ key: '', value: '' }],
    clientId: '',
    clientSecret: '',
    timeout: 30,
    sseReadTimeout: 300,
  }
}

export function createMcpEditForm(provider) {
  const raw = provider || {}
  const maskedHeaders = raw.masked_headers || {}
  return {
    ...createCustomMcpForm(),
    mode: 'custom',
    name: raw.name || '',
    serverUrl: raw.server_url || '',
    originalServerUrl: raw.server_url || '',
    serverIdentifier: raw.server_identifier || '',
    icon: typeof raw.icon === 'object' ? (raw.icon.content || '🔌') : (raw.icon || '🔌'),
    iconBackground: typeof raw.icon === 'object' ? (raw.icon.background || '#eff4ff') : '#eff4ff',
    headers: Object.entries(maskedHeaders).map(([key, value]) => ({ key, value })),
    authMode: raw.authentication ? 'oauth' : 'headers',
    clientId: raw.authentication?.client_id || '',
    clientSecret: raw.authentication?.client_secret || '',
    timeout: Number(raw.configuration?.timeout || 30),
    sseReadTimeout: Number(raw.configuration?.sse_read_timeout || 300),
  }
}

export function validateMcpForm(form) {
  if (!String(form?.name || '').trim())
    return '请输入 MCP 名称'
  if (!/^[a-z0-9_-]{1,24}$/.test(String(form?.serverIdentifier || '').trim()))
    return '唯一标识仅支持 1–24 位小写字母、数字、下划线或连字符'
  if (form?.mode === 'github' && !String(form?.token || '').trim())
    return '请输入 GitHub Personal Access Token'
  try {
    const url = new URL(String(form?.serverUrl || '').trim())
    if (url.protocol !== 'https:')
      return '远程 MCP URL 必须使用 HTTPS'
  }
  catch {
    return '请输入有效的 MCP Server URL'
  }
  return ''
}

export function buildMcpProviderPayload(form, providerId = '') {
  const editing = !!providerId
  const serverUrl = editing && form.serverUrl === form.originalServerUrl
    ? '[__HIDDEN__]'
    : String(form.serverUrl || '').trim()
  const headers = {}
  for (const item of form.headers || []) {
    const key = String(item?.key || '').trim()
    if (key)
      headers[key] = String(item?.value || '')
  }
  if (form.mode === 'github') {
    headers.Authorization = `Bearer ${String(form.token || '').trim()}`
    headers['X-MCP-Readonly'] = form.readonly === false ? 'false' : 'true'
    if (form.toolsets?.length)
      headers['X-MCP-Toolsets'] = form.toolsets.join(',')
  }

  const payload = {
    server_url: serverUrl,
    name: String(form.name || '').trim(),
    icon: String(form.icon || '🔌'),
    icon_type: 'emoji',
    icon_background: String(form.iconBackground || '#eff4ff'),
    server_identifier: String(form.serverIdentifier || '').trim(),
    configuration: {
      timeout: Number(form.timeout || 30),
      sse_read_timeout: Number(form.sseReadTimeout || 300),
    },
    headers,
    identity_mode: 'off',
  }
  if (form.authMode === 'oauth' && String(form.clientId || '').trim()) {
    payload.authentication = {
      client_id: String(form.clientId).trim(),
      client_secret: String(form.clientSecret || ''),
    }
  }
  if (editing)
    payload.provider_id = providerId
  return payload
}

export function clearMcpFormSecrets(form) {
  if (!form)
    return
  form.token = ''
  form.clientSecret = ''
  form.headers = (form.headers || []).map(item => ({ ...item, value: '' }))
}
