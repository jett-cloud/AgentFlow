import { assistStatusText } from './assistErrors.js'
import { assistCopy, formatAssistCopy, formatAssistToolActivity } from './assistLanguage.js'

function findRunningActivity(messages) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message?.role === 'assistant' && message.kind === 'activity' && message.status === 'running')
      return index
  }
  return -1
}

function findStreamingText(messages) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message?.role === 'assistant' && message.kind === 'assistant_text' && message.streaming)
      return index
  }
  return -1
}

function findLastAssistantText(messages) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message?.role === 'assistant' && message.kind === 'assistant_text')
      return index
  }
  return -1
}

function findTextByMessageId(messages, messageId) {
  if (!messageId)
    return -1
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message?.role === 'assistant' && message.kind === 'assistant_text' && message.message_id === messageId)
      return index
  }
  return -1
}

function operationKey(event) {
  if (event?.event === 'operation') {
    return [
      event?.stage || '',
      event?.action || '',
      event?.query || '',
      event?.node_id || '',
    ].join(':')
  }
  return [
    event?.event || '',
    event?.stage || '',
    event?.action || '',
    event?.query || '',
    event?.node_id || '',
    event?.resource_kind || '',
    event?.resource_name || '',
  ].join(':')
}

function requirementProgressMessage(event, language) {
  if (event?.event !== 'requirements_resolved' && event?.action !== 'requirements_resolved')
    return ''
  const labels = (Array.isArray(event.labels) ? event.labels : [])
    .map(label => String(label || '').trim())
    .filter(Boolean)
  const count = Number.isFinite(event.count) ? event.count : labels.length
  const copy = assistCopy(language)
  const suffix = labels.length
    ? `${copy.requirementLabelsPrefix}${labels.join(copy.requirementLabelsSeparator)}`
    : ''
  return formatAssistCopy(copy.understoodRequirements, { count, suffix })
}

function phaseStatusText(event, language) {
  const copy = assistCopy(language)
  if (event?.event === 'resource_resolving' || event?.phase === 'resolving_resource')
    return copy.resolvingResources
  if (event?.phase === 'understanding')
    return copy.understandingRequirements
  if (event?.phase === 'ready')
    return copy.generatingStructure
  if (event?.phase === 'waiting_user')
    return copy.waitingForInformation
  return event?.message || copy.planning
}

function resourceLabel(kind, language) {
  const labels = assistCopy(language).resourceLabels
  return labels[kind] || labels.resource
}

function phaseEventMessage(event, language) {
  const copy = assistCopy(language)
  if (event?.event === 'requirements_resolved' || event?.action === 'requirements_resolved')
    return requirementProgressMessage(event, language)
  if (event?.event === 'turn_interpreted')
    return copy.understoodCurrentRequest
  if (event?.event === 'resource_resolving')
    return formatAssistCopy(copy.resolvingResource, {
      resource: resourceLabel(event.resource_kind, language),
    })
  if (event?.event === 'resource_bound')
    return formatAssistCopy(copy.boundResource, {
      resource: resourceLabel(event.resource_kind, language),
      name: event.resource_name || copy.availableResource,
    })
  return event?.message || ''
}

function isToolCallObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    return false
  const name = typeof value.name === 'string' ? value.name.trim() : ''
  if (name && value.arguments != null)
    return true
  const id = typeof value.id === 'string' ? value.id : ''
  return Boolean(name && /^call[_-]/i.test(id))
}

function matchingBrace(text, start) {
  let depth = 0
  let inString = false
  let escaped = false
  for (let index = start; index < text.length; index += 1) {
    const char = text[index]
    if (inString) {
      if (escaped)
        escaped = false
      else if (char === '\\')
        escaped = true
      else if (char === '"')
        inString = false
      continue
    }
    if (char === '"') {
      inString = true
      continue
    }
    if (char === '{')
      depth += 1
    else if (char === '}') {
      depth -= 1
      if (depth === 0)
        return index
    }
  }
  return -1
}

export function stripAssistToolJson(text) {
  const source = String(text || '')
  let output = ''
  let cursor = 0
  while (cursor < source.length) {
    const start = source.indexOf('{', cursor)
    if (start < 0) {
      output += source.slice(cursor)
      break
    }
    output += source.slice(cursor, start)
    const end = matchingBrace(source, start)
    if (end < 0) {
      output += source.slice(start)
      break
    }
    const slice = source.slice(start, end + 1)
    try {
      const parsed = JSON.parse(slice)
      if (!isToolCallObject(parsed))
        output += slice
    }
    catch {
      output += slice
    }
    cursor = end + 1
  }
  return output.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim()
}

function createToolItem(event, previous, language, key, toolCallId) {
  const args = (event.arguments && typeof event.arguments === 'object' && !Array.isArray(event.arguments))
    ? event.arguments
    : (previous?.arguments || {})
  const name = event.name || previous?.action || ''
  return {
    key,
    tool_call_id: toolCallId || previous?.tool_call_id || '',
    action: name,
    arguments: args,
    status: event.event === 'tool_result'
      ? (event.ok === false ? 'failed' : 'done')
      : 'running',
    message: formatAssistToolActivity(
      { ...event, name, arguments: args },
      previous,
      language,
    ),
  }
}

function findToolItemLocation(messages, key) {
  if (!key)
    return null
  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const message = messages[messageIndex]
    if (message?.kind !== 'activity' && message?.kind !== 'operations')
      continue
    const itemIndex = (message.items || []).findIndex(item => item.key === key)
    if (itemIndex >= 0)
      return { messageIndex, itemIndex }
  }
  return null
}

function updateRunningActivity(messages, update) {
  const next = [...messages]
  let index = findRunningActivity(next)
  if (index < 0) {
    next.push(beginAssistActivity([])[0])
    index = next.length - 1
  }
  next[index] = update(next[index])
  return next
}

export function beginAssistActivity(messages, stage = 'planning') {
  const current = Array.isArray(messages) ? messages : []
  if (findRunningActivity(current) >= 0)
    return current
  return [...current, {
    role: 'assistant',
    kind: 'activity',
    status: 'running',
    stage,
    items: [],
    streaming: true,
  }]
}

export function normalizeAssistStreamEvent(input) {
  const event = input && typeof input === 'object' ? input : {}
  const data = event.data && typeof event.data === 'object' ? event.data : {}
  return {
    ...data,
    ...event,
    event: event.event === 'message.delta' ? 'message' : event.event,
  }
}

function upsertAssistantText(messages, patch) {
  const next = [...(Array.isArray(messages) ? messages : [])]
  const hydrate = Boolean(patch.hydrate)
  const messageId = patch.messageId || ''
  const index = messageId
    ? findTextByMessageId(next, messageId)
    : (hydrate ? findLastAssistantText(next) : findStreamingText(next))
  const incomingText = patch.textDelta == null ? null : String(patch.textDelta)
  const incomingReasoning = patch.reasoningDelta == null ? null : String(patch.reasoningDelta)
  if (index >= 0) {
    const current = next[index]
    const text = incomingText == null
      ? String(current.text || '')
      : stripAssistToolJson(`${current.text || ''}${incomingText}`)
    const reasoning = incomingReasoning == null
      ? String(current.reasoning || '')
      : `${current.reasoning || ''}${incomingReasoning}`
    if (!text && !reasoning) {
      next.splice(index, 1)
      return next
    }
    next[index] = {
      ...current,
      kind: 'assistant_text',
      text,
      reasoning,
      streaming: hydrate ? false : true,
      reasoningStreaming: hydrate ? false : (incomingReasoning != null ? true : Boolean(current.reasoningStreaming)),
      ...(messageId ? { message_id: messageId } : {}),
    }
    return next
  }
  const text = incomingText == null ? '' : stripAssistToolJson(incomingText)
  const reasoning = incomingReasoning == null ? '' : incomingReasoning
  if (!text && !reasoning)
    return next
  next.push({
    role: 'assistant',
    kind: 'assistant_text',
    text,
    reasoning,
    streaming: hydrate ? false : true,
    reasoningStreaming: hydrate ? false : Boolean(reasoning),
    ...(messageId ? { message_id: messageId } : {}),
  })
  return next
}

export function applyAssistStreamEvent(messages, input, language = 'zh-Hans', options = {}) {
  const event = normalizeAssistStreamEvent(input)
  const hydrate = options.mode === 'hydrate'
  if (!event?.event || event.event === 'thought')
    return messages

  if (event.event === 'status') {
    return updateRunningActivity(messages, activity => ({
      ...activity,
      stage: event.stage || activity.stage,
      message: event.message || assistStatusText(event, language),
    }))
  }

  if (event.event === 'planner_thinking') {
    return updateRunningActivity(messages, activity => ({
      ...activity,
      stage: event.phase || activity.stage,
      message: phaseStatusText(event, language),
    }))
  }

  const phaseEvents = new Set([
    'requirements_resolved',
    'turn_interpreted',
    'resource_resolving',
    'resource_bound',
  ])
  if (event.event === 'operation' || phaseEvents.has(event.event)) {
    const key = operationKey(event)
    const item = {
      key,
      stage: event.stage || '',
      action: event.action || '',
      query: event.query || '',
      count: Number.isFinite(event.count) ? event.count : null,
      node_id: event.node_id ?? null,
      message: phaseEventMessage(event, language),
    }
    if (event.event !== 'operation') {
      item.resource_kind = event.resource_kind || ''
      item.resource_name = event.resource_name || ''
    }
    return updateRunningActivity(messages, (activity) => {
      const items = [...(activity.items || [])]
      const existingIndex = items.findIndex(existing => existing.key === key)
      if (existingIndex >= 0)
        items[existingIndex] = item
      else
        items.push(item)
      return {
        ...activity,
        stage: event.stage || activity.stage,
        message: event.event === 'resource_resolving'
          ? phaseStatusText(event, language)
          : activity.message,
        items,
      }
    })
  }

  if (event.event === 'tool_call' || event.event === 'tool_result') {
    const toolCallId = String(event.tool_call_id || '').trim()
    const key = toolCallId ? `tool:${toolCallId}` : ''
    const existing = findToolItemLocation(messages, key)
    if (existing) {
      const next = [...messages]
      const activity = next[existing.messageIndex]
      const items = [...(activity.items || [])]
      const previous = items[existing.itemIndex]
      const item = createToolItem(event, previous, language, key || previous.key, toolCallId)
      items[existing.itemIndex] = { ...previous, ...item }
      next[existing.messageIndex] = {
        ...activity,
        message: item.message || activity.message,
        items,
      }
      return next
    }
    const item = createToolItem(event, null, language, key || 'tool:anon:0', toolCallId)
    const current = Array.isArray(messages) ? messages : []
    const lastIndex = current.length - 1
    const last = lastIndex >= 0 ? current[lastIndex] : null
    if (last?.kind === 'activity' && last.status === 'running' && !(last.items || []).length) {
      const next = [...current]
      next[lastIndex] = {
        ...last,
        status: item.status === 'failed' ? 'failed' : 'running',
        items: [item],
        streaming: hydrate ? false : true,
        message: item.message,
      }
      return next
    }
    return [...current, {
      role: 'assistant',
      kind: 'activity',
      status: item.status === 'failed' ? 'failed' : 'running',
      items: [item],
      streaming: hydrate ? false : true,
      message: item.message,
    }]
  }

  if (event.event === 'reasoning.delta') {
    const messageId = event.message_id != null && String(event.message_id).trim()
      ? String(event.message_id)
      : ''
    const incoming = String(event.text || event.delta || '')
    if (!incoming)
      return messages
    return upsertAssistantText(messages, { messageId, reasoningDelta: incoming, hydrate })
  }

  if (event.event === 'message') {
    const messageId = event.message_id != null && String(event.message_id).trim()
      ? String(event.message_id)
      : ''
    const incoming = String(event.text || event.delta || '')
    return upsertAssistantText(messages, { messageId, textDelta: incoming, hydrate })
  }

  if (event.event === 'done') {
    const finalized = finalizeAssistStreamMessages(messages).map((message) => {
      if (message?.kind === 'assistant_text')
        return { ...message, streaming: false, reasoningStreaming: false }
      return message
    })
    return [...finalized, {
      role: 'assistant',
      kind: 'completion',
      summary: event.summary || '',
      diff: event.diff || { added: [], removed: [], updated: [] },
      validation: event.validation || { ok: false, errors: [] },
    }]
  }

  if (event.event === 'turn_complete')
    return finalizeAssistStreamMessages(messages)

  if (event.event === 'candidate.updated')
    return messages

  return messages
}

export function removeStreamingAssistMessages(messages) {
  return (Array.isArray(messages) ? messages : [])
    .filter(message => !(message?.role === 'assistant' && message.streaming))
}

const TURN_BLOCK_KINDS = new Set(['assistant_text', 'activity', 'operations', 'completion'])

function isEmptyActivity(message) {
  return (message?.kind === 'activity' || message?.kind === 'operations')
    && !(message.items || []).length
}

export function groupAssistTimeline(messages) {
  const groups = []
  for (const message of Array.isArray(messages) ? messages : []) {
    if (message?.role === 'user' || message?.kind === 'clarification' || message?.kind === 'status') {
      groups.push({ kind: 'single', message })
      continue
    }
    if (TURN_BLOCK_KINDS.has(message?.kind)) {
      if (isEmptyActivity(message))
        continue
      const last = groups[groups.length - 1]
      if (last?.kind === 'turn')
        last.blocks.push(message)
      else
        groups.push({ kind: 'turn', blocks: [message] })
      continue
    }
    groups.push({ kind: 'single', message })
  }
  return groups
}

export function finalizeAssistStreamMessages(messages) {
  return (Array.isArray(messages) ? messages : []).flatMap((message) => {
    if (message?.kind === 'assistant_text' && message.streaming)
      return [{ ...message, streaming: false, reasoningStreaming: false }]
    if (message?.kind !== 'activity' || message.status !== 'running')
      return [message]
    if (!(message.items || []).length)
      return []
    return [{
      ...message,
      status: 'completed',
      collapsed: true,
      streaming: false,
    }]
  })
}

export function appendAssistStatusMessage(messages, text) {
  const statusText = String(text || '').trim()
  if (!statusText)
    return Array.isArray(messages) ? messages : []
  return [...(Array.isArray(messages) ? messages : []), {
    role: 'assistant',
    kind: 'status',
    text: statusText,
  }]
}

export function failAssistActivity(messages) {
  return (Array.isArray(messages) ? messages : []).flatMap((message) => {
    if (message?.kind === 'assistant_text') {
      if (!String(message.text || '').trim() && !String(message.reasoning || '').trim())
        return []
      return [{ ...message, streaming: false, reasoningStreaming: false }]
    }
    if (message?.kind !== 'activity' || message.status !== 'running')
      return [message]
    if (!(message.items || []).length)
      return []
    return [{
      ...message,
      status: 'failed',
      collapsed: false,
      streaming: false,
    }]
  })
}
