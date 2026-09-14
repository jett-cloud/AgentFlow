import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { CONTAINER_SELECTABLE_BLOCKS } from '../../model/nodeMeta.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  ANSWER_DEFAULTS,
  getAnswerValidationErrors,
  isAnswerAllowedInMode,
  isAnswerVariableSupported,
  normalizeAnswerNodeData,
} from './answerNode.js'

// 1. Defaults and availability
test('new Answer nodes use the official Dify defaults', () => {
  const { newNode } = generateNewNode({ type: 'answer', id: 'answer-1' })
  assert.deepEqual(newNode.data, {
    type: 'answer',
    title: '直接回复',
    ...ANSWER_DEFAULTS,
  })
})

test('Answer is available only in Chatflow mode', () => {
  assert.equal(isAnswerAllowedInMode('advanced-chat'), true)
  assert.equal(isAnswerAllowedInMode('workflow'), false)
  assert.equal(isAnswerAllowedInMode('chat'), false)
})

// 2. Normalization, migration, and unknown-field preservation
test('Answer normalization always writes the canonical backend type', () => {
  const normalized = normalizeAnswerNodeData({ type: 'future-answer-alias', future: true })
  assert.equal(normalized.type, 'answer')
  assert.equal(normalized.future, true)
})

test('Answer normalization preserves unknown fields and official variables', () => {
  assert.deepEqual(normalizeAnswerNodeData({
    answer: 42,
    variables: [{ variable: 'legacy', value_selector: ['llm', 'text'] }],
    future: true,
  }), {
    type: 'answer',
    answer: '42',
    variables: [{ variable: 'legacy', value_selector: ['llm', 'text'] }],
    future: true,
  })
})

// 3. Selectable outputs
test('Answer variable picker supports files but excludes array objects', () => {
  assert.equal(isAnswerVariableSupported({ type: 'string' }), true)
  assert.equal(isAnswerVariableSupported({ type: 'file' }), true)
  assert.equal(isAnswerVariableSupported({ type: 'arrayObject' }), false)
})

test('Answer has no selectable outputs but retains its control-flow branch', () => {
  const data = { type: 'answer', answer: 'Hi', variables: [] }
  assert.deepEqual(getNodeOutputVars({ id: 'answer', data }), [])
  assert.deepEqual(getNodeOutputBranches(data).map(branch => branch.id), ['source'])
})

// 4. Handles and container placement
test('Answer can be added inside Chatflow iteration and loop containers', () => {
  assert.equal(CONTAINER_SELECTABLE_BLOCKS.includes('answer'), true)
})

test('Answer rejects blank reply content', () => {
  assert.deepEqual(getAnswerValidationErrors({ answer: '' }), ['请填写回复内容'])
  assert.deepEqual(getAnswerValidationErrors({ answer: ' \n\t ' }), ['请填写回复内容'])
  assert.deepEqual(getAnswerValidationErrors({ answer: '{{#llm.text#}}' }), [])
})

// 5. DSL round-trip
test('Answer DSL round-trip preserves official and unknown fields', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'answer-1',
      type: 'custom',
      data: {
        type: 'answer',
        answer: '{{#llm.text#}}',
        variables: [],
        future: { enabled: true },
      },
    }],
    edges: [],
  })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.deepEqual(exported.nodes[0].data, {
    type: 'answer',
    answer: '{{#llm.text#}}',
    variables: [],
    future: { enabled: true },
  })
})

// 6. Checklist: invalid and valid graphs
test('Checklist enforces Answer mode, presence, and upstream references', () => {
  const workflowIssues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: '开始' } },
      { id: 'answer', data: { type: 'answer', title: '直接回复', answer: 'hello', variables: [] } },
    ],
    edges: [{ id: 'e1', source: 'start', target: 'answer' }],
  })
  assert.ok(workflowIssues.some(issue => issue.id === 'answer-mode-answer'))

  const missingIssues = buildWorkflowChecklist({
    nodes: [{ id: 'start', data: { type: 'start', title: '开始' } }],
    edges: [],
  }, { isChatMode: true })
  assert.ok(missingIssues.some(issue => issue.id === 'answer-required'))

  const invalidReferenceIssues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: '开始' } },
      { id: 'answer', data: { type: 'answer', title: '直接回复', answer: '{{#missing.text#}}', variables: [] } },
    ],
    edges: [{ id: 'e1', source: 'start', target: 'answer' }],
  }, { isChatMode: true })
  assert.ok(invalidReferenceIssues.some(issue => issue.id === 'invalid-var-answer'))
})

test('Answer checklist accepts non-blank replies and outgoing control flow', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: '开始', variables: [] } },
      { id: 'answer-1', data: { type: 'answer', title: '直接回复 1', answer: '处理中', variables: [] } },
      { id: 'answer-2', data: { type: 'answer', title: '直接回复 2', answer: '完成', variables: [] } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'answer-1' },
      { id: 'e2', source: 'answer-1', sourceHandle: 'source', target: 'answer-2' },
    ],
  }, { isChatMode: true })

  assert.deepEqual(issues.filter(issue => issue.level === 'error'), [])
})
