import test from 'node:test'
import assert from 'node:assert/strict'

import workflowAssistV2ContractJson from './workflowAssistV2Contract.json' with { type: 'json' }
import { WORKFLOW_ASSIST_V2_CONTRACT } from './workflowAssistV2Contract.js'

test('workflow assist v2 runtime contract equals its JSON mirror', () => {
  assert.deepEqual(WORKFLOW_ASSIST_V2_CONTRACT, workflowAssistV2ContractJson)
})

test('workflow assist v2 request schemas preserve exact wire-field names', () => {
  assert.deepEqual(Object.keys(WORKFLOW_ASSIST_V2_CONTRACT.requests.turns.schema).sort(), [
    'message',
    'mode',
    'model_config',
    'references',
    'selected_node',
  ])
  assert.deepEqual(Object.keys(WORKFLOW_ASSIST_V2_CONTRACT.requests.apply.schema).sort(), [
    'conversation_id',
    'hash',
  ])
})

test('workflow assist v2 response and conflict schemas preserve exact wire-field names', () => {
  assert.deepEqual(Object.keys(WORKFLOW_ASSIST_V2_CONTRACT.endpoints.turns.response.required).sort(), [
    'conversation_id',
    'cursor',
    'epoch',
    'run_id',
  ])

  for (const endpoint of ['abort', 'apply']) {
    const conflict = WORKFLOW_ASSIST_V2_CONTRACT.endpoints[endpoint].conflict_response
    assert.deepEqual(conflict.required, ['active_run', 'latest_run'])
    assert.deepEqual(conflict.run_summary, ['run_id', 'epoch', 'status'])
  }
})

test('workflow assist v2 locks the canonical message.delta payload field', () => {
  assert.deepEqual(WORKFLOW_ASSIST_V2_CONTRACT.event_payloads['message.delta'], {
    required: ['text'],
    optional: ['message_id', 'delta_index', 'stream_mode'],
  })
  assert.deepEqual(WORKFLOW_ASSIST_V2_CONTRACT.event_payloads['reasoning.delta'], {
    required: ['text'],
    optional: ['message_id', 'delta_index', 'stream_mode'],
  })
})
