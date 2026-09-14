import test from 'node:test'
import assert from 'node:assert/strict'
import { applyWorkflowRunEvent, createInitialRunningData } from './applyWorkflowRunEvent.js'

function reduce(events) {
  return events.reduce((state, [event, data]) => applyWorkflowRunEvent(state, { event, data }).state, createInitialRunningData())
}

test('parallel forms survive replay and only the completed instance is removed', () => {
  const a = { node_id: 'approval', form_id: 'a' }
  const b = { node_id: 'approval', form_id: 'b' }
  let state = reduce([['human_input_required', a], ['human_input_required', b], ['human_input_required', a]])
  assert.deepEqual(state.humanInputFormDataList.map(f => f.form_id), ['a', 'b'])
  state = applyWorkflowRunEvent(state, { event: 'human_input_form_filled', data: { node_id: 'approval' } }).state
  assert.equal(state.humanInputFormDataList.length, 2, 'ambiguous legacy event must not remove either instance')
  state = applyWorkflowRunEvent(state, { event: 'node_finished', data: { node_id: 'approval', id: 'b', status: 'succeeded' } }).state
  assert.deepEqual(state.humanInputFormDataList.map(f => f.form_id), ['a'])
})

test('reverse-order filled events only complete the targeted instance', () => {
  const state = reduce([
    ['human_input_required', { node_id: 'approval', node_execution_id: 'exec-a', form_id: 'a' }],
    ['human_input_required', { node_id: 'approval', node_execution_id: 'exec-b', form_id: 'b' }],
    ['human_input_form_filled', { node_id: 'approval', node_execution_id: 'exec-b', form_id: 'b' }],
    ['human_input_form_timeout', { node_id: 'approval', node_execution_id: 'exec-a', form_id: 'a' }],
  ])
  assert.deepEqual(state.humanInputFormDataList.map(form => form.form_id), [])
  assert.deepEqual(state.humanInputFilledFormDataList.map(form => form.form_id), ['b'])
})

test('identified timeout only removes its own form', () => {
  const state = reduce([
    ['human_input_required', { node_id: 'approval', form_id: 'a' }],
    ['human_input_required', { node_id: 'approval', form_id: 'b' }],
    ['human_input_form_timeout', { node_id: 'approval', form_id: 'a' }],
  ])
  assert.deepEqual(state.humanInputFormDataList.map(f => f.form_id), ['b'])
})

test('Graphon node_execution_id keeps repeated Human Input instances independent', () => {
  let state = reduce([
    ['human_input_required', { node_id: 'approval', node_execution_id: 'exec-a', form_token: 'a' }],
    ['human_input_required', { node_id: 'approval', node_execution_id: 'exec-b', form_token: 'b' }],
  ])
  state = applyWorkflowRunEvent(state, {
    event: 'human_input_form_filled',
    data: { node_id: 'approval', node_execution_id: 'exec-b', action_id: 'approve' },
  }).state
  assert.deepEqual(state.humanInputFormDataList.map(form => form.node_execution_id), ['exec-a'])
  assert.deepEqual(state.humanInputFilledFormDataList.map(form => form.node_execution_id), ['exec-b'])

  state = applyWorkflowRunEvent(state, {
    event: 'human_input_form_timeout',
    data: { node_id: 'approval', node_execution_id: 'exec-a' },
  }).state
  assert.equal(state.humanInputFormDataList.length, 0)
  assert.deepEqual(state.tracing.map(item => [item.executionId, item.status]), [
    ['exec-a', 'failed'],
    ['exec-b', 'succeeded'],
  ])
})

test('parallel tracing matches execution ids despite reversed completion and replay', () => {
  const state = reduce([
    ['node_started', { node_id: 'child', id: 'a', inputs: { n: 1 } }],
    ['node_started', { node_id: 'child', id: 'b', inputs: { n: 2 } }],
    ['node_started', { node_id: 'child', id: 'a', inputs: { n: 1 } }],
    ['node_finished', { node_id: 'child', id: 'b', outputs: { n: 20 } }],
    ['node_finished', { node_id: 'child', id: 'a', outputs: { n: 10 } }],
    ['node_finished', { node_id: 'child', id: 'b', outputs: { n: 20 } }],
  ])
  assert.equal(state.tracing.length, 2)
  assert.deepEqual(state.tracing.map(t => [t.executionId, t.inputs.n, t.outputs.n]), [['a', 1, 10], ['b', 2, 20]])
})

test('resume of the same paused run preserves prior tracing and forms', () => {
  let state = applyWorkflowRunEvent(createInitialRunningData(), { event: 'workflow_started', data: { id: 'run' } }).state
  state = applyWorkflowRunEvent(state, { event: 'human_input_required', data: { node_id: 'approval', form_id: 'a' } }).state
  state = applyWorkflowRunEvent(state, { event: 'workflow_paused', workflow_run_id: 'run' }).state
  state = applyWorkflowRunEvent(state, { event: 'workflow_started', data: { id: 'run' } }).state
  assert.equal(state.humanInputFormDataList.length, 1)
  assert.equal(state.tracing.length, 1)
})

test('a new workflow run clears old forms and traces', () => {
  const state = reduce([
    ['workflow_started', { id: 'old' }],
    ['human_input_required', { node_id: 'approval', form_id: 'a' }],
    ['workflow_paused', { id: 'old' }],
    ['workflow_started', { id: 'new' }],
  ])
  assert.equal(state.tracing.length, 0)
  assert.equal(state.humanInputFormDataList.length, 0)
})

test('identified stale filled and timeout events do not mutate the pending form', () => {
  const pending = { node_id: 'approval', node_execution_id: 'current', form_id: 'current' }
  for (const event of ['human_input_form_filled', 'human_input_form_timeout']) {
    const state = reduce([
      ['human_input_required', pending],
      [event, { node_id: 'approval', node_execution_id: 'stale', form_id: 'stale' }],
    ])
    assert.deepEqual(state.humanInputFormDataList.map(form => form.form_id), ['current'])
    assert.equal(state.humanInputFilledFormDataList?.length || 0, 0)
    assert.equal(state.tracing[0].status, 'paused')
  }
})

test('legacy completion resolves a single pending form and keeps its identity', () => {
  const state = reduce([
    ['node_started', { node_id: 'approval', id: 'a' }],
    ['human_input_required', { node_id: 'approval', form_id: 'a' }],
    ['human_input_form_filled', { node_id: 'approval', action_id: 'submit' }],
  ])
  assert.equal(state.humanInputFormDataList.length, 0)
  assert.equal(state.humanInputFilledFormDataList[0].form_id, 'a')
  assert.equal(state.tracing.length, 1)
  assert.equal(state.tracing[0].status, 'succeeded')
})

test('container completions use execution identity for repeated containers', () => {
  for (const type of ['iteration', 'loop']) {
    const state = reduce([
      [`${type}_started`, { node_id: 'container', id: 'a' }],
      [`${type}_started`, { node_id: 'container', id: 'b' }],
      [`${type}_completed`, { node_id: 'container', id: 'b', outputs: { n: 2 } }],
      [`${type}_completed`, { node_id: 'container', id: 'a', outputs: { n: 1 } }],
    ])
    assert.deepEqual(state.tracing.map(t => [t.executionId, t.outputs.n]), [['a', 1], ['b', 2]])
  }
})

test('replayed required forms do not reopen completed instances', () => {
  const state = reduce([
    ['human_input_required', { node_id: 'approval', form_id: 'a' }],
    ['node_finished', { node_id: 'approval', id: 'a' }],
    ['human_input_required', { node_id: 'approval', form_id: 'a' }],
  ])
  assert.equal(state.humanInputFormDataList.length, 0)
  assert.equal(state.tracing[0].status, 'succeeded')
})
