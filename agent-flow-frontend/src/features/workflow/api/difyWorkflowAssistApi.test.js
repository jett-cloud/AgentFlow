import test from 'node:test'
import assert from 'node:assert/strict'

import difyClient from '../../../shared/http/difyClient.js'
import * as workflowAssistApi from './difyWorkflowAssistApi.js'

async function withClientMethod(method, replacement, run) {
  const original = difyClient[method]
  difyClient[method] = replacement
  try {
    return await run()
  }
  finally {
    difyClient[method] = original
  }
}

test('conversation reads preserve server pagination and encode path coordinates', async () => {
  const calls = []
  await withClientMethod('get', async (...args) => {
    calls.push(args)
    return { items: [] }
  }, async () => {
    await workflowAssistApi.getWorkflowAssistConversations('app /1', { page: 3, limit: 17 })
    await workflowAssistApi.getWorkflowAssistRuns('app /1', 'conv /1', { after_epoch: 4, limit: 20 })
    await workflowAssistApi.getWorkflowAssistTimeline('app /1', 'conv /1', {
      after_epoch: 4,
      after_sequence: 9,
      limit: 50,
    })
    await workflowAssistApi.getWorkflowAssistCandidate('app /1', 'conv /1')
  })

  assert.deepEqual(calls, [
    ['/apps/app%20%2F1/workflow-assist/conversations', { params: { page: 3, limit: 17 } }],
    ['/apps/app%20%2F1/workflow-assist/conversations/conv%20%2F1/runs', { params: { after_epoch: 4, limit: 20 } }],
    ['/apps/app%20%2F1/workflow-assist/conversations/conv%20%2F1/timeline', {
      params: { after_epoch: 4, after_sequence: 9, limit: 50 },
    }],
    ['/apps/app%20%2F1/workflow-assist/conversations/conv%20%2F1/candidate'],
  ])
})

test('turn accepts the 202 result and sends only the exact v2 body', async () => {
  const accepted = { conversation_id: 'conv-1', run_id: 'run-1', epoch: 7, cursor: 0 }
  let call
  const result = await withClientMethod('post', async (...args) => {
    call = args
    return accepted
  }, () => workflowAssistApi.postWorkflowAssistTurn('app-1', 'conv-1', {
    message: 'build it',
    mode: 'workflow',
    model_config: { provider: 'openai', secret: 'server-reference-only' },
    selected_node: 'node-1',
    graph: { forbidden: true },
    draft_hash: 'forbidden',
    candidate_hash: 'forbidden',
  }))

  assert.equal(result, accepted)
  assert.deepEqual(call, [
    '/apps/app-1/workflow-assist/conversations/conv-1/turns',
    {
      message: 'build it',
      mode: 'workflow',
      model_config: { provider: 'openai', secret: 'server-reference-only' },
      selected_node: 'node-1',
    },
  ])
})

test('turn omits selected_node when it is not supplied', async () => {
  let body
  await withClientMethod('post', async (_path, payload) => {
    body = payload
    return { conversation_id: 'conv-1', run_id: 'run-1', epoch: 1, cursor: 0 }
  }, () => workflowAssistApi.postWorkflowAssistTurn('app-1', 'conv-1', {
    message: 'continue',
    mode: 'advanced-chat',
    model_config: {},
    selected_node: undefined,
  }))

  assert.deepEqual(body, {
    message: 'continue',
    mode: 'advanced-chat',
    model_config: {},
  })
})

test('abort sends only epoch and preserves the 409 reconciliation response', async () => {
  const reconciliation = {
    active_run: { run_id: 'run-2', epoch: 8, status: 'running' },
    latest_run: { run_id: 'run-2', epoch: 8, status: 'running' },
  }
  const conflict = Object.assign(new Error('conflict'), {
    response: { status: 409, data: reconciliation },
  })
  let call

  await assert.rejects(
    withClientMethod('post', async (...args) => {
      call = args
      throw conflict
    }, () => workflowAssistApi.postWorkflowAssistRunAbort('app-1', 'conv-1', 'run-1', {
      epoch: 7,
      run_id: 'forbidden',
      graph: { forbidden: true },
    })),
    error => error === conflict && error.response.data === reconciliation,
  )
  assert.deepEqual(call, [
    '/apps/app-1/workflow-assist/conversations/conv-1/runs/run-1/abort',
    { epoch: 7 },
  ])
})

test('abort rejects non-positive or non-integer epochs before making a request', async () => {
  let calls = 0
  for (const epoch of [0, '7']) {
    await assert.rejects(
      withClientMethod('post', async () => {
        calls += 1
      }, () => workflowAssistApi.postWorkflowAssistRunAbort('app-1', 'conv-1', 'run-1', { epoch })),
      /epoch must be a positive integer/,
    )
  }
  assert.equal(calls, 0)
})

test('apply sends only the server-owned candidate coordinate', async () => {
  let call
  await withClientMethod('post', async (...args) => {
    call = args
    return { applied: true }
  }, () => workflowAssistApi.postWorkflowAssistApply('app-1', {
    conversation_id: 'conv-1',
    hash: 'a'.repeat(64),
    graph: { forbidden: true },
    force: true,
    base_hash: 'forbidden',
    revision: 12,
    completion_evidence: { forbidden: true },
  }))

  assert.deepEqual(call, [
    '/apps/app-1/workflow-assist/apply',
    { conversation_id: 'conv-1', hash: 'a'.repeat(64) },
  ])
})

test('apply rejects a non-lowercase SHA-256 hash before making a request', async () => {
  let calls = 0
  await assert.rejects(
    withClientMethod('post', async () => {
      calls += 1
    }, () => workflowAssistApi.postWorkflowAssistApply('app-1', {
      conversation_id: 'conv-1',
      hash: 'A'.repeat(64),
    })),
    /hash must be a lowercase SHA-256/,
  )
  assert.equal(calls, 0)
})

test('run events use after only as the initial cursor and Last-Event-ID when resuming', async () => {
  const requests = []
  const received = []
  const fetchImpl = async (url, options) => {
    requests.push({ url: String(url), options })
    return {
      ok: true,
      status: 200,
      headers: { get: () => 'text/event-stream' },
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(
            'id: 10\nevent: done\ndata: {"event":"done","sequence":10}\n\n',
          ))
          controller.close()
        },
      }),
    }
  }

  const result = await workflowAssistApi.streamWorkflowAssistRunEvents(
    'app /1',
    'conv /1',
    'run /1',
    {
      after: 3,
      lastEventId: 9,
      fetchImpl,
      onEvent: event => received.push(event),
    },
  )

  assert.match(requests[0].url, /\/apps\/app%20%2F1\/workflow-assist\/conversations\/conv%20%2F1\/runs\/run%20%2F1\/events\?after=3$/)
  assert.equal(requests[0].options.headers['Last-Event-ID'], '9')
  assert.deepEqual(received, [{ event: 'done', sequence: 10 }])
  assert.deepEqual(result, { status: 200, lastEventId: '10' })
})

test('terminal run events accept an empty 204 response without a fake event', async () => {
  let eventCount = 0
  const result = await workflowAssistApi.streamWorkflowAssistRunEvents('app-1', 'conv-1', 'run-1', {
    after: 11,
    fetchImpl: async () => ({ ok: true, status: 204, headers: { get: () => null }, body: null }),
    onEvent: () => { eventCount += 1 },
  })

  assert.equal(eventCount, 0)
  assert.deepEqual(result, { status: 204, lastEventId: null })
})

test('rename sends only title on the title-only path', async () => {
  const updated = { id: 'conv-1', title: 'Invoice review' }
  let call
  const result = await withClientMethod('patch', async (...args) => {
    call = args
    return updated
  }, () => workflowAssistApi.patchWorkflowAssistConversationTitle('app /1', 'conv /1', {
    title: '  Invoice review  ',
    draft_hash: 'forbidden',
    state: { candidate_graph: { nodes: [] } },
  }))

  assert.equal(result, updated)
  assert.deepEqual(call, [
    '/apps/app%20%2F1/workflow-assist/conversations/conv%20%2F1/title',
    { title: 'Invoice review' },
  ])
})

test('rename rejects a blank title before making a request', async () => {
  let calls = 0
  await assert.rejects(
    withClientMethod('patch', async () => {
      calls += 1
    }, () => workflowAssistApi.patchWorkflowAssistConversationTitle('app-1', 'conv-1', '   ')),
    /title must be a non-empty string/,
  )
  assert.equal(calls, 0)
})

test('feature API no longer exports legacy stream, patch, validation, or catalogue calls', () => {
  for (const removed of [
    'streamWorkflowAssistChat',
    'postWorkflowAssistChatAbort',
    'updateWorkflowAssistConversation',
    'postWorkflowAssistValidate',
    'postWorkflowAssistHydrate',
    'getWorkflowAssistToolCatalogue',
    'getWorkflowAssistKnowledgeCatalogue',
  ])
    assert.equal(removed in workflowAssistApi, false, `${removed} must not remain in the v2 API`)
})
