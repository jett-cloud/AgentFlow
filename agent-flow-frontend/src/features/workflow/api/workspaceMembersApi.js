function normalizeMember(item) {
  const id = item?.id || item?.account_id
  if (!id)
    return null
  return {
    id: String(id),
    name: String(item.name || ''),
    email: String(item.email || ''),
  }
}

export function normalizeWorkspaceMembers(payload) {
  const rows = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.accounts)
      ? payload.accounts
      : Array.isArray(payload?.data)
        ? payload.data
        : []
  return rows.map(normalizeMember).filter(Boolean)
}

export async function fetchWorkspaceMembers({ language, signal, client } = {}) {
  const http = client || (await import('../../../shared/http/difyClient.js')).default
  const payload = await http.get('/workspaces/current/members', {
    params: language ? { language } : undefined,
    signal,
  })
  return normalizeWorkspaceMembers(payload)
}
