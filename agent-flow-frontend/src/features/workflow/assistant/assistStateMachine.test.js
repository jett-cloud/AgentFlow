import test from 'node:test'
import assert from 'node:assert/strict'
import {
  AssistPhase,
  approvedDatasetsFromSession,
  approvedToolsFromSession,
  createAssistSession,
  reduceAssist,
} from './assistStateMachine.js'

function plan(overrides = {}) {
  return {
    nodes: [{ label: 'Agent', node_type: 'agent', purpose: 'run task' }],
    mutable_node_ids: ['n1'],
    mode: 'local',
    intent_flags: { wants_agent: true },
    ...overrides,
  }
}

function sessionAfterSuccessfulDone() {
  let session = reduceAssist(createAssistSession(), { type: 'SEND' })
  const graph = { nodes: [{ id: 'n1' }], edges: [] }
  const diff = { added: ['n1'], removed: [], updated: [] }
  session = reduceAssist(session, {
    type: 'SSE',
    event: 'done',
    graph,
    diff,
    validation: { ok: true, errors: [] },
  })
  return { session, graph, diff }
}

test('SET_MODE keeps candidate graph and apply after a successful done', () => {
  const { session: ready, graph, diff } = sessionAfterSuccessfulDone()
  const session = reduceAssist(ready, { type: 'SET_MODE', mode: 'local' })

  assert.equal(session.mode, 'local')
  assert.equal(session.phase, AssistPhase.idle)
  assert.equal(session.candidateGraph, graph)
  assert.deepEqual(session.diff, diff)
  assert.equal(session.applyEnabled, true)
  assert.equal(session.composerSendable, true)
})

test('SET_TARGET_NODES after a successful done keeps the graph and applyEnabled', () => {
  const { session: ready, graph, diff } = sessionAfterSuccessfulDone()
  const session = reduceAssist(ready, {
    type: 'SET_TARGET_NODES',
    nodeIds: ['llm-1', 'tool-2', 'llm-1', ''],
  })

  assert.equal(session.mode, 'local')
  assert.deepEqual(session.targetNodeIds, ['llm-1', 'tool-2'])
  assert.equal(session.phase, AssistPhase.idle)
  assert.equal(session.candidateGraph, graph)
  assert.deepEqual(session.diff, diff)
  assert.equal(session.applyEnabled, true)
})

test('CLEAR_TARGET_NODES after a successful done keeps the graph and applyEnabled', () => {
  const { session: ready, graph } = sessionAfterSuccessfulDone()
  let session = reduceAssist(ready, {
    type: 'SET_TARGET_NODES',
    nodeIds: ['llm-1'],
  })
  session = reduceAssist(session, { type: 'CLEAR_TARGET_NODES' })

  assert.equal(session.mode, 'rebuild')
  assert.deepEqual(session.targetNodeIds, [])
  assert.equal(session.candidateGraph, graph)
  assert.equal(session.applyEnabled, true)
})

test('approved resource helpers still build payload values', () => {
  const session = {
    approvedToolKeys: ['web/search'],
    approvedDatasetIds: ['dataset-1'],
  }
  const resourcePlan = plan({
    resource_requests: [
      { kind: 'dataset', dataset_id: 'dataset-1', dataset_name: 'Research', reason: 'Use knowledge' },
    ],
  })

  assert.deepEqual(approvedToolsFromSession(session), [{ provider_name: 'web', tool_name: 'search' }])
  assert.deepEqual(approvedDatasetsFromSession(session, resourcePlan), [{ id: 'dataset-1', name: 'Research' }])
})

test('running send supersedes instead of queueing', () => {
  const idle = createAssistSession()
  let state = reduceAssist(idle, { type: 'SEND' })
  assert.equal(state.phase, 'running')
  state = reduceAssist(state, { type: 'SEND' })
  assert.equal(state.terminationReason, 'superseded_by_new_turn')
  assert.equal(state.phase, 'running')
  assert.equal(state.applyEnabled, false)
})

test('aborted does not enable apply', () => {
  const running = reduceAssist(createAssistSession(), { type: 'SEND' })
  const state = reduceAssist(running, {
    type: 'SSE',
    event: 'aborted',
    termination_reason: 'user_abort',
  })
  assert.equal(state.phase, 'idle')
  assert.equal(state.applyEnabled, false)
  assert.equal(state.retryable, false)
  assert.equal(state.failedStepId, '')
})

test('turn_complete ends the run without enabling Apply', () => {
  const running = reduceAssist(createAssistSession(), { type: 'SEND' })
  const state = reduceAssist(running, {
    type: 'SSE',
    event: 'turn_complete',
  })
  assert.equal(state.phase, 'idle')
  assert.equal(state.applyEnabled, false)
  assert.equal(state.terminationReason, null)
  assert.equal(state.statusMessage, '')
  assert.deepEqual(state.errors, [])
})

test('failed and error never light Apply', () => {
  const running = reduceAssist(createAssistSession(), { type: 'SEND' })
  const failed = reduceAssist(running, { type: 'SSE', event: 'failed', reason: 'cannot continue', step_id: 'failed:1' })
  assert.equal(failed.phase, 'idle')
  assert.equal(failed.applyEnabled, false)
  assert.equal(failed.retryable, true)
  assert.equal(failed.failedStepId, 'failed:1')

  const errored = reduceAssist(running, {
    type: 'SSE',
    event: 'error',
    message: 'runaway',
    termination_reason: 'runaway_guard',
    step_id: 'error:runaway',
  })
  assert.equal(errored.phase, 'idle')
  assert.equal(errored.applyEnabled, false)
  assert.equal(errored.retryable, true)
  assert.equal(errored.failedStepId, 'error:runaway')
})

test('only done with a passing validation enables Apply', () => {
  const running = reduceAssist(createAssistSession(), { type: 'SEND' })
  const graph = { nodes: [{ id: 'n1' }], edges: [] }
  const diff = { added: ['n1'], removed: [], updated: [] }
  const done = reduceAssist(running, {
    type: 'SSE',
    event: 'done',
    graph,
    summary: 'ready',
    diff,
    validation: { ok: true, errors: [] },
  })
  assert.equal(done.phase, 'idle')
  assert.equal(done.applyEnabled, true)
  assert.equal(done.candidateGraph, graph)
  assert.deepEqual(done.diff, diff)

  const invalid = reduceAssist(running, {
    type: 'SSE',
    event: 'done',
    graph,
    summary: 'not valid',
    diff,
    validation: { ok: false, errors: [{ detail: 'broken' }] },
  })
  assert.equal(invalid.applyEnabled, false)
})

test('tool_result with graph updates preview only and does not enable Apply', () => {
  const running = reduceAssist(createAssistSession(), { type: 'SEND' })
  const preview = { nodes: [{ id: 'preview' }], edges: [] }
  const state = reduceAssist(running, {
    type: 'SSE',
    event: 'tool_result',
    id: 'call-1',
    name: 'build_node',
    ok: true,
    summary: '写入节点',
    graph: preview,
  })
  assert.equal(state.phase, 'running')
  assert.equal(state.candidateGraph, preview)
  assert.equal(state.applyEnabled, false)
})

test('waiting_user keeps composer sendable and does not enable Apply', () => {
  const running = reduceAssist(createAssistSession(), { type: 'SEND' })
  const state = reduceAssist(running, {
    type: 'SSE',
    event: 'waiting_user',
    tool_call_id: 'ask-1',
    questions: [{ id: 'format', question: 'Which format?', kind: 'text' }],
  })
  assert.equal(state.phase, 'waiting_user')
  assert.equal(state.applyEnabled, false)
  assert.equal(state.composerSendable, true)
  assert.equal(state.waitingUser.tool_call_id, 'ask-1')
})

test('composer stays sendable in idle, running, and waiting_user', () => {
  const idle = createAssistSession()
  assert.equal(idle.composerSendable, true)
  const running = reduceAssist(idle, { type: 'SEND' })
  assert.equal(running.composerSendable, true)
  const waiting = reduceAssist(running, {
    type: 'SSE',
    event: 'waiting_user',
    tool_call_id: 'ask-1',
    questions: [],
  })
  assert.equal(waiting.composerSendable, true)
})

test('abort status text is persisted for each termination reason', () => {
  const running = reduceAssist(createAssistSession(), { type: 'SEND' })
  const userAbort = reduceAssist(running, {
    type: 'SSE',
    event: 'aborted',
    termination_reason: 'user_abort',
  })
  assert.equal(userAbort.statusMessage, '已停止。')

  const superseded = reduceAssist(running, { type: 'SEND' })
  assert.equal(superseded.statusMessage, '已根据你的新消息停止上一轮；已写入的候选图保留。')

  const disconnected = reduceAssist(running, {
    type: 'SSE',
    event: 'aborted',
    termination_reason: 'transport_disconnect',
  })
  assert.equal(disconnected.statusMessage, '连接中断；候选图保留。')
  assert.notEqual(disconnected.statusMessage, '已停止。')
})

test('English reducer status copy covers abort and supersede paths', () => {
  const running = reduceAssist(createAssistSession(), { type: 'SEND' }, 'en')
  const superseded = reduceAssist(running, { type: 'SEND' }, 'en')
  const aborted = reduceAssist(running, {
    type: 'SSE',
    event: 'aborted',
    termination_reason: 'user_abort',
  }, 'en')

  assert.equal(superseded.statusMessage, 'The previous Run stopped for your new message; its saved candidate is preserved.')
  assert.equal(aborted.statusMessage, 'Stopped.')
})
