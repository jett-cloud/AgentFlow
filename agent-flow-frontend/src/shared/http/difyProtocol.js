export const HIDDEN_SECRET_VALUE = '[__HIDDEN__]'

export function sanitizeEnvironmentVariables(variables = []) {
  return variables.map(variable => variable.value_type === 'secret'
    ? { ...variable, value: HIDDEN_SECRET_VALUE }
    : { ...variable })
}

export function encodeSensitiveField(value) {
  const bytes = new TextEncoder().encode(value)
  let binary = ''
  for (const byte of bytes)
    binary += String.fromCharCode(byte)
  return btoa(binary)
}

export function getCookie(name, cookieSource = globalThis.document?.cookie || '') {
  const prefix = `${encodeURIComponent(name)}=`
  const item = cookieSource.split(';').map(part => part.trim()).find(part => part.startsWith(prefix))
  return item ? decodeURIComponent(item.slice(prefix.length)) : ''
}

export function getCsrfToken(cookieSource = globalThis.document?.cookie || '') {
  return getCookie('__Host-csrf_token', cookieSource) || getCookie('csrf_token', cookieSource)
}

export function isWriteMethod(method = 'get') {
  return ['post', 'put', 'patch', 'delete'].includes(method.toLowerCase())
}

export function parseSseBlock(block) {
  const dataLines = block
    .split(/\r?\n/)
    .filter(line => line.startsWith('data:'))
    .map(line => line.slice(5).trimStart())
  if (dataLines.length === 0)
    return null
  // Contrasts Dify web base.ts: mute incomplete / non-JSON chunks (e.g. cut mid-stream).
  // `event: ping` blocks have no data: lines and already return null above.
  try {
    return JSON.parse(dataLines.join('\n'))
  }
  catch {
    return null
  }
}

export function consumeSseText(buffer, onEvent) {
  const blocks = buffer.split(/\r?\n\r?\n/)
  const remainder = blocks.pop() || ''
  for (const block of blocks) {
    if (!block.trim())
      continue
    const payload = parseSseBlock(block)
    if (payload)
      onEvent(payload)
  }
  return remainder
}

/**
 * Decide whether a fetch Response should be read as SSE.
 * Proxies sometimes drop or rewrite Content-Type; Prefer stream when body exists
 * unless the server clearly returned JSON.
 */
export function shouldConsumeAsSse(response) {
  if (!response?.body)
    return false
  const contentType = String(response.headers?.get?.('content-type') || '').toLowerCase()
  if (contentType.includes('text/event-stream'))
    return true
  if (contentType.includes('application/json') || contentType.includes('+json'))
    return false
  // Missing / opaque content-type with a readable body → treat as SSE for draft-run.
  return !contentType || contentType.includes('text/plain') || contentType.includes('octet-stream')
}
