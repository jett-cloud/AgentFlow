import test from 'node:test'
import assert from 'node:assert/strict'
import {
  canApplyWorkflowAssistCandidate,
  isPreviewableAssistGraph,
  nextConversationIdAfterDelete,
  normalizeConversationTitle,
  workflowContractReportPresentation,
} from './workflowAssistUx.js'

test('a candidate is previewable only when it has at least one node', () => {
  assert.equal(isPreviewableAssistGraph(null), false)
  assert.equal(isPreviewableAssistGraph({ nodes: [], edges: [] }), false)
  assert.equal(isPreviewableAssistGraph({ nodes: [{ id: 'start' }] }), true)
})

test('deleting the current conversation selects the next remaining one', () => {
  const conversations = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]
  assert.equal(nextConversationIdAfterDelete(conversations, 'a', 'a'), 'b')
  assert.equal(nextConversationIdAfterDelete(conversations, 'c', 'c'), 'a')
})

test('deleting a non-current conversation leaves the current selection', () => {
  const conversations = [{ id: 'a' }, { id: 'b' }]
  assert.equal(nextConversationIdAfterDelete(conversations, 'b', 'a'), 'a')
})

test('deleting the last conversation asks for a new empty conversation', () => {
  assert.equal(nextConversationIdAfterDelete([{ id: 'only' }], 'only', 'only'), null)
})

test('conversation titles are trimmed and capped before save', () => {
  assert.equal(normalizeConversationTitle('  Invoice review  '), 'Invoice review')
  assert.equal(normalizeConversationTitle('   '), '')
  assert.equal(normalizeConversationTitle('x'.repeat(300)), 'x'.repeat(255))
})

test('contract report presentation keeps missing variables and unverified effects visible', () => {
  const presentation = workflowContractReportPresentation({
    contract_report: {
      passed: false,
      summary: { satisfied: 4, missing: 1, conflict: 0, unverified: 1 },
      checks: [
        { id: 'input:answer:start.query', category: 'input', status: 'missing', detail: 'Input query is missing' },
        { id: 'check:quality', category: 'requirement', status: 'unverified', detail: 'Answer is useful' },
        { id: 'node:start', category: 'node', status: 'satisfied', detail: 'Start exists' },
      ],
    },
  })

  assert.equal(presentation.visible, true)
  assert.equal(presentation.level, 'blocked')
  assert.deepEqual(presentation.summary, { satisfied: 4, missing: 1, conflict: 0, unverified: 1 })
  assert.deepEqual(presentation.issues.map(item => item.id), [
    'input:answer:start.query',
    'check:quality',
  ])
})

test('new protocol candidates need complete server evidence before Apply is offered', () => {
  const candidate = {
    graph: { nodes: [{ id: 'start' }], edges: [] },
    revision: 2,
    base_hash: 'b'.repeat(64),
    active_run: null,
    latest_run: { run_id: 'run-1', epoch: 1, status: 'done' },
    contract_report: { passed: true, summary: {}, checks: [] },
    completion_evidence: {
      run_id: 'run-1',
      epoch: 1,
      candidate_revision: 2,
      candidate_base_hash: 'b'.repeat(64),
      app_mode: 'workflow',
      assertion: 'workflow_structure_reaches_terminal',
      contract_protocol_version: 1,
      contract_revision: 1,
      contract_hash: 'c'.repeat(64),
      graph_hash: 'd'.repeat(64),
      validation_version: 1,
    },
  }

  assert.equal(canApplyWorkflowAssistCandidate(candidate, 'workflow'), true)
  assert.equal(canApplyWorkflowAssistCandidate({
    ...candidate,
    completion_evidence: { ...candidate.completion_evidence, graph_hash: null },
  }, 'workflow'), false)
  assert.equal(canApplyWorkflowAssistCandidate({
    ...candidate,
    contract_report: { ...candidate.contract_report, passed: false },
  }, 'workflow'), false)
})
