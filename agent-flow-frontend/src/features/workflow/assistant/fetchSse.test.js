import test from 'node:test'
import assert from 'node:assert/strict'

import { FetchSseHttpError, FetchSseParseError, fetchSse } from './fetchSse.js'

function responseFromReader(reader, { status = 200, contentType = 'text/event-stream' } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 409 ? 'Conflict' : 'OK',
    headers: { get: name => String(name).toLowerCase() === 'content-type' ? contentType : null },
    body: { getReader: () => reader },
  }
}

function chunkReader(chunks) {
  let index = 0
  return {
    async read() {
      if (index >= chunks.length)
        return { done: true, value: undefined }
      return { done: false, value: chunks[index++] }
    },
    async cancel() {},
    releaseLock() {},
  }
}

test('parses CRLF and LF frames across UTF-8 chunk boundaries with ids, event names, and multiline JSON', async () => {
  const source = [
    ': heartbeat\r\n',
    'id: 7\r\n',
    'event: message.delta\r\n',
    'data: {"event":"message.delta",\r\n',
    'data: "data":{"text":"你好"}}\r\n',
    '\r\n',
    ': another heartbeat\n\n',
  ].join('')
  const bytes = new TextEncoder().encode(source)
  const firstChineseByte = bytes.findIndex((value, index) => value === 0xE4 && bytes[index + 1] === 0xBD)
  const chunks = [
    bytes.slice(0, 5),
    bytes.slice(5, firstChineseByte + 1),
    bytes.slice(firstChineseByte + 1, firstChineseByte + 4),
    bytes.slice(firstChineseByte + 4),
  ]
  const received = []

  const result = await fetchSse('https://example.test/events', {
    fetchImpl: async () => responseFromReader(chunkReader(chunks)),
    onEvent: frame => received.push(frame),
  })

  assert.deepEqual(received, [{
    id: '7',
    event: 'message.delta',
    data: { event: 'message.delta', data: { text: '你好' } },
  }])
  assert.deepEqual(result, { status: 200, lastEventId: '7' })
})

test('id-only frames advance the resume cursor without dispatching fake events', async () => {
  const received = []
  const source = [
    'id: 12\n\n',
    'event: message.delta\n',
    'data: {"event":"message.delta","data":{"text":"next"}}\n\n',
    'id: 13\n\n',
  ].join('')

  const result = await fetchSse('/events', {
    fetchImpl: async () => responseFromReader(chunkReader([
      new TextEncoder().encode(source),
    ])),
    onEvent: frame => received.push(frame),
  })

  assert.deepEqual(received, [{
    id: '12',
    event: 'message.delta',
    data: { event: 'message.delta', data: { text: 'next' } },
  }])
  assert.deepEqual(result, { status: 200, lastEventId: '13' })
})

test('sends authenticated fetch headers, a resume id, and accepts a true empty 204', async () => {
  const originalDocument = globalThis.document
  globalThis.document = { cookie: 'csrf_token=csrf-value' }
  let request
  try {
    const result = await fetchSse('/console/api/events?after=3', {
      lastEventId: 9,
      headers: { 'X-Trace': 'trace-1' },
      fetchImpl: async (url, options) => {
        request = { url, options }
        return { ok: true, status: 204, headers: { get: () => null }, body: null }
      },
    })

    assert.equal(request.url, '/console/api/events?after=3')
    assert.equal(request.options.credentials, 'include')
    assert.equal(request.options.headers.Accept, 'text/event-stream')
    assert.equal(request.options.headers['X-CSRF-Token'], 'csrf-value')
    assert.equal(request.options.headers['X-Trace'], 'trace-1')
    assert.equal(request.options.headers['Last-Event-ID'], '9')
    assert.deepEqual(result, { status: 204, lastEventId: '9' })
  }
  finally {
    globalThis.document = originalDocument
  }
})

test('rejects a non-2xx JSON body as a typed HTTP error without creating an event', async () => {
  let eventCount = 0
  await assert.rejects(
    fetchSse('/events', {
      fetchImpl: async () => ({
        ok: false,
        status: 409,
        statusText: 'Conflict',
        headers: { get: () => 'application/json' },
        text: async () => '{"active_run":{"run_id":"run-2","epoch":2,"status":"running"},"latest_run":null}',
      }),
      onEvent: () => { eventCount += 1 },
    }),
    (error) => {
      assert.ok(error instanceof FetchSseHttpError)
      assert.equal(error.status, 409)
      assert.deepEqual(error.data, {
        active_run: { run_id: 'run-2', epoch: 2, status: 'running' },
        latest_run: null,
      })
      return true
    },
  )
  assert.equal(eventCount, 0)
})

test('rejects malformed event data and always cancels and releases the reader', async () => {
  let cancelled = 0
  let released = 0
  const reader = chunkReader([new TextEncoder().encode('id: 1\ndata: {bad json}\n\n')])
  reader.cancel = async () => { cancelled += 1 }
  reader.releaseLock = () => { released += 1 }

  await assert.rejects(
    fetchSse('/events', { fetchImpl: async () => responseFromReader(reader) }),
    error => error instanceof FetchSseParseError && error.eventId === '1',
  )
  assert.equal(cancelled, 1)
  assert.equal(released, 1)
})

test('AbortController cancellation stops the reader and releases its lock', async () => {
  const controller = new AbortController()
  let cancelled = 0
  let released = 0
  let settleRead
  const reader = {
    read() {
      return new Promise(resolve => { settleRead = resolve })
    },
    async cancel() {
      cancelled += 1
      settleRead?.({ done: true, value: undefined })
    },
    releaseLock() {
      released += 1
    },
  }
  const pending = fetchSse('/events', {
    signal: controller.signal,
    fetchImpl: async () => responseFromReader(reader),
  })

  await Promise.resolve()
  controller.abort()
  await assert.rejects(pending, error => error?.name === 'AbortError')
  assert.equal(cancelled, 1)
  assert.equal(released, 1)
})
