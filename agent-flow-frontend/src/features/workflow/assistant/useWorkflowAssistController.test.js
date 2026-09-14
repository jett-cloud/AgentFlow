import test from 'node:test'
import assert from 'node:assert/strict'

import { createAssistSession, reduceAssist } from './assistStateMachine.js'
import { clarificationAnswerText } from './assistClarification.js'
import { createAssistStatusAnnouncement } from './assistLiveAnnouncement.js'
import { useWorkflowAssistController } from './useWorkflowAssistController.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function harness(streamHandler, overrides = {}) {
  const state = { value: createAssistSession() }
  const messages = { value: [] }
  const lastInstruction = { value: '' }
  const conversationId = { value: 'conversation-1' }
  const abortCalls = []
  const turns = new Map()
  let runNumber = 0
  const controller = useWorkflowAssistController({
    state,
    messages,
    lastInstruction,
    conversationId,
    hasSelectedModel: () => true,
    prepareInstruction: async () => true,
    buildPayload: turn => turn,
    submitTurn: async (payload) => {
      runNumber += 1
      const run = {
        conversation_id: conversationId.value,
        run_id: `legacy-test-run-${runNumber}`,
        epoch: runNumber,
        cursor: 0,
      }
      turns.set(run.run_id, payload)
      return run
    },
    streamRunEvents: async (run, options) => {
      await streamHandler(turns.get(run.run_id), options)
      return { status: 200, lastEventId: null }
    },
    abortChat: async (payload) => { abortCalls.push(payload) },
    dispatch: event => { state.value = reduceAssist(state.value, event) },
    reconcileConversation: async () => {},
    selectConversation: async id => `selected:${id}`,
    newConversation: async () => 'created',
    ...overrides,
  })
  return { controller, state, messages, lastInstruction, conversationId, abortCalls }
}

test('expired stream authentication preserves the running task and blocks retry or new turns', async () => {
  const phases = []
  const statuses = []
  let writes = 0
  const { controller, state, messages, abortCalls } = harness(async () => {}, {
    onRecoveryState: phase => phases.push(phase),
    onRunStatus: status => statuses.push(status),
    submitTurn: async () => { writes += 1; return { run_id: 'run-auth', epoch: 1 } },
    streamRunEvents: async () => {
      throw Object.assign(new Error('Sign in again'), { status: 401, data: { code: 'ASSIST_AUTH_REQUIRED' } })
    },
    retryRun: async () => { writes += 1 },
  })
  await controller.submitMessage('build')
  assert.equal(phases.at(-1), 'auth_required')
  assert.equal(state.value.phase, 'running')
  assert.equal(state.value.retryable, false)
  assert.equal(statuses.includes('error'), false)
  assert.equal(messages.value.some(message => message.text === 'Sign in again'), false)
  assert.deepEqual(await controller.submitMessage('accidental retry'), { accepted: false })
  assert.deepEqual(await controller.retryFailedStep(), { accepted: false })
  assert.equal(writes, 1)
  assert.equal(abortCalls.length, 0)
})

test('a real SSE reconnect after 401 keeps the original task and appends only its unseen suffix', async () => {
  const { fetchSse } = await import('./fetchSse.js')
  const urls = []
  let refreshes = 0
  let writes = 0
  const { controller, state, messages } = harness(async () => {}, {
    submitTurn: async () => { writes += 1; return { run_id: 'same-run', epoch: 1 } },
    waitForReconnect: async () => true,
    streamRunEvents: (run, options) => fetchSse(`/runs/${run.run_id}/events?after=${options.after}`, {
      ...options,
      onEvent: frame => options.onEvent(frame.data),
      refreshAuth: async () => { refreshes += 1 },
      fetchImpl: async (url) => {
        urls.push(url)
        if (urls.length === 2)
          return { ok: false, status: 401 }
        const events = urls.length === 1
          ? [envelope('same-run', 1, 1, 'message.delta', { message_id: 'reply', text: '开始' })]
          : [envelope('same-run', 1, 2, 'message.delta', { message_id: 'reply', text: '搭建' }), envelope('same-run', 1, 3, 'done')]
        return new Response(events.map(event => `id: ${event.sequence}\ndata: ${JSON.stringify(event)}\n\n`).join(''))
      },
    }),
  })
  await controller.submitMessage('build')
  assert.equal(writes, 1)
  assert.equal(refreshes, 1)
  assert.deepEqual(urls, ['/runs/same-run/events?after=0', '/runs/same-run/events?after=1', '/runs/same-run/events?after=1'])
  assert.equal(messages.value.find(message => message.kind === 'assistant_text')?.text, '开始搭建')
  assert.notEqual(state.value.phase, 'failed')
  assert.equal(state.value.retryable, false)
})

test('every turn awaits draft synchronization before submitting the v2 body', async () => {
  const calls = []
  const submitted = []
  const { controller, state, messages } = harness(async () => {}, {
    syncDraftIfDirty: async () => { calls.push('sync') },
    submitTurn: async (payload) => {
      calls.push(`turn:${payload.message}`)
      submitted.push(payload)
      return { conversation_id: 'conversation-1', run_id: `run-${submitted.length}`, epoch: submitted.length, cursor: 0 }
    },
    streamRunEvents: async (run, { onEvent }) => {
      if (run.run_id === 'run-1') {
        onEvent(envelope('run-1', 1, 1, 'waiting_user', {
          tool_call_id: 'ask-1',
          questions: [{ id: 'format', question: 'Format?', kind: 'text' }],
        }))
      }
      else {
        onEvent(envelope(run.run_id, run.epoch, 1, 'done', { summary: 'done' }))
      }
      return { status: 200, lastEventId: '1' }
    },
  })

  await controller.submitMessage('first')
  assert.equal(state.value.phase, 'waiting_user')
  await controller.submitClarification('ask-1', [{ question_id: 'format', text: 'markdown' }])
  messages.value.push({
    role: 'assistant',
    kind: 'clarification',
    clarification: { clarification_id: 'ask-2', questions: [{ id: 'q', question: 'More?', kind: 'text' }] },
    status: 'pending',
  })
  state.value = { ...state.value, phase: 'waiting_user', waitingUser: { tool_call_id: 'ask-2' } }
  await controller.submitMessage('third')

  assert.deepEqual(calls, [
    'sync', 'turn:first',
    'sync', 'turn:markdown',
    'sync', 'turn:third',
  ])
})

test('running supersede detaches the old fetch after draft sync and never calls abort API', async () => {
  const firstStream = deferred()
  const firstSubscribed = deferred()
  const calls = []
  let firstSignal
  let turnNumber = 0
  const { controller, abortCalls } = harness(async () => {}, {
    syncDraftIfDirty: async () => { calls.push('sync') },
    submitTurn: async (payload) => {
      turnNumber += 1
      calls.push(`turn:${payload.message}`)
      return { conversation_id: 'conversation-1', run_id: `run-${turnNumber}`, epoch: turnNumber, cursor: 0 }
    },
    streamRunEvents: async (run, { signal, onEvent }) => {
      if (run.run_id === 'run-1') {
        firstSignal = signal
        firstSubscribed.resolve()
        await firstStream.promise
      }
      else {
        onEvent(envelope('run-2', 2, 1, 'done', { summary: 'new' }))
      }
      return { status: 200, lastEventId: '1' }
    },
  })

  const first = controller.submitMessage('first')
  await firstSubscribed.promise
  assert.equal(firstSignal.aborted, false)
  await controller.submitMessage('second')

  assert.equal(firstSignal.aborted, true)
  assert.deepEqual(abortCalls, [])
  assert.deepEqual(calls, ['sync', 'turn:first', 'sync', 'turn:second'])
  firstStream.resolve()
  await first
})

function envelope(runId, epoch, sequence, event, data = {}) {
  return {
    event,
    run_id: runId,
    epoch,
    sequence,
    step_id: `${runId}:${sequence}`,
    created_at: '2026-08-25T00:00:00Z',
    data,
  }
}

function manualTimers() {
  const timers = []
  return {
    setTimeout(fn, delay) {
      const timer = { active: true, delay, fn }
      timers.push(timer)
      return timer
    },
    clearTimeout(timer) {
      timer.active = false
    },
    async runNext() {
      const timer = timers.find(item => item.active)
      assert.ok(timer, 'expected a scheduled timer')
      timer.active = false
      await timer.fn()
      await Promise.resolve()
    },
    active() {
      return timers.filter(item => item.active)
    },
  }
}

function manualReconnectWaits() {
  const waits = []
  return {
    wait(delay, signal) {
      const gate = deferred()
      const item = { delay, signal, release: () => gate.resolve(true) }
      signal.addEventListener('abort', () => gate.resolve(false), { once: true })
      waits.push(item)
      return gate.promise
    },
    waits,
  }
}

test('clarification answers serialize labels and supported scalar values', () => {
  const text = clarificationAnswerText([
    { question_id: 'knowledge', kind: 'resource_select', labels: [' Product docs ', 'Team wiki'] },
    { question_id: 'format', kind: 'text', text: ' markdown ' },
    { question_id: 'other', other_text: ' custom ' },
    { question_id: 'value', value: ' draft ' },
    { question_id: 'selected', selected_value: ' workflow ' },
    { question_id: 'empty', kind: 'text', text: '   ' },
  ])

  assert.equal(text, 'Product docs、Team wiki\nmarkdown\ncustom\ndraft\nworkflow')
})

test('composer send submits a Turn and reaches done', async () => {
  let payload
  const { controller, state } = harness(async (nextPayload, { onEvent }) => {
    payload = nextPayload
    onEvent({
      event: 'done',
      graph: { nodes: [], edges: [] },
      summary: 'ready',
      diff: { added: [], removed: [], updated: [] },
      validation: { ok: true, errors: [] },
    })
  })

  await controller.submitMessage('build a workflow')

  assert.equal(payload.message, 'build a workflow')
  assert.equal(state.value.phase, 'idle')
  assert.equal(state.value.applyEnabled, true)
})

test('running send supersedes, detaches the old fetch, and does not call abort API', async () => {
  const first = deferred()
  const firstSubscribed = deferred()
  const payloads = []
  let firstSignal
  const { controller, state, abortCalls, messages } = harness(async (payload, options) => {
    payloads.push(payload.message)
    if (payload.message === 'first') {
      firstSignal = options.signal
      firstSubscribed.resolve()
      await first.promise
      return
    }
    options.onEvent({
      event: 'done',
      graph: { nodes: [], edges: [] },
      validation: { ok: true, errors: [] },
    })
  })

  const firstTurn = controller.submitMessage('first')
  await firstSubscribed.promise
  assert.equal(state.value.phase, 'running')
  await controller.submitMessage('second')
  assert.equal(firstSignal.aborted, true)
  first.resolve()
  await firstTurn

  assert.deepEqual(payloads, ['first', 'second'])
  assert.deepEqual(abortCalls, [])
  assert.equal(state.value.terminationReason, null)
  assert.equal(
    messages.value.some(message => message.text === '已根据你的新消息停止上一轮；已写入的候选图保留。'),
    true,
  )
})

test('explicit stop sends the exact run and epoch fence and does not enable apply', async () => {
  const active = deferred()
  const { controller, state, abortCalls } = harness(async (_payload, { signal }) => {
    await new Promise((resolve) => {
      signal.addEventListener('abort', resolve, { once: true })
    })
    await active.promise
  }, {
    getRunCoordinates: () => ({
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      epoch: 7,
      cursor: 3,
    }),
  })

  const turn = controller.submitMessage('build a workflow')
  for (let index = 0; index < 5 && state.value.phase !== 'running'; index += 1)
    await Promise.resolve()
  await controller.stopActiveTurn()

  assert.deepEqual(abortCalls, [{
    conversation_id: 'conversation-1',
    run_id: 'run-1',
    epoch: 7,
  }])
  assert.equal(state.value.phase, 'idle')
  assert.equal(state.value.applyEnabled, false)
  assert.equal(state.value.terminationReason, 'user_abort')
  active.resolve()
  await turn
})

test('explicit stop keeps visible assistant text and does not add a retry-step button', async () => {
  const active = deferred()
  const { controller, state, messages } = harness(async (_payload, { signal, onEvent }) => {
    onEvent(envelope('run-1', 7, 1, 'message.delta', {
      text: '正在创建节点',
      message_id: 'msg-1',
      delta_index: 0,
    }))
    await new Promise((resolve) => {
      signal.addEventListener('abort', resolve, { once: true })
    })
    await active.promise
  }, {
    getRunCoordinates: () => ({
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      epoch: 7,
      cursor: 3,
    }),
    submitTurn: async () => ({
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      epoch: 7,
      cursor: 0,
    }),
  })

  const turn = controller.submitMessage('build a workflow')
  for (let index = 0; index < 20 && !messages.value.some(message => message.kind === 'assistant_text'); index += 1)
    await Promise.resolve()
  await controller.stopActiveTurn()

  const bubble = messages.value.find(message => message.kind === 'assistant_text')
  assert.equal(bubble?.text, '正在创建节点')
  assert.equal(bubble?.streaming, false)
  assert.equal(state.value.terminationReason, 'user_abort')
  assert.equal(
    messages.value.some(message => message.kind === 'retry_step' || message.retry_step),
    false,
  )
  active.resolve()
  await turn
})

test('tearing SSE without stop keeps the run alive and does not abort', async () => {
  const active = deferred()
  const { controller, state, abortCalls } = harness(async (_payload, { signal }) => {
    await new Promise((resolve) => {
      signal.addEventListener('abort', resolve, { once: true })
    })
    await active.promise
  })

  const turn = controller.submitMessage('build a workflow')
  for (let index = 0; index < 5 && state.value.phase !== 'running'; index += 1)
    await Promise.resolve()
  controller.detachActiveTurn()
  active.resolve()
  await turn

  assert.deepEqual(abortCalls, [])
  assert.equal(state.value.phase, 'running')
  assert.notEqual(state.value.terminationReason, 'user_abort')
  assert.notEqual(state.value.terminationReason, 'transport_disconnect')
})

test('waiting_user card and typed answers share the same chat stream', async () => {
  const payloads = []
  const { controller, state, messages } = harness(async (payload, { onEvent }) => {
    payloads.push(payload)
    if (payload.message === 'build a workflow') {
      onEvent({
        event: 'waiting_user',
        tool_call_id: 'ask-1',
        questions: [{ id: 'format', question: 'Format?', kind: 'text' }],
      })
      return
    }
    onEvent({
      event: 'done',
      graph: { nodes: [], edges: [] },
      validation: { ok: true, errors: [] },
    })
  })

  await controller.submitMessage('build a workflow')
  assert.equal(state.value.phase, 'waiting_user')
  assert.equal(messages.value.at(-1).kind, 'clarification')
  assert.equal(messages.value.at(-1).clarification.questions[0].question, 'Format?')

  await controller.submitClarification('ask-1', [{ question_id: 'format', kind: 'text', text: 'markdown' }])
  await controller.submitMessage('用文件上传')

  assert.deepEqual(payloads.map(item => item.message), [
    'build a workflow',
    'markdown',
    '用文件上传',
  ])
  assert.equal(payloads.every(item => !item.request_kind), true)
})

test('stop 409 reconciles authoritative summaries without marking a stale run aborted', async () => {
  const facts = {
    active_run: { run_id: 'run-2', epoch: 8, status: 'running' },
    latest_run: { run_id: 'run-2', epoch: 8, status: 'running' },
  }
  const conflict = Object.assign(new Error('conflict'), {
    response: { status: 409, data: facts },
  })
  const reconciled = []
  const { controller, state } = harness(async () => {}, {
    getRunCoordinates: () => ({
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      epoch: 7,
      cursor: 3,
    }),
    abortChat: async () => { throw conflict },
    reconcileRunCoordinates: payload => reconciled.push(payload),
    streamRunEvents: async () => ({ status: 204, lastEventId: null }),
  })
  state.value = { ...state.value, phase: 'running' }

  const stopped = await controller.stopActiveTurn()

  assert.equal(stopped, false)
  assert.equal(state.value.phase, 'running')
  assert.equal(state.value.terminationReason, null)
  assert.deepEqual(reconciled[0], { conversation_id: 'conversation-1', ...facts })
})

test('resource-select clarification labels create a new user turn', async () => {
  const payloads = []
  const { controller, messages } = harness(async (payload, { onEvent }) => {
    payloads.push(payload.message)
    if (payload.message === 'build a workflow') {
      onEvent({
        event: 'waiting_user',
        tool_call_id: 'ask-resource',
        questions: [{ id: 'knowledge', question: 'Which knowledge base?', kind: 'resource_select' }],
      })
      return
    }
    onEvent({ event: 'done', graph: { nodes: [], edges: [] }, validation: { ok: true, errors: [] } })
  })

  await controller.submitMessage('build a workflow')
  await controller.submitClarification('ask-resource', [
    { question_id: 'knowledge', kind: 'resource_select', labels: ['Product docs'] },
  ])

  assert.deepEqual(payloads, ['build a workflow', 'Product docs'])
  assert.equal(messages.value.some(message => message.role === 'user' && message.text === 'Product docs'), true)
})

test('selected-value clarification creates a new user turn', async () => {
  const payloads = []
  const { controller, messages } = harness(async (payload, { onEvent }) => {
    payloads.push(payload.message)
    if (payload.message === 'build a workflow') {
      onEvent({
        event: 'waiting_user',
        tool_call_id: 'ask-mode',
        questions: [{ id: 'mode', question: 'Which mode?', kind: 'select' }],
      })
      return
    }
    onEvent({ event: 'done', graph: { nodes: [], edges: [] }, validation: { ok: true, errors: [] } })
  })

  await controller.submitMessage('build a workflow')
  await controller.submitClarification('ask-mode', [
    { question_id: 'mode', kind: 'select', selected_value: 'workflow' },
  ])

  assert.deepEqual(payloads, ['build a workflow', 'workflow'])
  assert.equal(messages.value.some(message => message.role === 'user' && message.text === 'workflow'), true)
})

test('empty clarification submission leaves the card pending', async () => {
  const payloads = []
  const { controller, messages, state } = harness(async (payload, { onEvent }) => {
    payloads.push(payload.message)
    onEvent({
      event: 'waiting_user',
      tool_call_id: 'ask-empty',
      questions: [{ id: 'format', question: 'Format?', kind: 'text' }],
    })
  })

  await controller.submitMessage('build a workflow')
  await controller.submitClarification('ask-empty', [{ question_id: 'format', kind: 'text', text: '   ' }])

  const card = messages.value.find(message => message.kind === 'clarification')
  assert.deepEqual(payloads, ['build a workflow'])
  assert.equal(state.value.phase, 'waiting_user')
  assert.equal(card.status, 'pending')
  assert.equal(card.resolved, false)
})

test('waiting_user string questions still render as clarification prompts', async () => {
  const { controller, messages } = harness(async (_payload, { onEvent }) => {
    onEvent({
      event: 'waiting_user',
      tool_call_id: 'ask-2',
      questions: ['知识库选哪个？', { prompt: '输出格式用什么？' }],
    })
  })

  await controller.submitMessage('build a workflow')
  const card = messages.value.find(message => message.kind === 'clarification')
  assert.deepEqual(card.clarification.questions.map(question => question.question), [
    '知识库选哪个？',
    '输出格式用什么？',
  ])
})

test('composer send during waiting_user resolves the pending clarification card', async () => {
  const { controller, state, messages } = harness(async (payload, { onEvent }) => {
    if (payload.message === 'build a workflow') {
      onEvent({
        event: 'waiting_user',
        tool_call_id: 'ask-1',
        questions: [{ id: 'format', question: 'Format?', kind: 'text' }],
      })
      return
    }
    onEvent({
      event: 'done',
      graph: { nodes: [], edges: [] },
      validation: { ok: true, errors: [] },
    })
  })

  await controller.submitMessage('build a workflow')
  const card = messages.value.find(message => message.kind === 'clarification')
  assert.equal(state.value.phase, 'waiting_user')
  assert.equal(card.status, 'pending')
  assert.equal(card.resolved, false)

  await controller.submitMessage('用文件上传')

  const resolved = messages.value.find(message => message.kind === 'clarification')
  assert.equal(resolved.status, 'resolved')
  assert.equal(resolved.resolved, true)
})

test('failed stream does not enable apply', async () => {
  const { controller, state } = harness(async (_payload, { onEvent }) => {
    onEvent({ event: 'failed', reason: 'cannot continue' })
  })

  await controller.submitMessage('build a workflow')

  assert.equal(state.value.phase, 'idle')
  assert.equal(state.value.applyEnabled, false)
})

test('cancelled or late request events cannot mutate a newer conversation', async () => {
  const first = deferred()
  const firstSubscribed = deferred()
  let staleOnEvent
  const { controller, messages } = harness(async (payload, options) => {
    if (payload.message === 'first') {
      staleOnEvent = options.onEvent
      firstSubscribed.resolve()
      await first.promise
      return
    }
    options.onEvent({
      event: 'done',
      graph: { nodes: [{ id: 'new' }], edges: [] },
      summary: 'new',
      validation: { ok: true, errors: [] },
    })
  })

  const firstTurn = controller.submitMessage('first')
  await firstSubscribed.promise
  await controller.submitMessage('second')
  staleOnEvent({
    event: 'done',
    graph: { nodes: [{ id: 'stale' }], edges: [] },
    summary: 'stale',
    validation: { ok: true, errors: [] },
  })
  first.resolve()
  await firstTurn

  const completions = messages.value.filter(message => message.kind === 'completion')
  assert.equal(completions.length, 1)
  assert.equal(completions[0].summary, 'new')
})

test('conversation changes cancel the active turn without calling abort API', async () => {
  const active = deferred()
  const subscribed = deferred()
  let capturedSignal
  const { controller, abortCalls } = harness(async (_payload, { signal }) => {
    capturedSignal = signal
    subscribed.resolve()
    await active.promise
  })

  const turn = controller.submitMessage('first')
  await subscribed.promise
  const selected = await controller.selectConversation('conversation-2')

  assert.equal(capturedSignal.aborted, true)
  assert.equal(selected, 'selected:conversation-2')
  assert.deepEqual(abortCalls, [])
  active.resolve()
  await turn
})

test('recoverable mount loads conversations, full timeline, candidate, reconciliation, then SSE', async () => {
  const calls = []
  const { controller, messages } = harness(async () => {}, {
    loadConversations: async () => {
      calls.push('conversations')
      return { items: [{ id: 'conversation-1' }] }
    },
    selectConversation: async (id) => {
      calls.push(`select:${id}`)
      return true
    },
    loadTimeline: async (_conversationId, params) => {
      calls.push(`timeline:${params.after_epoch}:${params.after_sequence}`)
      if (params.after_sequence === 0) {
        return {
          items: [
            envelope('run-1', 1, 0, 'user.message', { text: 'restored' }),
            envelope('run-1', 1, 1, 'status', { status: 'running' }),
          ],
          has_more: true,
          cursor: { epoch: 1, sequence: 1 },
        }
      }
      return {
        items: [envelope('run-1', 1, 2, 'message.delta', { text: 'continued' })],
        has_more: false,
        cursor: { epoch: 1, sequence: 2 },
      }
    },
    loadCandidate: async () => {
      calls.push('candidate')
      return {
        graph: { nodes: [], edges: [] },
        revision: 3,
        active_run: { run_id: 'run-1', epoch: 1, status: 'running' },
        latest_run: { run_id: 'run-1', epoch: 1, status: 'running' },
      }
    },
    getRunCoordinates: () => ({
      conversation_id: 'conversation-1',
      run_id: 'stale-run',
      epoch: 99,
      cursor: 99,
    }),
    reconcileRunCoordinates: (snapshot) => {
      calls.push(`reconcile:${snapshot.active_run.run_id}`)
      return snapshot.active_run
    },
    streamRunEvents: async (run, options) => {
      calls.push(`sse:${run.run_id}:${options.after}`)
      return { status: 204, lastEventId: String(options.after) }
    },
  })

  await controller.mountRecoverableSession()

  assert.deepEqual(calls, [
    'conversations',
    'select:conversation-1',
    'candidate',
    'timeline:0:0',
    'timeline:1:1',
    'reconcile:run-1',
    'sse:run-1:2',
    'candidate',
    'reconcile:run-1',
  ])
  assert.equal(messages.value.some(message => message.role === 'user' && message.text === 'restored'), true)
  assert.equal(messages.value.find(message => message.kind === 'assistant_text')?.text, 'continued')
})

test('timeline recovery paints each page while keeping submission blocked', async () => {
  const secondPage = deferred()
  const paints = []
  const { controller, messages } = harness(async () => {}, {
    selectConversation: async () => true,
    loadTimeline: async (_id, params) => {
      paints.push(messages.value.filter(message => message.role === 'user').map(message => message.text))
      if (params.after_epoch === 0 && params.after_sequence === 0) {
        return {
          items: [envelope('run-1', 1, 0, 'user.message', { text: 'first' })],
          has_more: true,
          cursor: { epoch: 1, sequence: 0 },
        }
      }
      await secondPage.promise
      return {
        items: [envelope('run-1', 1, 1, 'user.message', { text: 'second' })],
        has_more: false,
        cursor: { epoch: 1, sequence: 1 },
      }
    },
    loadCandidate: async () => ({
      revision: 0,
      active_run: null,
      latest_run: { run_id: 'run-1', epoch: 1, status: 'done' },
    }),
  })

  const recovery = controller.selectConversation('conversation-1')
  while (paints.length < 2)
    await Promise.resolve()
  assert.deepEqual(paints[0], [])
  assert.deepEqual(paints[1], ['first'])
  assert.deepEqual(await controller.submitMessage('accidental input'), { accepted: false })
  secondPage.resolve()
  await recovery
  assert.deepEqual(
    messages.value.filter(message => message.role === 'user').map(message => message.text),
    ['first', 'second'],
  )
})

test('history snapshot is visible before candidate and timeline finish loading', async () => {
  const candidate = deferred()
  const timeline = deferred()
  const phases = []
  const { controller, messages } = harness(async () => {}, {
    onRecoveryState: phase => phases.push(phase),
    loadConversation: async () => ({ messages: [
      { id: 'u1', role: 'user', event_type: 'message', payload: { text: 'previous request' } },
    ] }),
    loadCandidate: () => candidate.promise,
    loadTimeline: () => timeline.promise,
  })
  const recovery = controller.selectConversation('conversation-1')
  for (let index = 0; index < 10; index += 1)
    await Promise.resolve()
  assert.equal(messages.value[0]?.text, 'previous request')
  assert.equal(phases.at(-1), 'loading')
  assert.deepEqual(await controller.submitMessage('too early'), { accepted: false })
  candidate.resolve({ revision: 0, active_run: null })
  timeline.resolve({ items: [envelope('run-1', 1, 0, 'user.message', { text: 'previous request' })], has_more: false })
  assert.equal(await recovery, true)
  assert.equal(phases.at(-1), 'ready')
  assert.equal(messages.value.filter(message => message.role === 'user').length, 1)
})

test('failed initial history load blocks turns and retries until recovery or explicit new conversation', async () => {
  const listing = deferred()
  const phases = []
  let writes = 0
  const { controller } = harness(async () => {}, {
    onRecoveryState: phase => phases.push(phase),
    loadConversations: () => listing.promise,
    loadConversation: async () => ({ messages: [] }),
    loadCandidate: async () => ({ revision: 0 }),
    submitTurn: async () => { writes += 1 },
    retryRun: async () => { writes += 1 },
  })
  const recovery = controller.mountRecoverableSession()
  assert.deepEqual(await controller.submitMessage('before list'), { accepted: false })
  listing.reject(new Error('history unavailable'))
  await recovery
  assert.equal(phases.at(-1), 'error')
  assert.deepEqual(await controller.submitMessage('after error'), { accepted: false })
  await controller.retryFailedStep()
  assert.equal(writes, 0)
  await controller.newConversation()
  assert.equal(phases.at(-1), 'ready')
})

test('terminal recovery prefers conversation snapshot over timeline deltas', async () => {
  let timelineCalls = 0
  const { controller, messages } = harness(async () => {}, {
    selectConversation: async () => true,
    loadConversation: async () => ({
      conversation: { id: 'conversation-1' },
      messages: [
        { id: 'u1', role: 'user', event_type: 'message', payload: { text: 'snapshot user' } },
        { id: 'a1', role: 'assistant', event_type: 'message', payload: { text: 'snapshot assistant' } },
      ],
    }),
    loadTimeline: async () => {
      timelineCalls += 1
      return {
        items: [
          envelope('run-1', 1, 0, 'user.message', { text: 'timeline user' }),
          envelope('run-1', 1, 1, 'message.delta', { text: 'a' }),
          envelope('run-1', 1, 2, 'message.delta', { text: 'b' }),
        ],
        has_more: false,
      }
    },
    loadCandidate: async () => ({
      revision: 0,
      active_run: null,
      latest_run: { run_id: 'run-1', epoch: 1, status: 'done' },
    }),
  })

  await controller.selectConversation('conversation-1')

  assert.equal(timelineCalls, 0)
  assert.equal(messages.value.some(message => message.text === 'snapshot user'), true)
  assert.equal(messages.value.some(message => message.text === 'snapshot assistant'), true)
  assert.equal(messages.value.some(message => message.text === 'timeline user'), false)
  assert.equal(messages.value.some(message => message.streaming), false)
})

test('terminal recovery falls back to timeline when the latest snapshot reply has no text', async () => {
  let timelineCalls = 0
  const { controller, messages } = harness(async () => {}, {
    selectConversation: async () => true,
    loadConversation: async () => ({
      conversation: { id: 'conversation-1' },
      messages: [
        { id: 'u1', role: 'user', event_type: 'message', sequence: 1, payload: { text: '这个工作流是干什么的？' } },
        {
          id: 'a1',
          role: 'assistant',
          event_type: 'message',
          sequence: 2,
          payload: { text: '', reasoning: '先读取工作流结构', message_id: 'agent-message-1' },
        },
        {
          id: 'c1',
          role: 'assistant',
          event_type: 'tool_call',
          sequence: 3,
          payload: { id: 'call-1', name: 'read_graph', arguments: {} },
        },
        {
          id: 'r1',
          role: 'assistant',
          event_type: 'tool_result',
          sequence: 4,
          payload: { tool_call_id: 'call-1', name: 'read_graph', ok: true, content: { summary: 'empty' } },
        },
      ],
    }),
    loadTimeline: async () => {
      timelineCalls += 1
      return {
        items: [
          envelope('run-1', 1, 0, 'user.message', { text: '这个工作流是干什么的？' }),
          envelope('run-1', 1, 1, 'reasoning.delta', { text: '先读取工作流结构', message_id: 'agent-message-1' }),
          envelope('run-1', 1, 2, 'tool_call', { tool_call_id: 'call-1', name: 'read_graph', arguments: {} }),
          envelope('run-1', 1, 3, 'tool_result', { tool_call_id: 'call-1', name: 'read_graph', ok: true }),
          envelope('run-1', 1, 4, 'message.delta', { text: '当前工作流画布是空的，', message_id: 'agent-message-2' }),
          envelope('run-1', 1, 5, 'message.delta', { text: '还没有任何节点和连线。', message_id: 'agent-message-2' }),
          envelope('run-1', 1, 6, 'turn_complete', {}),
        ],
        has_more: false,
      }
    },
    loadCandidate: async () => ({
      revision: 0,
      active_run: null,
      latest_run: { run_id: 'run-1', epoch: 1, status: 'turn_complete' },
    }),
  })

  await controller.selectConversation('conversation-1')

  assert.equal(timelineCalls, 1)
  assert.equal(
    messages.value.find(message => message.kind === 'assistant_text' && message.message_id === 'agent-message-2')?.text,
    '当前工作流画布是空的，还没有任何节点和连线。',
  )
  const activities = messages.value.filter(message => message.kind === 'activity')
  assert.equal(activities.length, 1)
  assert.deepEqual(activities[0].items.map(item => item.key), ['tool:call-1'])
  assert.equal(messages.value.filter(message => message.role === 'user').length, 1)
})

test('terminal recovery never opens an EventSource', async () => {
  let streamCalls = 0
  const { controller } = harness(async () => {}, {
    selectConversation: async () => true,
    loadConversation: async () => ({
      conversation: { id: 'conversation-1' },
      messages: [{ id: 'u1', role: 'user', event_type: 'message', payload: { text: 'done' } }],
    }),
    loadTimeline: async () => ({ items: [], has_more: false }),
    loadCandidate: async () => ({
      revision: 0,
      active_run: null,
      latest_run: { run_id: 'run-1', epoch: 1, status: 'done' },
    }),
    streamRunEvents: async () => {
      streamCalls += 1
      return { status: 200, lastEventId: '0' }
    },
  })

  await controller.selectConversation('conversation-1')
  assert.equal(streamCalls, 0)
})

test('switching recoverable conversations aborts the previous live stream', async () => {
  const firstStream = deferred()
  const subscribed = deferred()
  let firstSignal
  let firstOnEvent
  const { controller, messages, conversationId } = harness(async () => {}, {
    selectConversation: async (id) => {
      conversationId.value = String(id)
      return true
    },
    loadTimeline: async (id) => ({
      items: [envelope(`run-${id.at(-1)}`, Number(id.at(-1)), 0, 'user.message', { text: id })],
      has_more: false,
    }),
    loadCandidate: async (id) => ({
      revision: 0,
      active_run: { run_id: `run-${id.at(-1)}`, epoch: Number(id.at(-1)), status: 'running' },
      latest_run: { run_id: `run-${id.at(-1)}`, epoch: Number(id.at(-1)), status: 'running' },
    }),
    streamRunEvents: async (run, options) => {
      if (run.run_id === 'run-2') {
        firstSignal = options.signal
        firstOnEvent = options.onEvent
        subscribed.resolve()
        await firstStream.promise
        return { status: 200, lastEventId: '0' }
      }
      return { status: 204, lastEventId: '0' }
    },
  })

  const first = controller.selectConversation('conversation-2')
  await subscribed.promise
  await controller.selectConversation('conversation-3')
  firstOnEvent(envelope('run-2', 2, 1, 'message.delta', { text: 'stale delta' }))
  firstStream.resolve()
  await first

  assert.equal(firstSignal.aborted, true)
  assert.equal(conversationId.value, 'conversation-3')
  assert.equal(messages.value.some(message => message.text === 'stale delta'), false)
  assert.equal(messages.value.some(message => message.text === 'conversation-3'), true)
})

test('recovering an authoritative running Run never regresses its announcement to queued', async () => {
  const announcements = []
  const dispatched = []
  const live = createAssistStatusAnnouncement({
    onAnnounce: text => announcements.push(text),
  })
  const announce = status => live.update('run', status, status)
  let mounted
  mounted = harness(async () => {}, {
    dispatch(event) {
      dispatched.push(event)
      mounted.state.value = reduceAssist(mounted.state.value, event)
    },
    loadConversations: async () => ({ items: [{ id: 'conversation-1' }] }),
    selectConversation: async () => true,
    loadTimeline: async () => ({ items: [], has_more: false }),
    loadCandidate: async () => ({
      graph: { nodes: [], edges: [] },
      revision: 0,
      active_run: { run_id: 'run-1', epoch: 1, status: 'running' },
      latest_run: { run_id: 'run-1', epoch: 1, status: 'running' },
    }),
    onRunStatus: announce,
    reconcileRunCoordinates: () => {},
    streamRunEvents: async () => ({ status: 204, lastEventId: '0' }),
  })

  await mounted.controller.mountRecoverableSession()

  assert.deepEqual(announcements, ['running'])
  assert.equal(mounted.state.value.phase, 'running')
  assert.equal(dispatched.filter(event => event.type === 'SEND').length, 1)
})

test('a real new Turn announces queued once before authoritative running and deduplicates replay', async () => {
  const announcements = []
  const callbackTrace = []
  const dispatched = []
  const live = createAssistStatusAnnouncement({
    onAnnounce: text => announcements.push(text),
  })
  const announce = status => live.update('run', status, status)
  let mounted
  mounted = harness(async () => {}, {
    dispatch(event) {
      dispatched.push(event)
      mounted.state.value = reduceAssist(mounted.state.value, event)
    },
    submitTurn: async () => ({
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      epoch: 1,
      cursor: 0,
      status: 'queued',
    }),
    onRunStatus(status, coordinates) {
      callbackTrace.push({
        status,
        source: coordinates.source,
        sequence: coordinates.sequence ?? null,
      })
      announce(status)
    },
    streamRunEvents: async (_run, { onEvent }) => {
      onEvent(envelope('run-1', 1, 1, 'status', { status: 'queued' }))
      onEvent(envelope('run-1', 1, 1, 'status', { status: 'queued' }))
      onEvent(envelope('run-1', 1, 2, 'status', { status: 'running' }))
      onEvent(envelope('run-1', 1, 2, 'status', { status: 'running' }))
      onEvent(envelope('run-1', 1, 3, 'done', { summary: 'done' }))
      return { status: 200, lastEventId: '3' }
    },
  })

  await mounted.controller.submitMessage('build it')

  assert.deepEqual(announcements, ['queued', 'running', 'done'])
  assert.deepEqual(callbackTrace, [
    { status: 'queued', source: 'submitted', sequence: null },
    { status: 'running', source: 'event', sequence: 2 },
    { status: 'done', source: 'event', sequence: 3 },
  ])
  assert.equal(dispatched.filter(event => event.type === 'SEND').length, 1)
})

test('idle disconnect reconnects the same run from the latest reduced sequence', async () => {
  const calls = []
  const { controller, messages } = harness(async () => {}, {
    waitForReconnect: async () => true,
    streamRunEvents: async (run, options) => {
      calls.push({ run: { ...run }, after: options.after, lastEventId: options.lastEventId })
      if (calls.length === 1) {
        options.onEvent(envelope('run-1', 4, 6, 'message.delta', { text: 'hello' }))
        return { status: 200, lastEventId: '6' }
      }
      options.onEvent(envelope('run-1', 4, 7, 'done', { summary: 'complete' }))
      return { status: 200, lastEventId: '7' }
    },
  })

  await controller.resumeActiveTurn({ run_id: 'run-1', epoch: 4, cursor: 5 })

  assert.deepEqual(calls.map(call => ({ after: call.after, lastEventId: call.lastEventId })), [
    { after: 5, lastEventId: 5 },
    { after: 6, lastEventId: 6 },
  ])
  assert.equal(messages.value.find(message => message.kind === 'assistant_text').text, 'hello')
})

test('a transient fetch disconnect reconnects without changing the resume cursor', async () => {
  const calls = []
  const { controller } = harness(async () => {}, {
    waitForReconnect: async () => true,
    streamRunEvents: async (_run, options) => {
      calls.push(options.after)
      if (calls.length === 1)
        throw new TypeError('network connection lost')
      options.onEvent(envelope('run-1', 4, 6, 'done', { summary: 'complete' }))
      return { status: 200, lastEventId: '6' }
    },
  })

  await controller.resumeActiveTurn({ run_id: 'run-1', epoch: 4, cursor: 5 })

  assert.deepEqual(calls, [5, 5])
})

test('a network error after a terminal event refreshes facts without delay or reconnect', async () => {
  let streamCalls = 0
  let terminalCalls = 0
  let candidateCalls = 0
  let runCalls = 0
  const delays = []
  const reconciles = []
  const { controller } = harness(async () => {}, {
    waitForReconnect: async (delay) => {
      delays.push(delay)
      return true
    },
    loadCandidate: async () => {
      candidateCalls += 1
      return {
        revision: 0,
        active_run: null,
        latest_run: { run_id: 'run-1', epoch: 1, status: 'done' },
      }
    },
    loadRunSummaries: async () => {
      runCalls += 1
      return { items: [{ run_id: 'run-1', epoch: 1, status: 'done' }] }
    },
    reconcileRunCoordinates: snapshot => reconciles.push(snapshot),
    onRunTerminal: () => { terminalCalls += 1 },
    streamRunEvents: async (_run, options) => {
      streamCalls += 1
      if (streamCalls === 1) {
        options.onEvent(envelope('run-1', 1, 1, 'done', { summary: 'complete' }))
        throw new TypeError('connection reset after terminal frame')
      }
      return { status: 204, lastEventId: '1' }
    },
  })

  await controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, cursor: 0 })

  assert.equal(streamCalls, 1)
  assert.deepEqual(delays, [])
  assert.equal(terminalCalls, 1)
  assert.equal(candidateCalls, 1)
  assert.equal(runCalls, 1)
  assert.equal(reconciles.length, 1)
})

test('an id-only SSE cursor is persisted and used for the next reconnect', async () => {
  const calls = []
  const cursors = []
  const { controller } = harness(async () => {}, {
    onRunCursor: cursor => cursors.push(cursor),
    waitForReconnect: async () => true,
    streamRunEvents: async (_run, options) => {
      calls.push(options.after)
      if (calls.length === 1)
        return { status: 200, lastEventId: '6' }
      options.onEvent(envelope('run-1', 4, 7, 'done', { summary: 'complete' }))
      return { status: 200, lastEventId: '7' }
    },
  })

  await controller.resumeActiveTurn({ run_id: 'run-1', epoch: 4, cursor: 5 })

  assert.deepEqual(calls, [5, 6])
  assert.deepEqual(cursors, [6, 7])
})

test('a late lower sequence never regresses the persisted resume cursor', async () => {
  const cursors = []
  const { controller } = harness(async () => {}, {
    onRunCursor: cursor => cursors.push(cursor),
    streamRunEvents: async (_run, options) => {
      options.onEvent(envelope('run-1', 4, 6, 'message.delta', { text: 'newer' }))
      options.onEvent(envelope('run-1', 4, 5, 'message.delta', { text: 'late' }))
      options.onEvent(envelope('run-1', 4, 7, 'done', { summary: 'complete' }))
      return { status: 200, lastEventId: '7' }
    },
  })

  await controller.resumeActiveTurn({ run_id: 'run-1', epoch: 4, cursor: 4 })

  assert.deepEqual(cursors, [6, 6, 7])
})

test('answering a waiting-user terminal creates and adopts a new run', async () => {
  const submitted = []
  const streamed = []
  const { controller, messages } = harness(async () => {}, {
    submitTurn: async (payload) => {
      const run = payload.message === 'build'
        ? { conversation_id: 'conversation-1', run_id: 'run-old', epoch: 1, cursor: 0 }
        : { conversation_id: 'conversation-1', run_id: 'run-new', epoch: 2, cursor: 0 }
      submitted.push({ payload, run })
      return run
    },
    streamRunEvents: async (run, options) => {
      streamed.push(run.run_id)
      if (run.run_id === 'run-old') {
        options.onEvent(envelope('run-old', 1, 1, 'waiting_user', {
          tool_call_id: 'ask-1',
          questions: [{ id: 'format', question: 'Format?', kind: 'text' }],
        }))
      }
      else {
        options.onEvent(envelope('run-new', 2, 1, 'done', { summary: 'complete' }))
      }
      return { status: 200, lastEventId: '1' }
    },
  })

  await controller.submitMessage('build')
  await controller.submitClarification('ask-1', [
    { question_id: 'format', kind: 'text', text: 'markdown' },
  ])

  assert.deepEqual(submitted.map(item => item.payload.message), ['build', 'markdown'])
  assert.deepEqual(streamed, ['run-old', 'run-new'])
  assert.equal(messages.value.find(message => message.kind === 'clarification').resolved, true)
})

for (const approved of [true, false]) {
  test(`live trial ${approved ? 'approval' : 'decline'} preserves explicit consent at Turn submission`, async () => {
    const submitted = []
    const requestId = 'b'.repeat(32)
    const { controller } = harness(async () => {}, {
      submitTurn: async (payload) => {
        submitted.push(payload)
        return { conversation_id: 'conversation-1', run_id: `run-${submitted.length}`, epoch: submitted.length, cursor: 0 }
      },
      streamRunEvents: async (run, options) => {
        options.onEvent(envelope(run.run_id, run.epoch, 1, run.epoch === 1 ? 'waiting_user' : 'done', run.epoch === 1 ? {
          tool_call_id: 'ask-live',
          questions: [{ id: 'live_run_consent', kind: 'live_acceptance', execution_request: { request_id: requestId } }],
        } : { summary: 'complete' }))
        return { status: 200, lastEventId: '1' }
      },
    })
    await controller.submitMessage('build')
    await controller.submitClarification('ask-live', [{ question_id: 'live_run_consent', approved, text: approved ? 'Approve' : 'Simulate' }])
    assert.equal(submitted[1].live_acceptance_request_id, approved ? requestId : undefined)
    await controller.submitMessage('continue')
    assert.equal('live_acceptance_request_id' in submitted[2], false)
  })
}

test('candidate refresh coalesces bursts, remains single-flight, and drops older responses', async () => {
  const timers = manualTimers()
  const firstCandidate = deferred()
  const secondCandidate = deferred()
  const candidateCalls = []
  const accepted = []
  let onEvent
  const streamDone = deferred()
  const { controller } = harness(async () => {}, {
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
    loadCandidate: async (_conversationId, requestedRevision) => {
      candidateCalls.push(requestedRevision)
      return candidateCalls.length === 1 ? firstCandidate.promise : secondCandidate.promise
    },
    onCandidate: candidate => accepted.push(candidate.revision),
    streamRunEvents: async (_run, options) => {
      onEvent = options.onEvent
      await streamDone.promise
      return { status: 204, lastEventId: null }
    },
  })
  const active = controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, cursor: 0 })
  await Promise.resolve()

  onEvent(envelope('run-1', 1, 1, 'candidate.updated', { revision: 2 }))
  onEvent(envelope('run-1', 1, 2, 'candidate.updated', { revision: 3 }))
  assert.equal(timers.active().length, 1)
  assert.equal(timers.active()[0].delay, 250)
  const firstRefresh = timers.runNext()
  await Promise.resolve()
  assert.deepEqual(candidateCalls, [3])

  onEvent(envelope('run-1', 1, 3, 'candidate.updated', { revision: 4 }))
  await timers.runNext()
  firstCandidate.resolve({ revision: 3, graph: { nodes: [{ id: 'stale' }], edges: [] } })
  await firstRefresh
  await Promise.resolve()
  assert.deepEqual(accepted, [])
  assert.deepEqual(candidateCalls, [3, 4])

  secondCandidate.resolve({ revision: 4, graph: { nodes: [{ id: 'fresh' }], edges: [] } })
  await Promise.resolve()
  await Promise.resolve()
  assert.deepEqual(accepted, [4])

  controller.detachActiveTurn()
  streamDone.resolve()
  await active
})

test('candidate response from a superseded conversation generation cannot overwrite current state', async () => {
  const timers = manualTimers()
  const candidate = deferred()
  const accepted = []
  let onEvent
  const streamDone = deferred()
  const { controller, conversationId } = harness(async () => {}, {
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
    loadCandidate: async () => candidate.promise,
    onCandidate: value => accepted.push(value),
    selectConversation: async (id) => {
      conversationId.value = id
      return true
    },
    streamRunEvents: async (_run, options) => {
      onEvent = options.onEvent
      await streamDone.promise
      return { status: 204, lastEventId: null }
    },
  })
  const active = controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, cursor: 0 })
  await Promise.resolve()
  onEvent(envelope('run-1', 1, 1, 'candidate.updated', { revision: 5 }))
  const refresh = timers.runNext()
  await Promise.resolve()

  await controller.selectConversation('conversation-2')
  candidate.resolve({ revision: 5, graph: { nodes: [{ id: 'stale' }], edges: [] } })
  await refresh

  assert.deepEqual(accepted, [])
  streamDone.resolve()
  await active
})

test('a stale in-flight candidate request cannot starve the next run refresh', async () => {
  const timers = manualTimers()
  const staleCandidate = deferred()
  const freshCandidate = deferred()
  const candidateCalls = []
  const accepted = []
  const streams = new Map()
  const events = new Map()
  const { controller } = harness(async () => {}, {
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
    loadCandidate: async (_conversationId, revision) => {
      candidateCalls.push(revision)
      return candidateCalls.length === 1 ? staleCandidate.promise : freshCandidate.promise
    },
    onCandidate: value => accepted.push(value.revision),
    streamRunEvents: async (run, options) => {
      events.set(run.run_id, options.onEvent)
      const pending = deferred()
      streams.set(run.run_id, pending)
      await pending.promise
      return { status: 204, lastEventId: null }
    },
  })

  const oldRun = controller.resumeActiveTurn({ run_id: 'run-old', epoch: 1, cursor: 0 })
  await Promise.resolve()
  events.get('run-old')(envelope('run-old', 1, 1, 'candidate.updated', { revision: 5 }))
  const oldRefresh = timers.runNext()
  await Promise.resolve()

  const newRun = controller.resumeActiveTurn({ run_id: 'run-new', epoch: 2, cursor: 0 })
  await Promise.resolve()
  events.get('run-new')(envelope('run-new', 2, 1, 'candidate.updated', { revision: 6 }))
  await timers.runNext()
  staleCandidate.resolve({ revision: 5, graph: { nodes: [{ id: 'stale' }], edges: [] } })
  await oldRefresh
  await Promise.resolve()

  assert.deepEqual(candidateCalls, [5, 6])
  freshCandidate.resolve({ revision: 6, graph: { nodes: [{ id: 'fresh' }], edges: [] } })
  await Promise.resolve()
  await Promise.resolve()
  assert.deepEqual(accepted, [6])

  controller.detachActiveTurn()
  streams.get('run-old').resolve()
  streams.get('run-new').resolve()
  await Promise.all([oldRun, newRun])
})

test('an old run handoff does not consume the new run candidate follow-up budget', async () => {
  const timers = manualTimers()
  const oldCandidate = deferred()
  const newStaleCandidate = deferred()
  const newFreshCandidate = deferred()
  const candidateCalls = []
  const accepted = []
  const candidateAccepted = deferred()
  const errors = []
  const streams = new Map()
  const events = new Map()
  const candidates = [oldCandidate, newStaleCandidate, newFreshCandidate]
  const { controller } = harness(async () => {}, {
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
    loadCandidate: async (_conversationId, revision) => {
      candidateCalls.push(revision)
      return candidates[candidateCalls.length - 1].promise
    },
    onCandidate: (candidate) => {
      accepted.push(candidate.revision)
      candidateAccepted.resolve()
    },
    onErrors: nextErrors => errors.push(nextErrors),
    streamRunEvents: async (run, options) => {
      events.set(run.run_id, options.onEvent)
      const pending = deferred()
      streams.set(run.run_id, pending)
      await pending.promise
      return { status: 204, lastEventId: null }
    },
  })

  const oldRun = controller.resumeActiveTurn({ run_id: 'run-old', epoch: 1, cursor: 0 })
  await Promise.resolve()
  events.get('run-old')(envelope('run-old', 1, 1, 'candidate.updated', { revision: 5 }))
  const oldRefresh = timers.runNext()
  await Promise.resolve()

  const newRun = controller.resumeActiveTurn({ run_id: 'run-new', epoch: 2, cursor: 0 })
  await Promise.resolve()
  events.get('run-new')(envelope('run-new', 2, 1, 'candidate.updated', { revision: 6 }))
  await timers.runNext()

  oldCandidate.resolve({ revision: 5, graph: { nodes: [{ id: 'old' }], edges: [] } })
  await oldRefresh
  await Promise.resolve()
  assert.deepEqual(candidateCalls, [5, 6])

  newStaleCandidate.resolve({ revision: 5, graph: { nodes: [{ id: 'new-stale' }], edges: [] } })
  await Promise.resolve()
  await Promise.resolve()
  assert.deepEqual(candidateCalls, [5, 6, 6])

  newFreshCandidate.resolve({ revision: 6, graph: { nodes: [{ id: 'new-fresh' }], edges: [] } })
  await candidateAccepted.promise
  assert.deepEqual(accepted, [6])
  assert.deepEqual(errors, [])

  controller.detachActiveTurn()
  streams.get('run-old').resolve()
  streams.get('run-new').resolve()
  await Promise.all([oldRun, newRun])
})

test('terminal reconciliation never overlaps an in-flight candidate.updated refresh', async () => {
  const timers = manualTimers()
  const candidateGate = deferred()
  const streamGate = deferred()
  let onEvent
  let inFlight = 0
  let maximumInFlight = 0
  let candidateCalls = 0
  let runSummaryCalls = 0
  const { controller } = harness(async () => {}, {
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
    loadCandidate: async () => {
      candidateCalls += 1
      inFlight += 1
      maximumInFlight = Math.max(maximumInFlight, inFlight)
      await candidateGate.promise
      inFlight -= 1
      return { revision: 2, active_run: null, latest_run: { run_id: 'run-1', epoch: 1, status: 'done' } }
    },
    loadRunSummaries: async () => {
      runSummaryCalls += 1
      return { items: [{ run_id: 'run-1', epoch: 1, status: 'done' }] }
    },
    streamRunEvents: async (_run, options) => {
      onEvent = options.onEvent
      await streamGate.promise
      return { status: 200, lastEventId: '2' }
    },
  })
  const active = controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, cursor: 0 })
  await Promise.resolve()

  onEvent(envelope('run-1', 1, 1, 'candidate.updated', { revision: 2 }))
  const scheduledRefresh = timers.runNext()
  await Promise.resolve()
  onEvent(envelope('run-1', 1, 2, 'done', { summary: 'complete' }))
  streamGate.resolve()
  await Promise.resolve()
  await Promise.resolve()

  assert.equal(maximumInFlight, 1)
  candidateGate.resolve()
  await scheduledRefresh
  await active
  assert.equal(maximumInFlight, 1)
  assert.equal(candidateCalls, 2)
  assert.equal(runSummaryCalls, 1)
})

test('terminal refresh consumes a pending candidate timer without issuing a later extra request', async () => {
  const timers = manualTimers()
  let candidateCalls = 0
  const { controller } = harness(async () => {}, {
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
    loadCandidate: async () => {
      candidateCalls += 1
      return { revision: 2, active_run: null, latest_run: { run_id: 'run-1', epoch: 1, status: 'done' } }
    },
    streamRunEvents: async (_run, options) => {
      options.onEvent(envelope('run-1', 1, 1, 'candidate.updated', { revision: 2 }))
      options.onEvent(envelope('run-1', 1, 2, 'done', { summary: 'complete' }))
      return { status: 200, lastEventId: '2' }
    },
  })

  await controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, cursor: 0 })

  assert.equal(candidateCalls, 1)
  assert.equal(timers.active().length, 0)
})

test('authoritative 204 refreshes terminal facts and clears stale running state without reconnecting', async () => {
  let streamCalls = 0
  let candidateCalls = 0
  let runCalls = 0
  let terminalCalls = 0
  const reconciles = []
  const { controller, state } = harness(async () => {}, {
    loadCandidate: async () => {
      candidateCalls += 1
      return {
        revision: 2,
        active_run: null,
        latest_run: { run_id: 'run-1', epoch: 1, status: 'done' },
      }
    },
    loadRunSummaries: async () => {
      runCalls += 1
      return { items: [{ run_id: 'run-1', epoch: 1, status: 'done' }] }
    },
    reconcileRunCoordinates: snapshot => reconciles.push(snapshot),
    onRunTerminal: () => { terminalCalls += 1 },
    streamRunEvents: async () => {
      streamCalls += 1
      return { status: 204, lastEventId: '5' }
    },
  })
  state.value = reduceAssist(state.value, { type: 'SEND' })

  await controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, cursor: 5 })

  assert.equal(streamCalls, 1)
  assert.equal(candidateCalls, 1)
  assert.equal(runCalls, 1)
  assert.equal(terminalCalls, 1)
  assert.equal(state.value.phase, 'idle')
  assert.deepEqual(reconciles.map(item => ({ active_run: item.active_run, latest_run: item.latest_run })), [{
    active_run: null,
    latest_run: { run_id: 'run-1', epoch: 1, status: 'done' },
  }])
})

test('mount rejects a candidate snapshot older than the highest timeline revision', async () => {
  const requestedRevisions = []
  const accepted = []
  const reconciles = []
  const { controller } = harness(async () => {}, {
    loadConversations: async () => ({ items: [{ id: 'conversation-1' }] }),
    selectConversation: async () => true,
    loadTimeline: async () => ({
      items: [
        envelope('run-1', 1, 0, 'user.message', { text: 'restore' }),
        envelope('run-1', 1, 1, 'candidate.updated', { revision: 5 }),
      ],
      has_more: false,
      cursor: { epoch: 1, sequence: 1 },
    }),
    loadCandidate: async (_conversationId, requestedRevision) => {
      requestedRevisions.push(requestedRevision)
      if (requestedRevision === 5) {
        return {
          revision: 5,
          active_run: { run_id: 'run-1', epoch: 1, status: 'running' },
          latest_run: { run_id: 'run-1', epoch: 1, status: 'running' },
        }
      }
      return {
        revision: 4,
        active_run: null,
        latest_run: { run_id: 'stale-run', epoch: 99, status: 'done' },
      }
    },
    onCandidate: candidate => accepted.push(candidate.revision),
    reconcileRunCoordinates: snapshot => reconciles.push(snapshot),
    streamRunEvents: async () => ({ status: 204, lastEventId: '1' }),
  })

  await controller.mountRecoverableSession()

  assert.deepEqual(requestedRevisions.slice(0, 2), [0, 5])
  assert.equal(accepted[0], 5)
  assert.equal(reconciles.some(item => item.latest_run?.run_id === 'stale-run'), false)
  assert.equal(reconciles[0].active_run.run_id, 'run-1')
})

test('an older request accepts a returned candidate that already covers the newest desired revision', async () => {
  const timers = manualTimers()
  const firstCandidate = deferred()
  const candidateCalls = []
  const accepted = []
  const errors = []
  let onEvent
  const streamDone = deferred()
  const { controller } = harness(async () => {}, {
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
    loadCandidate: async (_conversationId, requestedRevision) => {
      candidateCalls.push(requestedRevision)
      if (candidateCalls.length === 1)
        return firstCandidate.promise
      throw new Error('unnecessary follow-up failed')
    },
    onCandidate: candidate => accepted.push(candidate.revision),
    onErrors: nextErrors => errors.push(nextErrors),
    streamRunEvents: async (_run, options) => {
      onEvent = options.onEvent
      await streamDone.promise
      return { status: 204, lastEventId: null }
    },
  })
  const active = controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, cursor: 0 })
  await Promise.resolve()

  onEvent(envelope('run-1', 1, 1, 'candidate.updated', { revision: 3 }))
  const refresh = timers.runNext()
  await Promise.resolve()
  onEvent(envelope('run-1', 1, 2, 'candidate.updated', { revision: 4 }))
  await timers.runNext()
  firstCandidate.resolve({ revision: 4, graph: { nodes: [{ id: 'fresh' }], edges: [] } })
  await refresh
  await Promise.resolve()
  await Promise.resolve()

  assert.deepEqual(candidateCalls, [3])
  assert.deepEqual(accepted, [4])
  assert.deepEqual(errors, [])

  controller.detachActiveTurn()
  streamDone.resolve()
  await active
})

test('mount adopts an authoritative active run so stop remains available during recovery', async () => {
  let coordinates = null
  const subscribed = deferred()
  const { controller, state, abortCalls } = harness(async () => {}, {
    loadConversations: async () => ({ items: [{ id: 'conversation-1' }] }),
    selectConversation: async () => true,
    loadTimeline: async () => ({ items: [], has_more: false }),
    loadCandidate: async () => ({
      revision: 0,
      active_run: { run_id: 'run-1', epoch: 1, status: 'running' },
      latest_run: { run_id: 'run-1', epoch: 1, status: 'running' },
    }),
    getRunCoordinates: () => coordinates,
    reconcileRunCoordinates: facts => {
      const run = facts.active_run || facts.latest_run
      coordinates = run ? {
        conversation_id: facts.conversation_id,
        run_id: run.run_id,
        epoch: run.epoch,
        cursor: 0,
      } : null
    },
    streamRunEvents: async (_run, { signal }) => {
      subscribed.resolve()
      await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }))
      return { status: 200, lastEventId: null }
    },
  })

  const mount = controller.mountRecoverableSession()
  await subscribed.promise
  assert.equal(state.value.phase, 'running')

  await controller.stopActiveTurn()
  await mount
  assert.deepEqual(abortCalls, [{
    conversation_id: 'conversation-1',
    run_id: 'run-1',
    epoch: 1,
  }])
  assert.equal(state.value.phase, 'idle')
  assert.equal(state.value.terminationReason, 'user_abort')
})

test('direct resume adopts the recovered run before waiting for SSE', async () => {
  const subscribed = deferred()
  const { controller, state } = harness(async () => {}, {
    streamRunEvents: async (_run, { signal }) => {
      subscribed.resolve()
      await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }))
      return { status: 200, lastEventId: null }
    },
  })

  const active = controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, status: 'queued', cursor: 0 })
  await subscribed.promise
  assert.equal(state.value.phase, 'running')

  controller.detachActiveTurn()
  await active
})

test('reconnect backoff is bounded and resets after stream progress', async () => {
  const delays = []
  let calls = 0
  const { controller } = harness(async () => {}, {
    waitForReconnect: async (delay) => {
      delays.push(delay)
      return true
    },
    streamRunEvents: async (_run, options) => {
      calls += 1
      if (calls <= 6)
        throw new TypeError('network connection lost')
      if (calls === 7) {
        options.onEvent(envelope('run-1', 1, 1, 'status', { status: 'running' }))
        return { status: 200, lastEventId: '1' }
      }
      options.onEvent(envelope('run-1', 1, 2, 'done', { summary: 'complete' }))
      return { status: 200, lastEventId: '2' }
    },
  })

  await controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, cursor: 0 })

  assert.deepEqual(delays, [250, 500, 1000, 2000, 4000, 4000, 250])
  assert.equal(calls, 8)
})

test('detach immediately cancels an empty-200 reconnect backoff', async () => {
  const reconnects = manualReconnectWaits()
  let calls = 0
  const { controller } = harness(async () => {}, {
    waitForReconnect: reconnects.wait,
    streamRunEvents: async () => {
      calls += 1
      return { status: 200, lastEventId: null }
    },
  })

  const active = controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, cursor: 0 })
  while (!reconnects.waits.length && calls < 2)
    await Promise.resolve()

  controller.detachActiveTurn()
  await active
  assert.equal(reconnects.waits.length, 1)
  assert.equal(reconnects.waits[0].delay, 250)
  assert.equal(reconnects.waits[0].signal.aborted, true)
  assert.equal(calls, 1)
})

test('mount stops after bounded stale candidate attempts without accepting old facts', async () => {
  let candidateCalls = 0
  const accepted = []
  const reconciles = []
  const errors = []
  const { controller } = harness(async () => {}, {
    loadConversations: async () => ({ items: [{ id: 'conversation-1' }] }),
    selectConversation: async () => true,
    loadTimeline: async () => ({
      items: [envelope('run-1', 1, 1, 'candidate.updated', { revision: 5 })],
      has_more: false,
    }),
    loadCandidate: async () => {
      candidateCalls += 1
      if (candidateCalls > 2)
        throw new Error('unexpected unbounded candidate retry')
      return { revision: 4, active_run: null, latest_run: null }
    },
    onCandidate: candidate => accepted.push(candidate.revision),
    reconcileRunCoordinates: snapshot => reconciles.push(snapshot),
    onErrors: nextErrors => errors.push(nextErrors),
  })

  const mounted = await controller.mountRecoverableSession()

  assert.equal(mounted, false)
  assert.equal(candidateCalls, 2)
  assert.deepEqual(accepted, [])
  assert.deepEqual(reconciles, [])
  assert.equal(errors.length, 1)
})

test('live candidate refresh stops after one bounded follow-up when snapshots stay stale', async () => {
  const timers = manualTimers()
  const streamDone = deferred()
  let onEvent
  let candidateCalls = 0
  const accepted = []
  const errors = []
  const { controller } = harness(async () => {}, {
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
    loadCandidate: async () => {
      candidateCalls += 1
      if (candidateCalls > 2)
        throw new Error('unexpected unbounded candidate retry')
      return { revision: 4, active_run: null, latest_run: null }
    },
    onCandidate: candidate => accepted.push(candidate.revision),
    onErrors: nextErrors => errors.push(nextErrors),
    streamRunEvents: async (_run, options) => {
      onEvent = options.onEvent
      await streamDone.promise
      return { status: 204, lastEventId: null }
    },
  })
  const active = controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, cursor: 0 })
  await Promise.resolve()
  onEvent(envelope('run-1', 1, 1, 'candidate.updated', { revision: 5 }))

  await timers.runNext()
  await Promise.resolve()
  await Promise.resolve()

  assert.equal(candidateCalls, 2)
  assert.deepEqual(accepted, [])
  assert.equal(errors.length, 1)

  controller.detachActiveTurn()
  streamDone.resolve()
  await active
})

test('terminal reconciliation settles after bounded stale candidate attempts', async () => {
  let candidateCalls = 0
  let runCalls = 0
  const errors = []
  const { controller, state } = harness(async () => {}, {
    loadCandidate: async () => {
      candidateCalls += 1
      if (candidateCalls > 2)
        throw new Error('unexpected unbounded candidate retry')
      return { revision: 4, active_run: null, latest_run: null }
    },
    loadRunSummaries: async () => {
      runCalls += 1
      return { items: [{ run_id: 'run-1', epoch: 1, status: 'done' }] }
    },
    onErrors: nextErrors => errors.push(nextErrors),
    streamRunEvents: async (_run, options) => {
      options.onEvent(envelope('run-1', 1, 1, 'candidate.updated', { revision: 5 }))
      return { status: 204, lastEventId: '1' }
    },
  })

  await controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, cursor: 0 })

  assert.equal(candidateCalls, 2)
  assert.equal(runCalls, 1)
  assert.equal(errors.length, 1)
  assert.equal(state.value.phase, 'idle')
})

test('history selection repeats the full authoritative recovery path and restores Stop state', async () => {
  const calls = []
  let selectedId = 'conversation-1'
  const streamGate = deferred()
  const { controller, messages, state, conversationId } = harness(async () => {}, {
    selectConversation: async (id) => {
      selectedId = String(id)
      conversationId.value = selectedId
      calls.push(`select:${selectedId}`)
      return true
    },
    loadTimeline: async (id, params) => {
      calls.push(`timeline:${id}:${params.after_epoch}:${params.after_sequence}`)
      return {
        items: [envelope('run-2', 2, 0, 'user.message', { text: 'restored history' })],
        has_more: false,
      }
    },
    onTimelineRecovered: ({ messages: recoveredMessages }) => {
      calls.push(`language:${recoveredMessages.at(-1)?.text}`)
    },
    loadCandidate: async (id) => {
      calls.push(`candidate:${id}`)
      return {
        revision: 0,
        active_run: { run_id: 'run-2', epoch: 2, status: 'running' },
        latest_run: { run_id: 'run-2', epoch: 2, status: 'running' },
      }
    },
    reconcileRunCoordinates: (facts) => { calls.push(`reconcile:${facts.conversation_id}`) },
    streamRunEvents: async (run, options) => {
      calls.push(`sse:${run.run_id}:${options.after}`)
      await streamGate.promise
      return { status: 200, lastEventId: null }
    },
  })

  const recovery = controller.selectConversation('conversation-2')
  for (let index = 0; index < 5; index += 1)
    await Promise.resolve()

  assert.equal(selectedId, 'conversation-2')
  assert.equal(messages.value.some(message => message.text === 'restored history'), true)
  assert.equal(state.value.phase, 'running')
  assert.deepEqual(calls.slice(0, 5), [
    'select:conversation-2',
    'candidate:conversation-2',
    'timeline:conversation-2:0:0',
    'language:restored history',
    'reconcile:conversation-2',
  ])
  assert.equal(calls[5], 'sse:run-2:0')

  controller.detachActiveTurn()
  streamGate.resolve()
  await recovery
})

test('selecting the already-current conversation still replays full recovery', async () => {
  const calls = []
  const { controller } = harness(async () => {}, {
    selectConversation: async (id) => { calls.push(`select:${id}`); return true },
    loadTimeline: async (id, params) => {
      calls.push(`timeline:${id}:${params.after_epoch}:${params.after_sequence}`)
      return { items: [], has_more: false }
    },
    loadCandidate: async (id) => {
      calls.push(`candidate:${id}`)
      return { revision: 0, active_run: null, latest_run: { run_id: 'run-1', epoch: 1, status: 'done' } }
    },
    reconcileRunCoordinates: facts => calls.push(`reconcile:${facts.conversation_id}`),
  })

  await controller.selectConversation('conversation-1')
  await controller.selectConversation('conversation-1')

  assert.deepEqual(calls, [
    'select:conversation-1',
    'candidate:conversation-1',
    'timeline:conversation-1:0:0',
    'reconcile:conversation-1',
    'select:conversation-1',
    'candidate:conversation-1',
    'timeline:conversation-1:0:0',
    'reconcile:conversation-1',
  ])
})

test('a late duplicate history recovery cannot overwrite the newest selection', async () => {
  const firstTimeline = deferred()
  const calls = []
  const { controller, messages, conversationId } = harness(async () => {}, {
    selectConversation: async (id) => {
      conversationId.value = String(id)
      calls.push(`select:${id}`)
      return true
    },
    loadTimeline: async (id) => {
      calls.push(`timeline:${id}`)
      if (id === 'conversation-2')
        return firstTimeline.promise
      return {
        items: [envelope('run-3', 3, 0, 'user.message', { text: 'newest selection' })],
        has_more: false,
      }
    },
    loadCandidate: async id => ({
      revision: 0,
      active_run: null,
      latest_run: { run_id: `run-${id.at(-1)}`, epoch: Number(id.at(-1)), status: 'done' },
    }),
  })

  const first = controller.selectConversation('conversation-2')
  while (!calls.includes('timeline:conversation-2'))
    await Promise.resolve()
  const second = controller.selectConversation('conversation-3')
  await second
  firstTimeline.resolve({
    items: [envelope('run-2', 2, 0, 'user.message', { text: 'stale selection' })],
    has_more: false,
  })
  await first

  assert.equal(conversationId.value, 'conversation-3')
  assert.equal(messages.value.some(message => message.text === 'newest selection'), true)
  assert.equal(messages.value.some(message => message.text === 'stale selection'), false)
})

test('running preflight failure retains the authoritative stream and accepts its terminal event', async () => {
  const streamGate = deferred()
  const subscribed = deferred()
  let oldSignal
  let oldOnEvent
  let syncCalls = 0
  const { controller, state, messages } = harness(async () => {}, {
    syncDraftIfDirty: async () => {
      syncCalls += 1
      if (syncCalls === 2)
        throw new Error('sync failed')
    },
    streamRunEvents: async (_run, options) => {
      oldSignal = options.signal
      oldOnEvent = options.onEvent
      subscribed.resolve()
      await streamGate.promise
      return { status: 200, lastEventId: null }
    },
  })

  const first = controller.submitMessage('first')
  await subscribed.promise
  const second = await controller.submitMessage('second')

  assert.equal(second?.accepted, false)
  assert.equal(oldSignal.aborted, false)
  assert.equal(state.value.phase, 'running')
  oldOnEvent(envelope('legacy-test-run-1', 1, 1, 'done', { summary: 'old completed' }))
  streamGate.resolve()
  await first
  assert.equal(state.value.phase, 'idle')
  assert.equal(messages.value.some(message => message.summary === 'old completed'), true)
})

test('idle Turn creation failure leaves the session and draft acknowledgement untouched', async () => {
  let accepted = false
  const { controller, state, messages } = harness(async () => {}, {
    submitTurn: async () => { throw new Error('turn failed') },
  })

  const result = await controller.submitMessage('keep me', {
    onAccepted: () => { accepted = true },
  })

  assert.equal(result.accepted, false)
  assert.equal(accepted, false)
  assert.equal(state.value.phase, 'idle')
  assert.equal(messages.value.some(message => message.text === 'keep me'), false)
})

test('composer acknowledgement fires only after the Turn receives a 202 response', async () => {
  const streamGate = deferred()
  const subscribed = deferred()
  const calls = []
  const { controller } = harness(async () => {}, {
    submitTurn: async () => {
      calls.push('turn-accepted')
      return { conversation_id: 'conversation-1', run_id: 'run-1', epoch: 1, cursor: 0 }
    },
    streamRunEvents: async () => {
      calls.push('stream-started')
      subscribed.resolve()
      await streamGate.promise
      return { status: 204, lastEventId: null }
    },
  })

  const turn = controller.submitMessage('clear after acceptance', {
    onAccepted: () => { calls.push('composer-cleared') },
  })
  await subscribed.promise

  assert.deepEqual(calls, ['turn-accepted', 'composer-cleared', 'stream-started'])
  streamGate.resolve()
  await turn
})

test('running Turn creation failure does not fence or detach the old Run', async () => {
  const oldGate = deferred()
  const subscribed = deferred()
  let oldSignal
  let oldOnEvent
  let turnCount = 0
  const { controller, state, messages } = harness(async () => {}, {
    submitTurn: async () => {
      turnCount += 1
      if (turnCount === 2)
        throw new Error('turn failed')
      return { conversation_id: 'conversation-1', run_id: 'run-1', epoch: 1, cursor: 0 }
    },
    streamRunEvents: async (_run, options) => {
      oldSignal = options.signal
      oldOnEvent = options.onEvent
      subscribed.resolve()
      await oldGate.promise
      return { status: 200, lastEventId: null }
    },
  })
  const oldRun = controller.submitMessage('first')
  await subscribed.promise

  const result = await controller.submitMessage('second')
  assert.equal(result.accepted, false)
  assert.equal(oldSignal.aborted, false)
  assert.equal(state.value.phase, 'running')

  oldOnEvent(envelope('run-1', 1, 1, 'done', { summary: 'authoritative done' }))
  oldGate.resolve()
  await oldRun
  assert.equal(messages.value.some(message => message.summary === 'authoritative done'), true)
})

test('clarification returns to pending when Turn creation fails before acceptance', async () => {
  const { controller, messages, state } = harness(async () => {}, {
    submitTurn: async () => { throw new Error('turn failed') },
  })
  messages.value = [{
    role: 'assistant',
    kind: 'clarification',
    clarification: {
      clarification_id: 'ask-1',
      questions: [{ id: 'q', question: 'Format?', kind: 'text' }],
    },
    status: 'pending',
    resolved: false,
  }]
  state.value = { ...state.value, phase: 'waiting_user', waitingUser: { tool_call_id: 'ask-1' } }

  const result = await controller.submitClarification('ask-1', [{ question_id: 'q', text: 'markdown' }])
  const card = messages.value.find(message => message.kind === 'clarification')

  assert.equal(result?.accepted, false)
  assert.equal(card.status, 'pending')
  assert.equal(card.resolved, false)
  assert.equal(state.value.phase, 'waiting_user')
})

test('clarification returns to pending when draft synchronization fails before acceptance', async () => {
  const { controller, messages, state } = harness(async () => {}, {
    syncDraftIfDirty: async () => { throw new Error('sync failed') },
  })
  messages.value = [{
    role: 'assistant',
    kind: 'clarification',
    clarification: {
      clarification_id: 'ask-1',
      questions: [{ id: 'q', question: 'Format?', kind: 'text' }],
    },
    status: 'pending',
    resolved: false,
  }]
  state.value = { ...state.value, phase: 'waiting_user', waitingUser: { tool_call_id: 'ask-1' } }

  const result = await controller.submitClarification('ask-1', [{ question_id: 'q', text: 'markdown' }])
  const card = messages.value.find(message => message.kind === 'clarification')

  assert.equal(result?.accepted, false)
  assert.equal(card.status, 'pending')
  assert.equal(card.resolved, false)
  assert.equal(state.value.phase, 'waiting_user')
})

test('Stop network failure preserves the active stream and remains retryable', async () => {
  const streamGate = deferred()
  const subscribed = deferred()
  let signal
  let abortAttempts = 0
  const { controller, state } = harness(async () => {}, {
    getRunCoordinates: () => ({ conversation_id: 'conversation-1', run_id: 'run-1', epoch: 1, cursor: 0 }),
    abortChat: async () => {
      abortAttempts += 1
      throw new TypeError('network failed')
    },
    streamRunEvents: async (_run, options) => {
      signal = options.signal
      subscribed.resolve()
      await streamGate.promise
      return { status: 200, lastEventId: null }
    },
  })
  const active = controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, status: 'running', cursor: 0 })
  await subscribed.promise

  assert.equal(await controller.stopActiveTurn(), false)
  assert.equal(await controller.stopActiveTurn(), false)
  assert.equal(signal.aborted, false)
  assert.equal(state.value.phase, 'running')
  assert.equal(abortAttempts, 2)

  controller.detachActiveTurn()
  streamGate.resolve()
  await active
})

test('Stop 409 replaces the stale stream with the returned authoritative active Run', async () => {
  const streams = new Map()
  const signals = new Map()
  const conflict = Object.assign(new Error('conflict'), {
    response: {
      status: 409,
      data: {
        active_run: { run_id: 'run-2', epoch: 2, status: 'running', cursor: 0 },
        latest_run: { run_id: 'run-2', epoch: 2, status: 'running', cursor: 0 },
      },
    },
  })
  const { controller, state } = harness(async () => {}, {
    getRunCoordinates: () => ({ conversation_id: 'conversation-1', run_id: 'run-1', epoch: 1, cursor: 0 }),
    abortChat: async () => { throw conflict },
    streamRunEvents: async (run, options) => {
      signals.set(run.run_id, options.signal)
      const gate = deferred()
      streams.set(run.run_id, gate)
      await gate.promise
      return { status: 200, lastEventId: null }
    },
  })
  const old = controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, status: 'running', cursor: 0 })
  while (!streams.has('run-1'))
    await Promise.resolve()

  assert.equal(await controller.stopActiveTurn(), false)
  for (let index = 0; index < 5; index += 1)
    await Promise.resolve()
  assert.equal(streams.has('run-2'), true)
  assert.equal(signals.get('run-1').aborted, true)
  assert.equal(signals.get('run-2').aborted, false)
  assert.equal(state.value.phase, 'running')

  controller.detachActiveTurn()
  streams.get('run-1').resolve()
  streams.get('run-2').resolve()
  await old
})

test('Stop 409 refreshes authoritative terminal facts before settling the returned Run', async () => {
  const subscribed = deferred()
  let oldSignal
  const calls = []
  const candidateSnapshots = []
  const conflict = Object.assign(new Error('conflict'), {
    response: {
      status: 409,
      data: {
        active_run: null,
        latest_run: { run_id: 'run-1', epoch: 1, status: 'done' },
        runs: [{ run_id: 'run-1', epoch: 1, status: 'done' }],
      },
    },
  })
  const { controller, state } = harness(async () => {}, {
    getRunCoordinates: () => ({ conversation_id: 'conversation-1', run_id: 'run-1', epoch: 1, cursor: 0 }),
    abortChat: async () => { throw conflict },
    streamRunEvents: async (_run, { signal }) => {
      oldSignal = signal
      subscribed.resolve()
      await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }))
      return { status: 200, lastEventId: null }
    },
    loadCandidate: async () => {
      calls.push('candidate')
      return {
        revision: 3,
        graph: { nodes: [{ id: 'end' }], edges: [] },
        active_run: null,
        latest_run: { run_id: 'run-1', epoch: 1, status: 'done' },
        completion_evidence: { assertion: 'workflow_structure_reaches_terminal' },
      }
    },
    loadRunSummaries: async () => {
      calls.push('runs')
      return { items: [{ run_id: 'run-1', epoch: 1, status: 'done' }] }
    },
    onCandidate: snapshot => candidateSnapshots.push(snapshot),
  })
  const active = controller.resumeActiveTurn({ run_id: 'run-1', epoch: 1, status: 'running', cursor: 0 })
  await subscribed.promise

  assert.equal(await controller.stopActiveTurn(), false)
  assert.equal(oldSignal.aborted, true)
  assert.deepEqual(calls, ['candidate', 'runs'])
  assert.equal(candidateSnapshots.at(-1)?.revision, 3)
  assert.equal(state.value.phase, 'idle')
  assert.equal(state.value.terminationReason, null)
  await active
})

test('history recovery fences a Turn whose draft synchronization belongs to the previous conversation', async () => {
  const syncGate = deferred()
  const syncStarted = deferred()
  const prepareCalls = []
  const turnCalls = []
  let editorText = 'conversation one draft'
  let accepted = false
  const { controller, conversationId } = harness(async () => {}, {
    syncDraftIfDirty: async () => {
      syncStarted.resolve()
      await syncGate.promise
    },
    prepareInstruction: async (text) => {
      prepareCalls.push({ conversation_id: conversationId.value, text })
      return true
    },
    submitTurn: async (payload) => {
      turnCalls.push({ conversation_id: conversationId.value, payload })
      return { conversation_id: conversationId.value, run_id: 'wrong-run', epoch: 2, cursor: 0 }
    },
    streamRunEvents: async () => ({ status: 204, lastEventId: null }),
    selectConversation: async (id) => {
      conversationId.value = String(id)
      return true
    },
    loadTimeline: async () => ({
      items: [envelope('run-2', 2, 0, 'user.message', { text: 'conversation two history' })],
      has_more: false,
    }),
    loadCandidate: async () => ({
      revision: 0,
      active_run: null,
      latest_run: { run_id: 'run-2', epoch: 2, status: 'done' },
    }),
  })

  const oldAttempt = controller.submitMessage('belongs to conversation one', {
    onAccepted: () => {
      accepted = true
      editorText = ''
    },
  })
  await syncStarted.promise
  await controller.selectConversation('conversation-2')
  editorText = 'conversation two editor'
  syncGate.resolve()
  const result = await oldAttempt

  assert.equal(result.accepted, false)
  assert.deepEqual(prepareCalls, [])
  assert.deepEqual(turnCalls, [])
  assert.equal(accepted, false)
  assert.equal(editorText, 'conversation two editor')
  assert.equal(conversationId.value, 'conversation-2')
})

test('history recovery rejects a late 202 before adoption, acknowledgement, or subscription', async () => {
  const turnGate = deferred()
  const turnStarted = deferred()
  const adopted = []
  const streamCalls = []
  let editorText = 'conversation one draft'
  let accepted = false
  const { controller, conversationId, messages } = harness(async () => {}, {
    submitTurn: async () => {
      turnStarted.resolve()
      await turnGate.promise
      return { conversation_id: 'conversation-1', run_id: 'run-old', epoch: 1, cursor: 0 }
    },
    streamRunEvents: async (run) => {
      streamCalls.push(run)
      return { status: 204, lastEventId: null }
    },
    onRunSubmitted: run => adopted.push(run),
    selectConversation: async (id) => {
      conversationId.value = String(id)
      return true
    },
    loadTimeline: async () => ({
      items: [envelope('run-2', 2, 0, 'user.message', { text: 'conversation two history' })],
      has_more: false,
    }),
    loadCandidate: async () => ({
      revision: 0,
      active_run: null,
      latest_run: { run_id: 'run-2', epoch: 2, status: 'done' },
    }),
  })

  const oldAttempt = controller.submitMessage('old conversation turn', {
    onAccepted: () => {
      accepted = true
      editorText = ''
    },
  })
  await turnStarted.promise
  await controller.selectConversation('conversation-2')
  editorText = 'conversation two editor'
  turnGate.resolve()
  const result = await oldAttempt

  assert.equal(result.accepted, false)
  assert.deepEqual(adopted, [])
  assert.deepEqual(streamCalls, [])
  assert.equal(accepted, false)
  assert.equal(editorText, 'conversation two editor')
  assert.equal(conversationId.value, 'conversation-2')
  assert.deepEqual(messages.value.map(message => message.text).filter(Boolean), ['conversation two history'])
})

for (const action of ['new conversation', 'detach']) {
  test(`${action} invalidates a pending Turn preflight`, async () => {
    const syncGate = deferred()
    const syncStarted = deferred()
    let prepareCalls = 0
    let turnCalls = 0
    let accepted = false
    const { controller } = harness(async () => {}, {
      syncDraftIfDirty: async () => {
        syncStarted.resolve()
        await syncGate.promise
      },
      prepareInstruction: async () => {
        prepareCalls += 1
        return true
      },
      submitTurn: async () => {
        turnCalls += 1
        return { conversation_id: 'conversation-1', run_id: 'run-1', epoch: 1, cursor: 0 }
      },
      streamRunEvents: async () => ({ status: 204, lastEventId: null }),
    })

    const attempt = controller.submitMessage('pending preflight', {
      onAccepted: () => { accepted = true },
    })
    await syncStarted.promise
    if (action === 'new conversation')
      await controller.newConversation()
    else
      controller.detachActiveTurn()
    syncGate.resolve()
    const result = await attempt

    assert.equal(result.accepted, false)
    assert.equal(prepareCalls, 0)
    assert.equal(turnCalls, 0)
    assert.equal(accepted, false)
  })

  test(`${action} rejects a late 202 before mutating the session`, async () => {
    const turnGate = deferred()
    const turnStarted = deferred()
    const adopted = []
    const streamCalls = []
    let accepted = false
    const { controller, messages } = harness(async () => {}, {
      submitTurn: async () => {
        turnStarted.resolve()
        await turnGate.promise
        return { conversation_id: 'conversation-1', run_id: 'run-1', epoch: 1, cursor: 0 }
      },
      streamRunEvents: async (run) => {
        streamCalls.push(run)
        return { status: 204, lastEventId: null }
      },
      onRunSubmitted: run => adopted.push(run),
    })

    const attempt = controller.submitMessage('pending 202', {
      onAccepted: () => { accepted = true },
    })
    await turnStarted.promise
    messages.value = [{ role: 'user', text: 'new session fact' }]
    if (action === 'new conversation')
      await controller.newConversation()
    else
      controller.detachActiveTurn()
    turnGate.resolve()
    const result = await attempt

    assert.equal(result.accepted, false)
    assert.deepEqual(adopted, [])
    assert.deepEqual(streamCalls, [])
    assert.equal(accepted, false)
    assert.deepEqual(messages.value, [{ role: 'user', text: 'new session fact' }])
  })
}

test('an empty-session Turn adopts the conversation created by its own preparation', async () => {
  const turnCalls = []
  const adopted = []
  const subscriptions = []
  let accepted = 0
  let refs
  refs = harness(async () => {}, {
    syncDraftIfDirty: async () => {},
    prepareInstruction: async (_text, isCurrent) => {
      assert.equal(isCurrent(), true)
      refs.conversationId.value = 'conversation-created'
      return { accepted: true, conversationId: 'conversation-created' }
    },
    submitTurn: async (payload) => {
      turnCalls.push({ conversation_id: refs.conversationId.value, payload })
      return { conversation_id: 'conversation-created', run_id: 'run-created', epoch: 1, cursor: 0 }
    },
    streamRunEvents: async (run, { onEvent }) => {
      subscriptions.push(run)
      onEvent(envelope('run-created', 1, 1, 'done', { summary: 'created conversation done' }))
      return { status: 200, lastEventId: '1' }
    },
    onRunSubmitted: run => adopted.push(run),
  })
  refs.conversationId.value = ''

  const submission = await refs.controller.submitMessage('first instruction', {
    onAccepted: () => { accepted += 1 },
  })

  assert.equal(submission.accepted, true)
  assert.deepEqual(turnCalls, [{
    conversation_id: 'conversation-created',
    payload: { message: 'first instruction' },
  }])
  assert.equal(accepted, 1)
  assert.equal(adopted.length, 1)
  assert.equal(subscriptions.length, 1)
  assert.equal(refs.messages.value.some(message => message.text === 'first instruction'), true)
  assert.equal(refs.messages.value.some(message => message.summary === 'created conversation done'), true)
})

for (const action of ['history selection', 'new conversation', 'detach']) {
  test(`${action} invalidates preparation before it can adopt a conversation`, async () => {
    const prepareGate = deferred()
    const prepareStarted = deferred()
    let turnCalls = 0
    let accepted = 0
    let refs
    refs = harness(async () => {}, {
      prepareInstruction: async () => {
        prepareStarted.resolve()
        await prepareGate.promise
        return { accepted: true, conversationId: 'conversation-created' }
      },
      submitTurn: async () => {
        turnCalls += 1
        return { conversation_id: 'conversation-created', run_id: 'run-created', epoch: 1, cursor: 0 }
      },
      selectConversation: async (id) => {
        refs.conversationId.value = String(id)
        return true
      },
      newConversation: async () => {
        refs.conversationId.value = 'conversation-external-new'
        return true
      },
      loadTimeline: async () => ({ items: [], has_more: false }),
      loadCandidate: async () => ({ revision: 0, active_run: null, latest_run: null }),
    })
    refs.conversationId.value = ''

    const attempt = refs.controller.submitMessage('first instruction', {
      onAccepted: () => { accepted += 1 },
    })
    await prepareStarted.promise
    if (action === 'history selection')
      await refs.controller.selectConversation('conversation-external-history')
    else if (action === 'new conversation')
      await refs.controller.newConversation()
    else {
      refs.conversationId.value = 'conversation-external-detach'
      refs.controller.detachActiveTurn()
    }
    prepareGate.resolve()
    const submission = await attempt

    assert.equal(submission.accepted, false)
    assert.equal(turnCalls, 0)
    assert.equal(accepted, 0)
    assert.match(refs.conversationId.value, /^conversation-external-/)
  })
}

test('provider_error SSE keeps the exception text and does not add a duplicate status bubble', async () => {
  const captured = []
  const { controller, messages } = harness(async (_turn, { onEvent }) => {
    onEvent(envelope('legacy-test-run-1', 1, 1, 'error', {
      message: 'Connection to api.deepseek.com timed out. (connect timeout=10)',
      termination_reason: 'provider_error',
      errors: [{
        code: 'provider_error',
        detail: 'Connection to api.deepseek.com timed out. (connect timeout=10)',
      }],
    }))
    return { status: 200, lastEventId: '1' }
  }, {
    onErrors: nextErrors => captured.push(nextErrors),
  })

  await controller.submitMessage('生成循环工作流')

  assert.equal(captured.length, 1)
  assert.equal(captured[0][0].code, 'provider_error')
  assert.match(captured[0][0].detail, /deepseek/)
  assert.equal(messages.value.some(message => message.kind === 'status'), false)
})

test('retryable provider error retries the failed step without a new user turn', async () => {
  const retries = []
  let coordinates = { conversation_id: 'conversation-1', run_id: 'legacy-test-run-1', epoch: 1, cursor: 0 }
  const { controller, state, messages } = harness(async () => {}, {
    getRunCoordinates: () => coordinates,
    retryRun: async (input) => {
      retries.push(input)
      coordinates = { conversation_id: 'conversation-1', run_id: 'retry-run', epoch: 2, cursor: 0 }
      return { conversation_id: 'conversation-1', run_id: 'retry-run', epoch: 2, cursor: 0 }
    },
    streamRunEvents: async (run, { onEvent }) => {
      if (run.run_id === 'retry-run') {
        onEvent(envelope('retry-run', 2, 1, 'done', {
          summary: 'ok',
          validation: { ok: true, errors: [] },
        }))
        return { status: 200, lastEventId: '1' }
      }
      onEvent(envelope(run.run_id, run.epoch, 4, 'error', { message: 'provider failed', retryable: true }))
      return { status: 200, lastEventId: '4' }
    },
  })

  await controller.submitMessage('build a workflow')
  assert.equal(state.value.retryable, true)
  assert.equal(state.value.failedStepId, 'legacy-test-run-1:4')
  const userCount = messages.value.filter(message => message.role === 'user').length

  await controller.retryFailedStep()

  assert.equal(retries.length, 1)
  assert.deepEqual(retries[0], {
    conversation_id: 'conversation-1',
    run_id: 'legacy-test-run-1',
    epoch: 1,
    failed_step_id: 'legacy-test-run-1:4',
  })
  assert.equal(messages.value.filter(message => message.role === 'user').length, userCount)
  assert.equal(state.value.phase, 'idle')
})

test('user stop does not retry the failed step', async () => {
  const retries = []
  const { controller, state } = harness(async (_payload, { onEvent }) => {
    onEvent(envelope('legacy-test-run-1', 1, 2, 'aborted', { termination_reason: 'user_abort' }))
  }, {
    retryRun: async (input) => {
      retries.push(input)
      return { conversation_id: 'conversation-1', run_id: 'retry-run', epoch: 2, cursor: 0 }
    },
  })

  await controller.submitMessage('build a workflow')
  assert.equal(state.value.retryable, false)
  await controller.retryFailedStep()
  assert.equal(retries.length, 0)
})
