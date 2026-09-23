import test from 'node:test'
import assert from 'node:assert/strict'
import {
  finishThinkingEvents,
  mergePersistedMessagesWithThinking,
  normalizeAgentMessagesForDisplay,
  upsertThinkingEvent,
  upsertToolEventMessage,
} from './agentEventHelpers.js'
import * as agentEventHelpers from './agentEventHelpers.js'

test('tool result updates the matching call message', () => {
  const messages = []

  upsertToolEventMessage(messages, {
    event: 'tool_call',
    call_id: 'call-1',
    name: 'bootstrap_scaffold',
    arguments: { user_prompt: 'create tool' },
  })
  upsertToolEventMessage(messages, {
    event: 'tool_result',
    call_id: 'call-1',
    name: 'bootstrap_scaffold',
    ok: true,
    summary: 'created 6 files',
  })

  assert.equal(messages.length, 1)
  assert.equal(messages[0].tool_calls[0].status, 'completed')
  assert.equal(messages[0].tool_calls[0].summary, 'created 6 files')
})

test('legacy events without call_id remain visible', () => {
  const messages = []

  upsertToolEventMessage(messages, {
    event: 'tool_result',
    name: 'validate',
    ok: false,
    summary: 'invalid yaml',
  })

  assert.equal(messages.length, 1)
  assert.equal(messages[0].content, '工具失败：validate')
})

test('thinking deltas are aggregated by call id and closed by done event', () => {
  const messages = []

  upsertThinkingEvent(messages, { event: 'thinking', call_id: 'call-1', delta: '先分析', done: false })
  upsertThinkingEvent(messages, { event: 'thinking', call_id: 'call-1', delta: '再生成', done: false })
  upsertThinkingEvent(messages, { event: 'thinking', call_id: 'call-1', delta: '', done: true })
  upsertThinkingEvent(messages, { event: 'thinking', call_id: 'call-1', delta: '忽略', done: false })

  assert.equal(messages.length, 1)
  assert.equal(messages[0].content, '先分析再生成')
  assert.equal(messages[0].done, true)
})

test('parallel thinking calls remain separate', () => {
  const messages = []

  upsertThinkingEvent(messages, { event: 'thinking', call_id: 'call-1', delta: 'A', done: false })
  upsertThinkingEvent(messages, { event: 'thinking', call_id: 'call-2', delta: 'B', done: false })

  assert.deepEqual(messages.map((message) => [message.call_id, message.content]), [['call-1', 'A'], ['call-2', 'B']])
})

test('disconnect closes all temporary thinking messages', () => {
  const messages = [
    { role: 'thinking', call_id: 'call-1', content: 'A', done: false },
    { role: 'assistant', content: 'keep' },
    { role: 'thinking', call_id: 'call-2', content: 'B', done: false },
  ]

  finishThinkingEvents(messages)

  assert.equal(messages[0].done, true)
  assert.equal(messages[1].done, undefined)
  assert.equal(messages[2].done, true)
})

test('tool completion closes only its matching thinking message', () => {
  const messages = [
    { role: 'thinking', call_id: 'call-1', content: 'A', done: false },
    { role: 'thinking', call_id: 'call-2', content: 'B', done: false },
  ]

  finishThinkingEvents(messages, 'call-1')

  assert.equal(messages[0].done, true)
  assert.equal(messages[1].done, false)
})

test('thinking display buffer is capped without limiting provider output', () => {
  const messages = []

  upsertThinkingEvent(messages, { event: 'thinking', call_id: 'call-1', delta: 'x'.repeat(70000) })

  assert.equal(messages[0].content.length, 65536)
})

test('successful persistence refresh keeps thinking only in live messages', () => {
  const persisted = [{ role: 'assistant', content: 'done' }]
  const live = [{ role: 'thinking', call_id: 'call-1', content: 'plan', done: true }]

  const merged = mergePersistedMessagesWithThinking(persisted, live)

  assert.deepEqual(merged, [...persisted, ...live])
  assert.equal(persisted.some(message => message.role === 'thinking'), false)
})

test('persisted assistant tool calls render as tool cards instead of ellipsis bubbles', () => {
  const persisted = [{
    role: 'assistant',
    content: '',
    tool_calls: [{ id: 'call-1', name: 'bootstrap_scaffold', result: '{"ok": true}' }],
  }]

  const displayed = normalizeAgentMessagesForDisplay(persisted)

  assert.equal(displayed.length, 1)
  assert.equal(displayed[0].role, 'tool')
  assert.equal(displayed[0].tool_calls[0].name, 'bootstrap_scaffold')
  assert.equal(displayed[0].tool_calls[0].status, 'completed')
})

test('persisted assistant messages hide DeepSeek provider reasoning blocks', () => {
  const persisted = [{
    role: 'assistant',
    content: '<think>\n<!--dify-deepseek-reasoning-->internal plan\n</think>最终答复',
  }]

  const displayed = normalizeAgentMessagesForDisplay(persisted)

  assert.deepEqual(displayed, [{ role: 'assistant', content: '最终答复' }])
})

test('persisted assistant messages preserve unmarked think tags', () => {
  const persisted = [{ role: 'assistant', content: '示例：<think>保留文本</think>' }]

  const displayed = normalizeAgentMessagesForDisplay(persisted)

  assert.deepEqual(displayed, persisted)
})

test('completed stream merge keeps persisted tool calls and temporary thinking cards', () => {
  const persisted = [{
    role: 'assistant',
    content: '',
    tool_calls: [{ id: 'call-1', name: 'bootstrap_scaffold', result: '{"ok": true}' }],
  }]
  const live = [{ role: 'thinking', call_id: 'call-1', content: 'plan', done: true }]

  const displayed = mergePersistedMessagesWithThinking(persisted, live)

  assert.deepEqual(displayed.map(message => message.role), ['tool', 'thinking'])
})

test('completed stream keeps thinking beside its tool and before the final answer', () => {
  const persisted = [
    {
      role: 'assistant',
      content: '',
      tool_calls: [{ id: 'call-1', name: 'bootstrap_scaffold', result: '{"ok": true}' }],
    },
    { role: 'assistant', content: '最终答复' },
  ]
  const live = [{ role: 'thinking', call_id: 'call-1', content: '构建过程', done: true }]

  const displayed = mergePersistedMessagesWithThinking(persisted, live)

  assert.deepEqual(displayed.map(message => message.role), ['tool', 'thinking', 'assistant'])
  assert.equal(displayed[2].content, '最终答复')
})

test('stream scroll version changes when a non-last thinking card receives a delta', () => {
  assert.equal(typeof agentEventHelpers.agentStreamScrollVersion, 'function')
  const messages = [
    { role: 'thinking', call_id: 'call-1', content: '第一段', done: false },
    { role: 'tool', content: '工具执行中' },
  ]
  const before = agentEventHelpers.agentStreamScrollVersion(messages)
  messages[0].content += '第二段'

  assert.notEqual(agentEventHelpers.agentStreamScrollVersion(messages), before)
})

test('scroll helper advances both the conversation and open thinking details', () => {
  assert.equal(typeof agentEventHelpers.scrollAgentConversationToLatest, 'function')
  const thinkingDetail = { scrollTop: 0, scrollHeight: 700 }
  const conversation = {
    scrollTop: 0,
    scrollHeight: 1200,
    querySelectorAll: () => [thinkingDetail],
  }

  agentEventHelpers.scrollAgentConversationToLatest(conversation, { scrollOuter: true })

  assert.equal(thinkingDetail.scrollTop, 700)
  assert.equal(conversation.scrollTop, 1200)
})

test('conversation auto-scroll pauses after the user moves away from the bottom', () => {
  assert.equal(typeof agentEventHelpers.isAgentConversationPinned, 'function')

  assert.equal(agentEventHelpers.isAgentConversationPinned({
    scrollHeight: 1000,
    scrollTop: 400,
    clientHeight: 400,
  }), false)
  assert.equal(agentEventHelpers.isAgentConversationPinned({
    scrollHeight: 1000,
    scrollTop: 570,
    clientHeight: 400,
  }), true)
})
