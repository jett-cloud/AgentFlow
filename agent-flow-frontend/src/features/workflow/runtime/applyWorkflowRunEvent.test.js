import test from 'node:test'
import assert from 'node:assert/strict'
import {
  applyWorkflowRunEvent,
  createInitialRunningData,
  RUN_STATUS,
  RUN_TABS,
} from './applyWorkflowRunEvent.js'

test('workflow without text_chunk still fills RESULT from outputs', () => {
  let { state } = applyWorkflowRunEvent(createInitialRunningData(), {
    event: 'workflow_started',
    task_id: 't1',
    data: {},
  })
  ;({ state } = applyWorkflowRunEvent(state, {
    event: 'node_finished',
    data: { node_id: 'end', status: 'succeeded', outputs: { text: 'hello' } },
  }))
  ;({ state } = applyWorkflowRunEvent(state, {
    event: 'workflow_finished',
    data: { status: 'succeeded', outputs: { text: 'hello' } },
  }))

  assert.equal(state.runStatus, RUN_STATUS.succeeded)
  assert.equal(state.resultText, 'hello')
  assert.equal(state.preferredTab, RUN_TABS.RESULT)
  assert.deepEqual(state.runOutputs, { text: 'hello' })
})

test('multi-key outputs become JSON resultText when no stream', () => {
  const { state } = applyWorkflowRunEvent({
    ...createInitialRunningData(),
    isRunning: true,
    runStatus: RUN_STATUS.running,
  }, {
    event: 'workflow_finished',
    data: { status: 'succeeded', outputs: { a: 1, b: 'x' } },
  })
  assert.match(state.resultText, /"a": 1/)
  assert.equal(state.preferredTab, RUN_TABS.RESULT)
})

test('text_chunk streams into resultText', () => {
  let { state } = applyWorkflowRunEvent(createInitialRunningData(), {
    event: 'text_chunk',
    data: { text: 'Hel' },
  })
  ;({ state } = applyWorkflowRunEvent(state, {
    event: 'text_chunk',
    data: { text: 'lo' },
  }))
  assert.equal(state.resultText, 'Hello')
})

test('tracing records node start and finish', () => {
  let { state } = applyWorkflowRunEvent(createInitialRunningData(), {
    event: 'node_started',
    data: { node_id: 'llm-1', title: 'LLM', inputs: { q: 1 } },
  })
  ;({ state } = applyWorkflowRunEvent(state, {
    event: 'node_finished',
    data: { node_id: 'llm-1', status: 'succeeded', outputs: { text: 'ok' } },
  }))
  assert.equal(state.tracing.length, 1)
  assert.equal(state.tracing[0].status, 'succeeded')
  assert.deepEqual(state.tracing[0].outputs, { text: 'ok' })
})

test('error prefers RESULT tab', () => {
  const { state } = applyWorkflowRunEvent(createInitialRunningData(), {
    event: 'error',
    message: 'boom',
  })
  assert.equal(state.runStatus, RUN_STATUS.failed)
  assert.equal(state.preferredTab, RUN_TABS.RESULT)
  assert.equal(state.runError, 'boom')
})

test('message_end stores citation retriever_resources', () => {
  const { state } = applyWorkflowRunEvent(createInitialRunningData(), {
    event: 'message_end',
    data: {
      metadata: {
        retriever_resources: [
          { document_name: '指南.pdf', dataset_name: '产品库', score: 0.88 },
        ],
      },
    },
  })
  assert.equal(state.citations.length, 1)
  assert.equal(state.citations[0].document_name, '指南.pdf')
  assert.equal(state.citations[0].score, 0.88)
})

test('message_file and message_end.files populate messageFiles', () => {
  let { state } = applyWorkflowRunEvent(createInitialRunningData(), {
    event: 'message_file',
    id: 'mf1',
    type: 'image',
    url: 'https://cdn.example/a.png',
  })
  assert.equal(state.messageFiles.length, 1)
  assert.equal(state.messageFiles[0].id, 'mf1')
  assert.equal(state.messageFiles[0].url, 'https://cdn.example/a.png')

  ;({ state } = applyWorkflowRunEvent(state, {
    event: 'message_end',
    files: [{
      related_id: 'mf2',
      filename: 'b.pdf',
      mime_type: 'application/pdf',
      url: 'https://cdn.example/b.pdf',
    }],
    data: { metadata: { retriever_resources: [] } },
  }))
  assert.equal(state.messageFiles.length, 2)
  assert.equal(state.messageFiles[1].name, 'b.pdf')
})

test('iteration/loop/retry SSE emit canvasEvents and update iterTimes', () => {
  let { state, canvasEvent } = applyWorkflowRunEvent(createInitialRunningData(), {
    event: 'iteration_started',
    data: { node_id: 'iter-1', title: '迭代', metadata: { iterator_length: 4 } },
  })
  assert.equal(canvasEvent.type, 'iteration_started')
  assert.equal(canvasEvent.iterationLength, 4)
  assert.equal(state.iterTimes, 1)

  ;({ state, canvasEvent } = applyWorkflowRunEvent(state, {
    event: 'iteration_next',
    data: { node_id: 'iter-1' },
  }))
  assert.equal(canvasEvent.iterationIndex, 1)
  assert.equal(state.iterTimes, 2)

  ;({ state, canvasEvent } = applyWorkflowRunEvent(state, {
    event: 'loop_next',
    data: { node_id: 'loop-1', index: 3 },
  }))
  assert.deepEqual(canvasEvent, { type: 'loop_next', nodeId: 'loop-1', loopIndex: 3 })

  ;({ canvasEvent } = applyWorkflowRunEvent(state, {
    event: 'node_retry',
    data: { node_id: 'llm-1', retry_index: 2, status: 'running' },
  }))
  assert.equal(canvasEvent.type, 'node_retry')
  assert.equal(canvasEvent.retryIndex, 2)
})

test('text_replace replaces resultText; workflow_paused sets paused', () => {
  let { state } = applyWorkflowRunEvent({
    ...createInitialRunningData(),
    resultText: 'old',
  }, {
    event: 'text_replace',
    data: { text: 'new' },
  })
  assert.equal(state.resultText, 'new')

  ;({ state } = applyWorkflowRunEvent(state, {
    event: 'workflow_paused',
    workflow_run_id: 'run-9',
    data: {},
  }))
  assert.equal(state.runStatus, RUN_STATUS.paused)
  assert.equal(state.workflowRunId, 'run-9')
  assert.equal(state.preferredTab, 'RESULT')
})

test('human_input_required stores form and paints paused canvasEvent', () => {
  const { state, canvasEvent } = applyWorkflowRunEvent(createInitialRunningData(), {
    event: 'human_input_required',
    workflow_run_id: 'run-1',
    data: { node_id: 'hi-1', form_token: 'tok', display_in_ui: true },
  })
  assert.equal(canvasEvent.type, 'human_input_required')
  assert.equal(state.humanInputFormDataList.length, 1)
  assert.equal(state.workflowRunId, 'run-1')
  assert.equal(state.tracing[0]?.status, 'paused')
})

test('human_input_form_filled removes pending form', () => {
  let { state } = applyWorkflowRunEvent(createInitialRunningData(), {
    event: 'human_input_required',
    data: { node_id: 'hi-1', form_token: 'tok' },
  })
  ;({ state } = applyWorkflowRunEvent(state, {
    event: 'human_input_form_filled',
    data: { node_id: 'hi-1', action_id: 'approve' },
  }))
  assert.equal(state.humanInputFormDataList.length, 0)
  assert.equal(state.humanInputFilledFormDataList.length, 1)
})

test('workflow_started stores workflowRunId from data.id', () => {
  const { state } = applyWorkflowRunEvent(createInitialRunningData(), {
    event: 'workflow_started',
    task_id: 't1',
    data: { id: 'run-42' },
  })
  assert.equal(state.workflowRunId, 'run-42')
})

test('workflow_finished attaches grouped files from outputs', () => {
  const { state, canvasEvent } = applyWorkflowRunEvent(createInitialRunningData(), {
    event: 'workflow_finished',
    data: {
      status: 'succeeded',
      outputs: {
        text: 'ok',
        file: {
          dify_model_identity: '__dify__file__',
          filename: 'a.png',
          mime_type: 'image/png',
          url: 'https://example.com/a.png',
          related_id: '1',
          type: 'image',
        },
      },
    },
  })
  assert.equal(state.result.files.length, 1)
  assert.equal(state.result.files[0].varName, 'file')
  assert.equal(state.result.files[0].list[0].name, 'a.png')
  assert.equal(state.preferredTab, 'RESULT')
  assert.deepEqual(canvasEvent, { type: 'workflow_finished', status: 'succeeded' })
})

test('tracing entry keeps process_data node_type and tokens metadata', () => {
  let { state } = applyWorkflowRunEvent(createInitialRunningData(), {
    event: 'node_started',
    data: { node_id: 'llm-1', node_type: 'llm', title: 'LLM', inputs: { q: 1 } },
  })
  ;({ state } = applyWorkflowRunEvent(state, {
    event: 'node_finished',
    data: {
      node_id: 'llm-1',
      node_type: 'llm',
      status: 'succeeded',
      inputs: { q: 1 },
      process_data: { model: 'gpt' },
      outputs: { text: 'hi' },
      elapsed_time: 1.234,
      execution_metadata: { total_tokens: 42 },
    },
  }))
  const item = state.tracing[0]
  assert.equal(item.nodeType, 'llm')
  assert.deepEqual(item.processData, { model: 'gpt' })
  assert.equal(item.executionMetadata.total_tokens, 42)
  assert.equal(item.elapsed_time, 1.234)
})
