import { CSRF_HEADER_NAME, getCsrfToken } from '../../../shared/http/difyClient.js'
import { refreshAccessTokenOrReLogin } from '../../../shared/auth/difyRefreshToken.js'

export class FetchSseHttpError extends Error {
  constructor(message, { status, data }) {
    super(message)
    this.name = 'FetchSseHttpError'
    this.status = status
    this.data = data
  }
}

export class FetchSseParseError extends Error {
  constructor(message, { eventId, event, data }) {
    super(message)
    this.name = 'FetchSseParseError'
    this.eventId = eventId
    this.event = event
    this.data = data
  }
}

function abortReason(signal) {
  if (signal?.reason instanceof Error)
    return signal.reason
  return new DOMException('The operation was aborted', 'AbortError')
}

function authenticationRequired() {
  return new FetchSseHttpError('Sign in again to reconnect to this run.', {
    status: 401,
    data: { code: 'ASSIST_AUTH_REQUIRED' },
  })
}

async function refreshForStream(refreshAuth, signal) {
  let onAbort
  try {
    if (signal?.aborted)
      throw abortReason(signal)
    const cancelled = new Promise((_, reject) => {
      onAbort = () => reject(abortReason(signal))
      signal?.addEventListener('abort', onAbort, { once: true })
    })
    await Promise.race([cancelled, Promise.resolve().then(refreshAuth)])
  }
  finally {
    signal?.removeEventListener('abort', onAbort)
  }
}

async function readErrorData(response) {
  let raw = ''
  if (typeof response.text === 'function')
    raw = await response.text()
  else if (typeof response.json === 'function')
    return response.json()
  if (!raw)
    return null
  try {
    return JSON.parse(raw)
  }
  catch {
    return raw
  }
}

function nextLine(buffer, endOfStream) {
  for (let index = 0; index < buffer.length; index += 1) {
    const character = buffer[index]
    if (character === '\n')
      return [buffer.slice(0, index), buffer.slice(index + 1)]
    if (character !== '\r')
      continue
    if (index === buffer.length - 1 && !endOfStream)
      return null
    const nextIndex = buffer[index + 1] === '\n' ? index + 2 : index + 1
    return [buffer.slice(0, index), buffer.slice(nextIndex)]
  }
  if (endOfStream && buffer)
    return [buffer, '']
  return null
}

function createParser({ initialEventId, onEvent }) {
  let buffer = ''
  let lastEventId = initialEventId
  let eventName = ''
  let dataLines = []

  async function dispatch() {
    if (dataLines.length === 0) {
      eventName = ''
      return
    }
    const rawData = dataLines.join('\n')
    let data
    try {
      data = JSON.parse(rawData)
    }
    catch (error) {
      throw new FetchSseParseError('Workflow Assist SSE event contains malformed JSON', {
        eventId: lastEventId,
        event: eventName || 'message',
        data: rawData,
        cause: error,
      })
    }
    await onEvent({
      id: lastEventId,
      event: eventName || 'message',
      data,
    })
    dataLines = []
    eventName = ''
  }

  async function processLine(line) {
    if (line === '') {
      await dispatch()
      return
    }
    if (line.startsWith(':'))
      return
    const colonIndex = line.indexOf(':')
    const field = colonIndex === -1 ? line : line.slice(0, colonIndex)
    let value = colonIndex === -1 ? '' : line.slice(colonIndex + 1)
    if (value.startsWith(' '))
      value = value.slice(1)
    if (field === 'data')
      dataLines.push(value)
    else if (field === 'event')
      eventName = value
    else if (field === 'id' && !value.includes('\0'))
      lastEventId = value
  }

  return {
    async push(text, endOfStream = false) {
      buffer += text
      while (true) {
        const line = nextLine(buffer, endOfStream)
        if (!line)
          break
        buffer = line[1]
        await processLine(line[0])
      }
      if (endOfStream)
        await dispatch()
    },
    getLastEventId() {
      return lastEventId
    },
  }
}

export async function fetchSse(url, {
  fetchImpl = globalThis.fetch,
  refreshAuth = refreshAccessTokenOrReLogin,
  headers = {},
  lastEventId = null,
  onEvent = () => {},
  signal,
} = {}) {
  const requestHeaders = {
    Accept: 'text/event-stream',
    ...headers,
  }
  if (lastEventId !== null && lastEventId !== undefined)
    requestHeaders['Last-Event-ID'] = String(lastEventId)

  const connect = () => {
    if (signal?.aborted)
      throw abortReason(signal)
    const csrfToken = getCsrfToken()
    delete requestHeaders[CSRF_HEADER_NAME]
    if (csrfToken)
      requestHeaders[CSRF_HEADER_NAME] = csrfToken
    return fetchImpl(url, {
      method: 'GET',
      credentials: 'include',
      headers: { ...requestHeaders },
      signal,
    })
  }
  let response = await connect()
  if (response.status === 401) {
    await response.body?.cancel?.().catch(() => {})
    try {
      await refreshForStream(refreshAuth, signal)
    }
    catch (error) {
      if (signal?.aborted)
        throw abortReason(signal)
      throw authenticationRequired()
    }
    // Reopen only this GET with the same durable cursor, never resubmit a Turn.
    response = await connect()
    if (response.status === 401) {
      await response.body?.cancel?.().catch(() => {})
      throw authenticationRequired()
    }
  }
  if (!response.ok) {
    const data = await readErrorData(response)
    const message = data && typeof data === 'object'
      ? data.message || data.error || response.statusText
      : data || response.statusText
    throw new FetchSseHttpError(message || `HTTP ${response.status}`, {
      status: response.status,
      data,
    })
  }

  if (response.status === 204)
    return { status: 204, lastEventId: lastEventId === null ? null : String(lastEventId) }

  const reader = response.body?.getReader?.()
  if (!reader)
    return { status: response.status, lastEventId: lastEventId === null ? null : String(lastEventId) }

  const parser = createParser({
    initialEventId: lastEventId === null ? null : String(lastEventId),
    onEvent,
  })
  const decoder = new TextDecoder()
  let cancelPromise = null
  let aborted = false
  const cancelReader = () => {
    if (!cancelPromise)
      cancelPromise = Promise.resolve(reader.cancel()).catch(() => {})
    return cancelPromise
  }
  const handleAbort = () => {
    aborted = true
    void cancelReader()
  }
  signal?.addEventListener('abort', handleAbort, { once: true })

  try {
    if (signal?.aborted)
      handleAbort()
    while (true) {
      if (aborted)
        throw abortReason(signal)
      const { done, value } = await reader.read()
      if (aborted)
        throw abortReason(signal)
      if (done) {
        await parser.push(decoder.decode(), true)
        break
      }
      await parser.push(decoder.decode(value, { stream: true }))
    }
    return { status: response.status, lastEventId: parser.getLastEventId() }
  }
  finally {
    signal?.removeEventListener('abort', handleAbort)
    await cancelReader()
    reader.releaseLock?.()
  }
}
