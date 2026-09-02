import test from 'node:test'
import assert from 'node:assert/strict'
import {
  applyAssistStreamEvent,
  beginAssistActivity,
  failAssistActivity,
  finalizeAssistStreamMessages,
  groupAssistTimeline,
  removeStreamingAssistMessages,
  stripAssistToolJson,
} from './assistStreamMessage.js'
import { createWorkflowAssistRunState, reduceWorkflowAssistRunEvent } from './workflowAssistRunReducer.js'

test('planning starts one running activity card', () => {
  const result = beginAssistActivity([])

  assert.deepEqual(result, [{
    role: 'assistant',
    kind: 'activity',
    status: 'running',
    stage: 'planning',
    items: [],
    streaming: true,
  }])
})

test('thought events never enter the visible message list', () => {
  const messages = beginAssistActivity([])

  assert.equal(applyAssistStreamEvent(messages, { event: 'thought', delta: 'hidden chain of thought' }), messages)
})

test('status and operation update the same activity card', () => {
  let messages = beginAssistActivity([])
  messages = applyAssistStreamEvent(messages, {
    event: 'status',
    stage: 'planning',
    message: 'Searching tools',
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'operation',
    stage: 'planning',
    action: 'search_tools',
    query: 'web search',
    count: 3,
    message: 'Found tools',
  })

  assert.equal(messages.length, 1)
  assert.equal(messages[0].kind, 'activity')
  assert.equal(messages[0].message, 'Searching tools')
  assert.deepEqual(messages[0].items, [{
    key: 'planning:search_tools:web search:',
    stage: 'planning',
    action: 'search_tools',
    query: 'web search',
    count: 3,
    node_id: null,
    message: 'Found tools',
  }])
})

test('operations are deduplicated by stable action identity and keep the latest count', () => {
  let messages = beginAssistActivity([])
  messages = applyAssistStreamEvent(messages, {
    event: 'operation',
    stage: 'planning',
    action: 'search_knowledge',
    query: 'manual',
    count: 1,
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'operation',
    stage: 'planning',
    action: 'search_knowledge',
    query: 'manual',
    count: 4,
  })

  assert.equal(messages[0].items.length, 1)
  assert.equal(messages[0].items[0].count, 4)
})

test('requirements_resolved shows count and labels without internal keys', () => {
  const messages = applyAssistStreamEvent([], {
    event: 'operation',
    stage: 'planning',
    action: 'requirements_resolved',
    count: 2,
    requirement_keys: ['rag.source', 'testset.source'],
    labels: ['RAG 数据源', '测试集来源'],
  })

  assert.equal(messages[0].items[0].message, '已理解 2 项需求：RAG 数据源、测试集来源')
  assert.doesNotMatch(JSON.stringify(messages[0].items[0]), /rag\.source|testset\.source/)
})

test('planning phase events update one activity without exposing internal ids', () => {
  let messages = beginAssistActivity([])
  messages = applyAssistStreamEvent(messages, {
    event: 'planner_thinking',
    phase: 'understanding',
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'requirements_resolved',
    action: 'requirements_resolved',
    count: 2,
    labels: ['RAG 数据源', '测试集来源'],
    requirement_keys: ['rag.source', 'testset.source'],
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'resource_resolving',
    action: 'resource_resolving',
    resource_kind: 'dataset',
    intent_id: 'internal-intent',
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'resource_bound',
    action: 'resource_bound',
    resource_kind: 'dataset',
    resource_name: 'Product docs',
    resource_id: 'dataset-internal-id',
  })

  assert.equal(messages[0].message, '正在解析资源…')
  assert.deepEqual(messages[0].items.map(item => item.message), [
    '已理解 2 项需求：RAG 数据源、测试集来源',
    '正在解析知识库资源…',
    '已绑定知识库：Product docs',
  ])
  assert.doesNotMatch(JSON.stringify(messages), /rag\.source|internal-intent|dataset-internal-id/)
})

test('finalizing removes an empty planning placeholder', () => {
  const result = finalizeAssistStreamMessages(beginAssistActivity([]))

  assert.deepEqual(result, [])
})

test('finalizing completes and collapses an activity with observable operations', () => {
  const messages = applyAssistStreamEvent(beginAssistActivity([]), {
    event: 'operation',
    action: 'search_tools',
    query: 'image',
    count: 2,
  })
  const result = finalizeAssistStreamMessages(messages)

  assert.equal(result[0].status, 'completed')
  assert.equal(result[0].collapsed, true)
  assert.equal(result[0].streaming, false)
})

test('failed activity remains visible and retryable', () => {
  const messages = applyAssistStreamEvent(beginAssistActivity([]), {
    event: 'operation',
    action: 'search_tools',
    query: 'image',
  })
  const result = failAssistActivity(messages)

  assert.equal(result[0].status, 'failed')
  assert.equal(result[0].streaming, false)
})

test('failAssistActivity keeps visible assistant text and drops empty placeholders', () => {
  const kept = failAssistActivity([
    { role: 'assistant', kind: 'assistant_text', text: '已写出一半', streaming: true },
    ...beginAssistActivity([]),
  ])
  const bubble = kept.find(message => message.kind === 'assistant_text')
  assert.equal(bubble.text, '已写出一半')
  assert.equal(bubble.streaming, false)
  assert.equal(kept.some(message => message.kind === 'activity'), false)

  const dropped = failAssistActivity([
    { role: 'assistant', kind: 'assistant_text', text: '   ', streaming: true },
    ...beginAssistActivity([]),
  ])
  assert.equal(dropped.some(message => message.kind === 'assistant_text'), false)
  assert.equal(dropped.some(message => message.kind === 'activity'), false)
})

test('failed and aborted envelopes keep nonempty assistant_text', () => {
  const started = reduceWorkflowAssistRunEvent(
    createWorkflowAssistRunState(),
    {
      event: 'message.delta',
      run_id: 'run-1',
      sequence: 1,
      data: { text: '正在创建', message_id: 'msg-1', delta_index: 0 },
    },
  )
  const failed = reduceWorkflowAssistRunEvent(started, {
    event: 'failed',
    run_id: 'run-1',
    sequence: 2,
    data: { reason: 'provider error' },
  })
  const failedBubble = failed.messages.find(message => message.kind === 'assistant_text')
  assert.equal(failedBubble.text, '正在创建')
  assert.equal(failedBubble.streaming, false)

  const aborted = reduceWorkflowAssistRunEvent(started, {
    event: 'aborted',
    run_id: 'run-1',
    sequence: 2,
    data: { reason: 'user_abort' },
  })
  const abortedBubble = aborted.messages.find(message => message.kind === 'assistant_text')
  assert.equal(abortedBubble.text, '正在创建')
  assert.equal(abortedBubble.streaming, false)
})

test('removeStreamingAssistMessages drops only the active activity', () => {
  const messages = removeStreamingAssistMessages([
    { role: 'user', text: 'hi' },
    ...beginAssistActivity([]),
    { role: 'assistant', text: 'done' },
  ])

  assert.deepEqual(messages, [
    { role: 'user', text: 'hi' },
    { role: 'assistant', text: 'done' },
  ])
})

test('tool_call and tool_result show short activity labels without dumping the graph', () => {
  let messages = beginAssistActivity([])
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_call',
    tool_call_id: 'call-1',
    name: 'build_node',
    arguments: { title: '生成答案', type: 'llm', purpose: 'create llm' },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_result',
    tool_call_id: 'call-1',
    name: 'build_node',
    ok: true,
    summary: 'ok',
    graph: { nodes: [{ id: 'n1', data: { config: { secret: 'nope' } } }], edges: [] },
  })

  assert.equal(messages[0].items[0].message, '写入节点「生成答案」')
  assert.doesNotMatch(JSON.stringify(messages), /secret|nope/)
})

test('v2 tool envelopes associate activities by tool_call_id rather than name or arrival order', () => {
  let messages = applyAssistStreamEvent([], {
    event: 'tool_call',
    data: { tool_call_id: 'call-a', name: 'build_node' },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_call',
    data: { tool_call_id: 'call-b', name: 'build_node' },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_result',
    data: { tool_call_id: 'call-b', name: 'build_node', summary: 'second' },
  })

  const items = messages.filter(message => message.kind === 'activity').flatMap(message => message.items)
  assert.deepEqual(items.map(item => ({ key: item.key, message: item.message })), [
    { key: 'tool:call-a', message: '写入节点' },
    { key: 'tool:call-b', message: '写入节点 · second' },
  ])
  assert.equal(items[0].status, 'running')
  assert.equal(items[1].status, 'done')
})

test('a tool_result updates its tool_call_id instead of the latest running activity', () => {
  let messages = applyAssistStreamEvent([], {
    event: 'tool_call',
    data: { tool_call_id: 'call-a', name: 'build_node' },
  })
  messages = applyAssistStreamEvent(messages, { event: 'turn_complete' })
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_call',
    data: { tool_call_id: 'call-b', name: 'finish' },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_result',
    data: { tool_call_id: 'call-a', name: 'build_node', summary: 'first', ok: true },
  })
  const activities = messages.filter(message => message.kind === 'activity')
  assert.equal(activities.length, 2)
  assert.deepEqual(activities[0].items.map(item => ({ key: item.key, status: item.status })), [
    { key: 'tool:call-a', status: 'done' },
  ])
  assert.deepEqual(activities[1].items.map(item => ({ key: item.key, status: item.status })), [
    { key: 'tool:call-b', status: 'running' },
  ])
})

test('message deltas append one streaming assistant bubble', () => {
  let messages = applyAssistStreamEvent([], { event: 'message', text: '已' })
  messages = applyAssistStreamEvent(messages, { event: 'message', text: '搭好' })
  const bubble = messages.find(message => message.kind === 'assistant_text')
  assert.equal(bubble.text, '已搭好')
  assert.equal(bubble.streaming, true)
})

test('v2 message.delta envelopes append their nested data to one bubble', () => {
  let messages = applyAssistStreamEvent([], { event: 'message.delta', data: { text: '已' } })
  messages = applyAssistStreamEvent(messages, { event: 'message.delta', data: { text: '搭好' } })

  assert.equal(messages.find(message => message.kind === 'assistant_text').text, '已搭好')
})

test('same message_id with delta_index 0 then 1 grows one bubble twice', () => {
  let messages = applyAssistStreamEvent([], {
    event: 'message.delta',
    data: { text: '正在', message_id: 'msg-1', delta_index: 0 },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'message.delta',
    data: { text: '创建', message_id: 'msg-1', delta_index: 1 },
  })
  const bubbles = messages.filter(message => message.kind === 'assistant_text')
  assert.equal(bubbles.length, 1)
  assert.equal(bubbles[0].text, '正在创建')
  assert.equal(bubbles[0].message_id, 'msg-1')
})

test('different message_ids create two bubbles', () => {
  let messages = applyAssistStreamEvent([], {
    event: 'message.delta',
    data: { text: '第一', message_id: 'msg-1', delta_index: 0 },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'message.delta',
    data: { text: '第二', message_id: 'msg-2', delta_index: 0 },
  })
  const bubbles = messages.filter(message => message.kind === 'assistant_text')
  assert.equal(bubbles.length, 2)
  assert.equal(bubbles[0].text, '第一')
  assert.equal(bubbles[1].text, '第二')
})

test('a later delta updates its message_id bubble instead of the last streaming text', () => {
  let messages = applyAssistStreamEvent([], {
    event: 'message.delta',
    data: { text: 'A', message_id: 'msg-1', delta_index: 0 },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'message.delta',
    data: { text: 'B', message_id: 'msg-2', delta_index: 0 },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'message.delta',
    data: { text: 'C', message_id: 'msg-1', delta_index: 1 },
  })
  const bubbles = messages.filter(message => message.kind === 'assistant_text')
  assert.deepEqual(bubbles.map(message => ({ id: message.message_id, text: message.text })), [
    { id: 'msg-1', text: 'AC' },
    { id: 'msg-2', text: 'B' },
  ])
})

test('text and tools stay in arrival order instead of dumping tools into the first activity', () => {
  let messages = beginAssistActivity([])
  messages = applyAssistStreamEvent(messages, {
    event: 'message.delta',
    data: { text: '先确认字段', message_id: 'msg-1', delta_index: 0 },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_call',
    data: { tool_call_id: 'call-a', name: 'build_node', arguments: { title: '模板转换' } },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'message.delta',
    data: { text: '画布是空的', message_id: 'msg-2', delta_index: 0 },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_call',
    data: { tool_call_id: 'call-b', name: 'build_node', arguments: { title: '开始' } },
  })

  assert.deepEqual(messages.map(message => message.kind), [
    'activity',
    'assistant_text',
    'activity',
    'assistant_text',
    'activity',
  ])
  assert.equal(messages[0].items.length, 0)
  assert.equal(messages[1].text, '先确认字段')
  assert.equal(messages[2].items[0].key, 'tool:call-a')
  assert.equal(messages[3].text, '画布是空的')
  assert.equal(messages[4].items[0].key, 'tool:call-b')
})

test('one agent turn groups interleaved text and tools into a single bubble', () => {
  let messages = beginAssistActivity([])
  messages = applyAssistStreamEvent(messages, {
    event: 'message.delta',
    data: { text: '先确认字段', message_id: 'msg-1', delta_index: 0 },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_call',
    data: { tool_call_id: 'call-a', name: 'build_node', arguments: { title: '模板转换' } },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'message.delta',
    data: { text: '画布是空的', message_id: 'msg-2', delta_index: 0 },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_call',
    data: { tool_call_id: 'call-b', name: 'build_node', arguments: { title: '开始' } },
  })
  const groups = groupAssistTimeline([
    { role: 'user', text: '生成循环工作流' },
    ...messages,
  ])

  assert.equal(groups.length, 2)
  assert.equal(groups[0].kind, 'single')
  assert.equal(groups[0].message.role, 'user')
  assert.equal(groups[1].kind, 'turn')
  assert.deepEqual(groups[1].blocks.map((block) => (
    block.kind === 'assistant_text' ? block.text : block.items[0].key
  )), [
    '先确认字段',
    'tool:call-a',
    '画布是空的',
    'tool:call-b',
  ])
})

test('English activity copy covers planning, resource, and tool progress', () => {
  let messages = applyAssistStreamEvent([], {
    event: 'status',
    data: { stage: 'planning' },
  }, 'en')
  assert.equal(messages[0].message, 'Planning…')
  messages = applyAssistStreamEvent(messages, {
    event: 'resource_resolving',
    data: { resource_kind: 'dataset' },
  }, 'en')
  assert.equal(messages[0].items[0].message, 'Resolving knowledge base resources…')
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_call',
    data: { tool_call_id: 'call-1', name: 'build_node' },
  }, 'en')
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_call',
    data: { tool_call_id: 'call-2', name: 'finish' },
  }, 'en')

  assert.deepEqual(
    messages.filter(message => message.kind === 'activity').flatMap(message => message.items || []).map(item => item.message),
    [
      'Resolving knowledge base resources…',
      'Write node',
      'Finish validation',
    ],
  )
})

test('done completion bubble shows summary, diff, and validation', () => {
  const messages = applyAssistStreamEvent([], {
    event: 'done',
    summary: '已搭好 RAG 测试工作流',
    diff: { added: ['n1'], removed: [], updated: ['n2'] },
    validation: { ok: true, errors: [] },
  })
  const completion = messages.find(message => message.kind === 'completion')
  assert.equal(completion.summary, '已搭好 RAG 测试工作流')
  assert.deepEqual(completion.diff.added, ['n1'])
  assert.equal(completion.validation.ok, true)
})

test('connect labels keep source and target after a generic ok result', () => {
  let messages = applyAssistStreamEvent([], {
    event: 'tool_call',
    tool_call_id: 'call-c',
    name: 'connect',
    arguments: { source: 'start', target: 'kb_retrieval' },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_result',
    tool_call_id: 'call-c',
    name: 'connect',
    ok: true,
    summary: 'ok',
  })
  assert.equal(messages[0].items[0].message, '连线 start → kb_retrieval')
})

test('embedded tool-call JSON is stripped from assistant prose', () => {
  const raw = [
    '先创建起始节点。',
    '{"id":"call_00_abc","name":"build_node","arguments":{"mode":"create","id":"end","type":"end"}}',
    '链路已连通。',
  ].join('\n')
  assert.equal(stripAssistToolJson(raw), '先创建起始节点。\n\n链路已连通。')
  const messages = applyAssistStreamEvent([], {
    event: 'message',
    text: raw,
  })
  assert.equal(messages[0].text, '先创建起始节点。\n\n链路已连通。')
  assert.doesNotMatch(messages[0].text, /build_node/)
})

test('a message that is only a tool-call JSON object is omitted', () => {
  const messages = applyAssistStreamEvent([], {
    event: 'message',
    text: '{"id":"call_1","name":"validate_graph","arguments":{}}',
  })
  assert.equal(messages.length, 0)
})

test('three tool_call events before any tool_result show three concurrently running steps', () => {
  let messages = applyAssistStreamEvent([], {
    event: 'tool_call',
    data: { tool_call_id: 'call-a', name: 'build_node' },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_call',
    data: { tool_call_id: 'call-b', name: 'build_node' },
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'tool_call',
    data: { tool_call_id: 'call-c', name: 'build_node' },
  })

  const items = messages.filter(message => message.kind === 'activity').flatMap(message => message.items || [])
  assert.equal(items.filter(step => step.status === 'running').length, 3)
  assert.deepEqual(items.map(item => item.key), ['tool:call-a', 'tool:call-b', 'tool:call-c'])
})

test('candidate.updated does not dump the graph into bubbles', () => {
  const before = applyAssistStreamEvent([], {
    event: 'tool_call',
    data: { tool_call_id: 'call-a', name: 'build_node' },
  })
  const after = applyAssistStreamEvent(before, {
    event: 'candidate.updated',
    data: {
      revision: 4,
      graph: { nodes: [{ id: 'secret-node', data: { title: 'should-not-appear' } }], edges: [] },
    },
  })

  assert.equal(after, before)
  assert.equal(JSON.stringify(after).includes('secret-node'), false)
  assert.equal(JSON.stringify(after).includes('should-not-appear'), false)
})

test('the same run_id and sequence does not double already-applied text', () => {
  const envelope = {
    event: 'message.delta',
    run_id: 'run-1',
    sequence: 3,
    data: { text: 'hello', message_id: 'msg-1', delta_index: 0 },
  }
  let state = reduceWorkflowAssistRunEvent(createWorkflowAssistRunState(), envelope)
  state = reduceWorkflowAssistRunEvent(state, envelope)
  const bubbles = state.messages.filter(message => message.kind === 'assistant_text')
  assert.equal(bubbles.length, 1)
  assert.equal(bubbles[0].text, 'hello')
})

test('reasoning.delta is captured on the same assistant bubble and stays out of public text', () => {
  let messages = applyAssistStreamEvent([], {
    event: 'reasoning.delta',
    text: '先读图',
    message_id: 'msg-1',
  })
  messages = applyAssistStreamEvent(messages, {
    event: 'message.delta',
    text: '开始改',
    message_id: 'msg-1',
  })
  messages = finalizeAssistStreamMessages(messages)

  assert.equal(messages.length, 1)
  assert.equal(messages[0].text, '开始改')
  assert.equal(messages[0].reasoning, '先读图')
  assert.equal(messages[0].reasoningStreaming, false)
  assert.equal(messages[0].streaming, false)
})

test('empty reasoning.delta does not render a thought bubble', () => {
  const messages = applyAssistStreamEvent([], {
    event: 'reasoning.delta',
    text: '',
    message_id: 'msg-1',
  })
  assert.equal(messages.length, 0)
})
