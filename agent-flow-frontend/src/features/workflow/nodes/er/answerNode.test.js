import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { CONTAINER_SELECTABLE_BLOCKS } from '../../model/nodeMeta.js'
import {
  ANSWER_DEFAULTS,
  getAnswerValidationErrors,
  isAnswerAllowedInMode,
  isAnswerVariableSupported,
  normalizeAnswerNodeData,
} from './answerNode.js'

test('new Answer nodes use the official Dify defaults', () => {
  const { newNode } = generateNewNode({ type: 'answer', id: 'answer-1' })
  assert.deepEqual(newNode.data, {
    type: 'answer',
    title: '直接回复',
    ...ANSWER_DEFAULTS,
  })
})

test('Answer normalization preserves unknown fields and official variables', () => {
  assert.deepEqual(normalizeAnswerNodeData({
    answer: 42,
    variables: [{ variable: 'legacy', value_selector: ['llm', 'text'] }],
    future: true,
  }), {
    answer: '42',
    variables: [{ variable: 'legacy', value_selector: ['llm', 'text'] }],
    future: true,
  })
})

test('Answer is available only in Chatflow mode', () => {
  assert.equal(isAnswerAllowedInMode('advanced-chat'), true)
  assert.equal(isAnswerAllowedInMode('workflow'), false)
  assert.equal(isAnswerAllowedInMode('chat'), false)
})

test('Answer can be added inside Chatflow iteration and loop containers', () => {
  assert.equal(CONTAINER_SELECTABLE_BLOCKS.includes('answer'), true)
})

test('Answer variable picker supports files but excludes array objects', () => {
  assert.equal(isAnswerVariableSupported({ type: 'string' }), true)
  assert.equal(isAnswerVariableSupported({ type: 'file' }), true)
  assert.equal(isAnswerVariableSupported({ type: 'arrayObject' }), false)
})

test('Answer requires non-empty reply content', () => {
  assert.deepEqual(getAnswerValidationErrors({ answer: '' }), ['请填写回复内容'])
  assert.deepEqual(getAnswerValidationErrors({ answer: '{{#llm.text#}}' }), [])
})

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

test('Answer panel uses the real upstream prompt variable picker', () => {
  const source = readFileSync(new URL('./AnswerPanel.vue', import.meta.url), 'utf8')
  assert.match(source, /PromptVariableTextarea/)
  assert.match(source, /:filter-var="answerVariableFilter"/)
  assert.doesNotMatch(source, /command="llm\.text"/)
  assert.doesNotMatch(source, /command="start\.query"/)
  assert.doesNotMatch(source, /command="code\.result"/)
})
