import test from 'node:test'
import assert from 'node:assert/strict'
import {
  applyDebugRunEvent,
  buildStartVariableDefaults,
  createInitialDebugState,
  RUN_STATUS,
  validateRequiredStartInputs,
} from './workflowDebugSession.js'

test('workflow_started records taskId and running status', () => {
  const { state } = applyDebugRunEvent(createInitialDebugState(), {
    event: 'workflow_started',
    task_id: 'task-1',
    data: { id: 'run-1' },
  })
  assert.equal(state.taskId, 'task-1')
  assert.equal(state.isRunning, true)
  assert.equal(state.runStatus, RUN_STATUS.running)
})

test('node events produce canvas nodeState', () => {
  const started = applyDebugRunEvent(createInitialDebugState(), {
    event: 'node_started',
    data: { node_id: 'llm-1', inputs: { a: 1 } },
  })
  assert.deepEqual(started.nodeState, {
    nodeId: 'llm-1',
    status: 'running',
    inputs: { a: 1 },
  })
  assert.equal(started.canvasEvent.type, 'node_started')

  const finished = applyDebugRunEvent(started.state, {
    event: 'node_finished',
    data: {
      node_id: 'llm-1',
      status: 'succeeded',
      outputs: { text: 'hi' },
      node_type: 'llm',
    },
  })
  assert.equal(finished.nodeState.status, 'succeeded')
  assert.deepEqual(finished.nodeState.outputs, { text: 'hi' })
  assert.equal(finished.canvasEvent.type, 'node_finished')
  assert.equal(finished.canvasEvent.nodeType, 'llm')
})

test('workflow_started emits canvasEvent for waiting paint', () => {
  const { canvasEvent } = applyDebugRunEvent(createInitialDebugState(), {
    event: 'workflow_started',
    task_id: 'task-1',
    data: {},
  })
  assert.deepEqual(canvasEvent, { type: 'workflow_started' })
})

test('text_chunk and message append transcript', () => {
  let { state } = applyDebugRunEvent(createInitialDebugState(), {
    event: 'text_chunk',
    data: { text: 'Hello' },
  })
  ;({ state } = applyDebugRunEvent(state, {
    event: 'message',
    data: { answer: ' world' },
  }))
  assert.equal(state.transcript, 'Hello world')
})

test('workflow_finished captures outputs and failed status', () => {
  const { state, canvasEvent } = applyDebugRunEvent({
    ...createInitialDebugState(),
    isRunning: true,
    runStatus: RUN_STATUS.running,
  }, {
    event: 'workflow_finished',
    data: { status: 'failed', error: 'boom', outputs: { result: null } },
  })
  assert.equal(state.isRunning, false)
  assert.equal(state.runStatus, RUN_STATUS.failed)
  assert.equal(state.runError, 'boom')
  assert.deepEqual(state.runOutputs, { result: null })
  assert.deepEqual(canvasEvent, { type: 'workflow_finished', status: RUN_STATUS.failed })
})

test('error event marks failed', () => {
  const { state, canvasEvent } = applyDebugRunEvent(createInitialDebugState(), {
    event: 'error',
    message: 'stream broke',
  })
  assert.equal(state.runStatus, RUN_STATUS.failed)
  assert.equal(state.runError, 'stream broke')
  assert.equal(state.isRunning, false)
  assert.deepEqual(canvasEvent, { type: 'workflow_finished', status: RUN_STATUS.failed })
})

test('conversation_id and message_id are retained from SSE root', () => {
  const { state } = applyDebugRunEvent(createInitialDebugState(), {
    event: 'workflow_started',
    task_id: 't1',
    conversation_id: 'conv-9',
    message_id: 'msg-3',
    data: {},
  })
  assert.equal(state.conversationId, 'conv-9')
  assert.equal(state.parentMessageId, 'msg-3')
})

test('buildStartVariableDefaults and required validation', () => {
  const variables = [
    { variable: 'name', label: '姓名', required: true, default: '' },
    { variable: 'city', required: false, default: 'Shanghai' },
  ]
  const defaults = buildStartVariableDefaults(variables)
  assert.deepEqual(defaults, { name: '', city: 'Shanghai' })
  assert.deepEqual(validateRequiredStartInputs(variables, defaults), ['姓名'])
  assert.deepEqual(validateRequiredStartInputs(variables, { ...defaults, name: 'Ada' }), [])
})
