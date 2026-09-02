import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createWorkflowAssistRunState,
  reduceWorkflowAssistRunEvent,
  reduceWorkflowAssistTimeline,
  workflowAssistRunCursor,
} from './workflowAssistRunReducer.js'

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

test('timeline replay keeps sequence-zero turns distinct and duplicate envelopes are strict no-ops', () => {
  const events = [
    envelope('run-1', 1, 0, 'user.message', { text: 'first' }),
    envelope('run-1', 1, 1, 'message.delta', { text: 'hello' }),
    envelope('run-2', 2, 0, 'user.message', { text: 'second' }),
    envelope('run-2', 2, 1, 'message.delta', { text: 'world' }),
  ]
  const replayed = reduceWorkflowAssistTimeline(createWorkflowAssistRunState(), events)
  const duplicate = reduceWorkflowAssistRunEvent(replayed, events[3])

  assert.equal(duplicate, replayed)
  assert.deepEqual(replayed.messages.filter(message => message.role === 'user').map(message => message.text), [
    'first',
    'second',
  ])
  assert.deepEqual(replayed.messages.filter(message => message.kind === 'assistant_text').map(message => message.text), [
    'hello',
    'world',
  ])
  assert.deepEqual(workflowAssistRunCursor(replayed, 'run-1'), { epoch: 1, sequence: 1 })
  assert.deepEqual(workflowAssistRunCursor(replayed, 'run-2'), { epoch: 2, sequence: 1 })
})

test('the real reducer renders the canonical backend message.delta text payload', () => {
  const state = reduceWorkflowAssistRunEvent(
    createWorkflowAssistRunState(),
    envelope('run-1', 1, 1, 'message.delta', { text: 'visible answer' }),
  )

  assert.equal(
    state.messages.find(message => message.kind === 'assistant_text')?.text,
    'visible answer',
  )
})

test('the real reducer keeps reasoning.delta on the same message_id as narration', () => {
  const state = reduceWorkflowAssistTimeline(createWorkflowAssistRunState(), [
    envelope('run-1', 1, 1, 'reasoning.delta', { text: 'plan first', message_id: 'msg-1' }),
    envelope('run-1', 1, 2, 'message.delta', { text: 'ok', message_id: 'msg-1' }),
  ])
  const bubble = state.messages.find(message => message.kind === 'assistant_text')
  assert.equal(bubble?.text, 'ok')
  assert.equal(bubble?.reasoning, 'plan first')
})

test('timeline recovery adopts authoritative user language before reducing activity copy', () => {
  const state = reduceWorkflowAssistTimeline(createWorkflowAssistRunState(), [
    envelope('run-1', 1, 0, 'user.message', { text: 'Build a support workflow' }),
    envelope('run-1', 1, 1, 'status', { stage: 'planning' }),
  ])

  assert.equal(state.language, 'en')
  assert.equal(state.messages.find(message => message.kind === 'activity')?.message, 'Planning…')
})

test('live reduction uses the explicitly selected language when sequence zero is not streamed', () => {
  const state = reduceWorkflowAssistRunEvent(
    createWorkflowAssistRunState([], 'zh-Hans'),
    envelope('run-1', 1, 1, 'status', { stage: 'planning' }),
    'en',
  )

  assert.equal(state.messages.find(message => message.kind === 'activity')?.message, 'Planning…')
})

test('user.message keeps mention references for chip replay', () => {
  const state = reduceWorkflowAssistRunEvent(
    createWorkflowAssistRunState(),
    envelope('run-1', 1, 0, 'user.message', {
      text: '把 知识库检索 接到 LLM',
      references: [{ kind: 'node', id: 'n1', label: '知识库检索' }],
    }),
  )

  assert.deepEqual(state.messages.find(message => message.role === 'user'), {
    role: 'user',
    text: '把 知识库检索 接到 LLM',
    run_id: 'run-1',
    epoch: 1,
    sequence: 0,
    references: [{ kind: 'node', id: 'n1', label: '知识库检索' }],
  })
})

test('tool results associate only by tool_call_id even when results arrive out of order', () => {
  const state = reduceWorkflowAssistTimeline(createWorkflowAssistRunState(), [
    envelope('run-1', 1, 1, 'tool_call', { tool_call_id: 'call-a', name: 'build_node' }),
    envelope('run-1', 1, 2, 'tool_call', { tool_call_id: 'call-b', name: 'build_node' }),
    envelope('run-1', 1, 3, 'tool_result', { tool_call_id: 'call-b', name: 'build_node', summary: 'second' }),
    envelope('run-1', 1, 4, 'tool_result', { tool_call_id: 'call-a', name: 'build_node', summary: 'first' }),
  ])

  const items = state.messages.filter(message => message.kind === 'activity').flatMap(message => message.items)
  assert.deepEqual(items.map(item => ({ key: item.key, message: item.message })), [
    { key: 'tool:call-a', message: '写入节点 · first' },
    { key: 'tool:call-b', message: '写入节点 · second' },
  ])
})

test('candidate and terminal facts are reduced without storing a candidate graph', () => {
  const state = reduceWorkflowAssistTimeline(createWorkflowAssistRunState(), [
    envelope('run-1', 1, 1, 'candidate.updated', { revision: 4, diff: { added: ['node-1'] } }),
    envelope('run-1', 1, 2, 'waiting_user', {
      tool_call_id: 'ask-1',
      questions: [{ id: 'format', question: 'Format?', kind: 'text' }],
    }),
  ])

  assert.equal(state.candidateRevision, 4)
  assert.equal(state.terminalRuns.has('run-1'), true)
  assert.doesNotMatch(JSON.stringify(state.messages), /candidate_graph|"graph"/)
})

test('large sequential timeline keeps compact per-run dedupe state', () => {
  const events = Array.from({ length: 20_000 }, (_, sequence) => (
    envelope('run-large', 1, sequence, 'candidate.updated', { revision: sequence })
  ))

  const state = reduceWorkflowAssistTimeline(createWorkflowAssistRunState(), events)
  const duplicate = reduceWorkflowAssistRunEvent(state, events[10_000])

  assert.equal(duplicate, state)
  assert.equal(state.eventSequencesByRun['run-large'].through, 19_999)
  assert.equal(state.eventSequencesByRun['run-large'].pending.length, 0)
  assert.equal('seenEvents' in state, false)
})

test('compact dedupe accepts out-of-order gaps once and collapses them when filled', () => {
  const sequenceTwo = envelope('run-1', 1, 2, 'candidate.updated', { revision: 2 })
  const state = reduceWorkflowAssistTimeline(createWorkflowAssistRunState(), [
    sequenceTwo,
    envelope('run-1', 1, 0, 'candidate.updated', { revision: 0 }),
    envelope('run-1', 1, 1, 'candidate.updated', { revision: 1 }),
  ])

  assert.equal(reduceWorkflowAssistRunEvent(state, sequenceTwo), state)
  assert.equal(state.eventSequencesByRun['run-1'].through, 2)
  assert.equal(state.eventSequencesByRun['run-1'].pending.length, 0)
})

test('a non-zero resume cursor compresses a sequential sparse gap into one range', () => {
  const events = Array.from({ length: 10_000 }, (_, index) => (
    envelope('run-resumed', 1, 10_000 + index, 'candidate.updated', { revision: index })
  ))

  const state = reduceWorkflowAssistTimeline(createWorkflowAssistRunState(), events)

  assert.deepEqual(state.eventSequencesByRun['run-resumed'].pending, [[10_000, 19_999]])
})
