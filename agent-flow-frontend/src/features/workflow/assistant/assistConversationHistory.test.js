import test from 'node:test'
import assert from 'node:assert/strict'

import { buildAssistHistoryMessages } from './assistConversationHistory.js'

test('history deduplicates semantically identical instructions across server records', () => {
  const record = {
    id: 'message-1',
    role: 'user',
    payload: { instruction: 'build a workflow' },
  }

  const messages = buildAssistHistoryMessages([record, { ...record, id: 'message-2' }])

  assert.deepEqual(messages, [{ role: 'user', text: 'build a workflow', turnKey: 'message:message-1' }])
})

test('history ignores thought and status placeholders while grouping operations', () => {
  const record = {
    id: 'assistant-1',
    role: 'assistant',
    payload: {
      events: [
        { event: 'thought', delta: 'hidden' },
        { event: 'status', stage: 'planning' },
        { event: 'operation', stage: 'planning', action: 'search_tools', query: 'web', count: 1 },
        { event: 'operation', stage: 'planning', action: 'search_tools', query: 'web', count: 3 },
        { event: 'plan', nodes: [{ id: 'node-1' }], edges: [] },
      ],
    },
  }
  const messages = buildAssistHistoryMessages([record, { ...record, id: 'assistant-2' }])

  assert.equal(messages.length, 2)
  assert.equal(messages[0].kind, 'activity')
  assert.equal(messages[0].status, 'completed')
  assert.equal(messages[0].items.length, 1)
  assert.equal(messages[0].items[0].count, 3)
  assert.equal(messages[1].kind, 'plan_summary')
})

test('history restores only the server pending clarification as interactive', () => {
  const records = [
    { id: 'c1', role: 'assistant', event_type: 'clarification', payload: { clarification_id: 'old', questions: [] } },
    { id: 'c2', role: 'assistant', event_type: 'clarification', payload: { clarification_id: 'current', questions: [] } },
  ]

  const messages = buildAssistHistoryMessages(records, { clarification_id: 'current' })

  assert.equal(messages[0].status, 'resolved')
  assert.equal(messages[1].status, 'pending')
})

test('history preserves failed stream state even when no operation was emitted', () => {
  const messages = buildAssistHistoryMessages([{
    id: 'failed-1',
    role: 'assistant',
    status: 'failed',
    payload: { events: [{ event: 'error', message: 'network down' }] },
  }])

  assert.equal(messages.length, 1)
  assert.equal(messages[0].kind, 'activity')
  assert.equal(messages[0].status, 'failed')
  assert.equal(messages[0].message, 'network down')
})

test('history renders typed answer labels and assistant messages without internal ids', () => {
  const messages = buildAssistHistoryMessages([
    {
      id: 'answer-1',
      role: 'user',
      event_type: 'clarification_answer',
      payload: {
        clarification_id: 'clarification-1',
        answers: [
          {
            question_id: 'knowledge',
            kind: 'resource_select',
            resource_ids: ['dataset-internal-id'],
            labels: ['Product docs'],
          },
        ],
      },
    },
    {
      id: 'assistant-1',
      role: 'assistant',
      payload: {
        events: [{ event: 'assistant_message', message: 'I use the selected knowledge base for retrieval.' }],
      },
    },
  ])

  assert.equal(messages[0].text, 'Product docs')
  assert.equal(messages[1].text, 'I use the selected knowledge base for retrieval.')
})

test('history restores unified user message records', () => {
  const messages = buildAssistHistoryMessages([
    { id: 'message-1', role: 'user', event_type: 'message', payload: { message: 'Why is this required?' } },
  ])

  assert.equal(messages[0].text, 'Why is this required?')
})

test('history restores user text payload and mention references as chips', () => {
  const messages = buildAssistHistoryMessages([
    {
      id: 'message-2',
      role: 'user',
      event_type: 'message',
      payload: {
        text: '把 知识库检索 接到 LLM',
        references: [{ kind: 'node', id: 'n1', label: '知识库检索' }],
      },
    },
  ])

  assert.equal(messages[0].text, '把 知识库检索 接到 LLM')
  assert.deepEqual(messages[0].references, [{ kind: 'node', id: 'n1', label: '知识库检索' }])
})

test('history restores requirement progress without evidence or internal keys', () => {
  const messages = buildAssistHistoryMessages([{
    id: 'assistant-requirements',
    role: 'assistant',
    payload: {
      events: [{
        event: 'operation',
        stage: 'planning',
        action: 'requirements_resolved',
        count: 1,
        requirement_keys: ['rag.source'],
        labels: ['RAG 数据源'],
        evidence: 'internal evidence',
      }],
    },
  }])

  assert.equal(messages[0].items[0].message, '已理解 1 项需求：RAG 数据源')
  assert.doesNotMatch(JSON.stringify(messages), /rag\.source|internal evidence/)
})

test('history restores v4 phase summaries and resource names only', () => {
  const messages = buildAssistHistoryMessages([{
    id: 'assistant-v4',
    role: 'assistant',
    payload: {
      events: [
        { event: 'planner_thinking', phase: 'understanding' },
        { event: 'turn_interpreted', action: 'turn_interpreted' },
        {
          event: 'resource_bound',
          action: 'resource_bound',
          resource_name: 'Product docs',
          resource_id: 'dataset-secret',
        },
      ],
    },
  }])

  assert.equal(messages[0].status, 'completed')
  assert.deepEqual(messages[0].items.map(item => item.message), [
    '已理解当前需求',
    '已绑定资源：Product docs',
  ])
  assert.doesNotMatch(JSON.stringify(messages), /dataset-secret/)
})

test('history restores chat-loop waiting_user, abort status, and done completion', () => {
  const messages = buildAssistHistoryMessages([
    {
      id: 'ask-1',
      role: 'assistant',
      event_type: 'tool_call',
      status: 'pending',
      payload: { id: 'ask-1', name: 'ask_user', arguments: { questions: [{ id: 'format', question: 'Format?', kind: 'text' }] } },
    },
    {
      id: 'run-1',
      role: 'assistant',
      payload: {
        events: [
          { event: 'aborted', termination_reason: 'user_abort' },
          {
            event: 'done',
            summary: 'ready',
            diff: { added: ['n1'], removed: [], updated: [] },
            validation: { ok: true, errors: [] },
          },
        ],
      },
    },
  ])

  assert.equal(messages[0].kind, 'clarification')
  assert.equal(messages[0].clarification.clarification_id, 'ask-1')
  assert.equal(messages.some(message => message.kind === 'status' && message.text === '已停止。'), true)
  assert.equal(messages.some(message => message.kind === 'completion' && message.summary === 'ready'), true)
})

test('English history uses selected-language planning and abort copy', () => {
  const messages = buildAssistHistoryMessages([{
    id: 'run-english',
    role: 'assistant',
    payload: {
      events: [
        { event: 'planner_thinking', phase: 'understanding' },
        { event: 'resource_resolving', resource_kind: 'dataset' },
        { event: 'aborted', termination_reason: 'user_abort' },
      ],
    },
  }], null, 'en')

  assert.equal(messages[0].items[0].message, 'Resolving knowledge base resources…')
  assert.equal(messages[1].text, 'Stopped.')
})

test('conversation timestamps are localized instead of exposing raw server text', async () => {
  const history = await import('./assistConversationHistory.js')
  assert.equal(typeof history.formatAssistConversationTimestamp, 'function')

  const raw = '2026-08-25T00:00:00Z'
  const english = history.formatAssistConversationTimestamp(raw, 'en')
  const chinese = history.formatAssistConversationTimestamp(raw, 'zh-Hans')

  assert.notEqual(english, raw)
  assert.notEqual(chinese, raw)
  assert.notEqual(english, chinese)
  assert.equal(history.formatAssistConversationTimestamp('not-a-date', 'en'), '')
})
