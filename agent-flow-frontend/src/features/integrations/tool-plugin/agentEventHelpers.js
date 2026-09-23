const DEEPSEEK_REASONING_BLOCK = /<think>\s*<!--dify-deepseek-reasoning-->.*?<\/think>/gis

function callIdFor(event) {
  const callId = String(event?.call_id || '').trim()
  return callId || null
}

function findToolMessage(messages, callId) {
  if (!callId)
    return null
  return messages.find((message) => message.role === 'tool'
    && message.tool_calls?.some((call) => String(call.id || call.call_id || '') === callId))
}

function findThinkingMessage(messages, callId) {
  if (!callId)
    return null
  return messages.find((message) => message.role === 'thinking' && message.call_id === callId)
}

export function upsertThinkingEvent(messages, event) {
  if (!Array.isArray(messages) || event?.event !== 'thinking')
    return
  const callId = callIdFor(event)
  if (!callId)
    return
  let message = findThinkingMessage(messages, callId)
  if (!message) {
    message = { role: 'thinking', call_id: callId, content: '', done: false }
    messages.push(message)
  }
  if (message.done)
    return
  if (event.delta)
    message.content = `${message.content}${String(event.delta)}`.slice(0, 65536)
  if (event.done === true)
    message.done = true
}

export function finishThinkingEvents(messages, callId = null) {
  if (!Array.isArray(messages))
    return
  for (const message of messages) {
    if (message.role === 'thinking' && (!callId || message.call_id === callId))
      message.done = true
  }
}

function persistedToolFailed(call) {
  if (call?.ok === false || call?.status === 'error')
    return true
  const result = call?.result || call?.summary
  if (!result)
    return false
  try {
    return JSON.parse(result)?.ok === false
  }
  catch {
    return false
  }
}

export function normalizeAgentMessagesForDisplay(messages) {
  if (!Array.isArray(messages))
    return []
  const displayed = []
  for (const message of messages) {
    const content = message?.role === 'assistant'
      ? String(message.content || '').replace(DEEPSEEK_REASONING_BLOCK, '')
      : message?.content
    const normalizedMessage = content === message?.content ? message : { ...message, content }
    const calls = normalizedMessage?.role === 'assistant' && Array.isArray(normalizedMessage.tool_calls)
      ? normalizedMessage.tool_calls
      : []
    if (!calls.length) {
      displayed.push(normalizedMessage)
      continue
    }
    if (String(normalizedMessage.content || '').trim())
      displayed.push({ role: 'assistant', content: normalizedMessage.content })
    for (const call of calls) {
      const name = call.name || call.tool || 'tool'
      const failed = persistedToolFailed(call)
      displayed.push({
        role: 'tool',
        content: failed ? `工具失败：${name}` : `工具完成：${name}`,
        tool_calls: [{
          ...call,
          name,
          tool: name,
          summary: call.summary || call.result || '',
          ok: !failed,
          status: failed ? 'error' : 'completed',
        }],
      })
    }
  }
  return displayed
}

export function mergePersistedMessagesWithThinking(persistedMessages, liveMessages) {
  const persisted = normalizeAgentMessagesForDisplay(persistedMessages)
  const thinking = Array.isArray(liveMessages)
    ? liveMessages.filter(message => message.role === 'thinking')
    : []
  const pending = [...thinking]
  const displayed = []
  for (const message of persisted) {
    displayed.push(message)
    if (message.role !== 'tool')
      continue
    const callIds = new Set((message.tool_calls || [])
      .map(call => String(call.id || call.call_id || '').trim())
      .filter(Boolean))
    if (!callIds.size)
      continue
    for (let index = 0; index < pending.length;) {
      if (callIds.has(String(pending[index].call_id || '').trim()))
        displayed.push(...pending.splice(index, 1))
      else
        index += 1
    }
  }
  return [...displayed, ...pending]
}

/**
 * A compact reactive dependency for any visible streaming text, including a
 * thinking card that is no longer the last message after a tool row appears.
 */
export function agentStreamScrollVersion(messages) {
  if (!Array.isArray(messages))
    return ''
  return messages.map((message, index) => {
    if (message?.role !== 'thinking' && message?.role !== 'assistant')
      return `${index}:${message?.role || ''}`
    return [
      index,
      message.role,
      message.call_id || '',
      String(message.content || '').length,
      message.done === true ? 1 : 0,
    ].join(':')
  }).join('|')
}

export function isAgentConversationPinned(container, threshold = 48) {
  if (!container)
    return true
  return container.scrollHeight - container.scrollTop - container.clientHeight <= threshold
}

export function scrollAgentConversationToLatest(container, { scrollOuter = true } = {}) {
  if (!container)
    return
  for (const detail of container.querySelectorAll?.('.thinking-card[open] .thinking-detail') || [])
    detail.scrollTop = detail.scrollHeight
  if (scrollOuter)
    container.scrollTop = container.scrollHeight
}

export function upsertToolEventMessage(messages, event) {
  if (!Array.isArray(messages) || !event?.event || !event.name)
    return

  const callId = callIdFor(event)
  if (event.event === 'tool_call') {
    messages.push({
      role: 'tool',
      content: `调用 ${event.name}`,
      tool_calls: [{
        id: callId || undefined,
        call_id: callId || undefined,
        name: event.name,
        tool: event.name,
        arguments: event.arguments || {},
        status: 'running',
      }],
    })
    return
  }

  if (event.event !== 'tool_result')
    return

  const message = findToolMessage(messages, callId)
  if (!message) {
    messages.push({
      role: 'tool',
      content: event.ok === false ? `工具失败：${event.name}` : `工具完成：${event.name}`,
      tool_calls: [{
        id: callId || undefined,
        call_id: callId || undefined,
        name: event.name,
        tool: event.name,
        summary: event.summary || '',
        ok: event.ok !== false,
        status: event.ok === false ? 'error' : 'completed',
      }],
    })
    return
  }

  const call = message.tool_calls.find((item) => String(item.id || item.call_id || '') === callId)
  if (!call)
    return
  call.summary = event.summary || ''
  call.ok = event.ok !== false
  call.status = event.ok === false ? 'error' : 'completed'
  message.content = event.ok === false ? `工具失败：${event.name}` : `工具完成：${event.name}`
}
