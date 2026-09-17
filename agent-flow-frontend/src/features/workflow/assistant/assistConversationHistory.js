import {
  applyAssistStreamEvent,
  beginAssistActivity,
  failAssistActivity,
  finalizeAssistStreamMessages,
} from './assistStreamMessage.js'
import { abortStatusText } from './assistStateMachine.js'

function uniqueRecords(records) {
  const seenIds = new Set()
  return (Array.isArray(records) ? records : []).filter((record) => {
    const id = String(record?.id || '')
    if (!id)
      return true
    if (seenIds.has(id))
      return false
    seenIds.add(id)
    return true
  })
}

function userMessages(record, payload) {
  if (record?.event_type === 'clarification_answer') {
    const answers = (payload.answers || [])
      .map((answer) => {
        if (Array.isArray(answer?.labels) && answer.labels.length)
          return answer.labels.join('、')
        if (answer?.kind === 'text')
          return answer.text || ''
        return answer?.other_text || answer?.value || answer?.selected_value || ''
      })
      .filter(Boolean)
    if (!answers.length)
      return []
    const clarificationId = payload.clarification_id || record.id
    return [{
      role: 'user',
      text: answers.join('；'),
      turnKey: `clarification-answer:${clarificationId}`,
      delivery: 'delivered',
    }]
  }
  const text = String(payload.text || payload.message || payload.instruction || record?.text || '')
  const references = Array.isArray(payload.references) ? payload.references : []
  if (!text)
    return []
  return [{
    role: 'user',
    text,
    ...(references.length ? { references } : {}),
    turnKey: record?.id ? `message:${record.id}` : undefined,
  }]
}

function assistantEventMessages(events, failed, language) {
  let activity = []
  const plans = []
  const replies = []
  const eventList = Array.isArray(events) ? events : []
  for (const event of eventList) {
    if ([
      'operation',
      'planner_thinking',
      'requirements_resolved',
      'turn_interpreted',
      'resource_resolving',
      'resource_bound',
      'tool_call',
      'tool_result',
      'message',
      'message.delta',
      'reasoning.delta',
    ].includes(event?.event)) {
      if (!activity.length)
        activity = beginAssistActivity([])
      activity = applyAssistStreamEvent(activity, event, language)
    }
    else if (event?.event === 'plan') {
      const { event: _event, ...plan } = event
      plans.push({ role: 'assistant', kind: 'plan_summary', plan })
    }
    else if (event?.event === 'assistant_message' && event.message) {
      replies.push({ role: 'assistant', text: String(event.message) })
    }
    else if (event?.event === 'waiting_user') {
      replies.push({
        role: 'assistant',
        kind: 'clarification',
        clarification: {
          clarification_id: event.tool_call_id,
          questions: event.questions || [],
        },
        status: 'pending',
        resolved: false,
      })
    }
    else if (event?.event === 'aborted') {
      replies.push({
        role: 'assistant',
        kind: 'status',
        text: abortStatusText(event.termination_reason, language),
      })
    }
    else if (event?.event === 'done') {
      replies.push({
        role: 'assistant',
        kind: 'completion',
        summary: event.summary || '',
        diff: event.diff || { added: [], removed: [], updated: [] },
        validation: event.validation || { ok: false, errors: [] },
      })
    }
    else if (event?.event === 'failed') {
      replies.push({
        role: 'assistant',
        kind: 'status',
        text: String(event.reason || ''),
      })
    }
  }
  if (failed) {
    if (!activity.length)
      activity = beginAssistActivity([])
    let error = null
    for (let index = eventList.length - 1; index >= 0; index -= 1) {
      if (eventList[index]?.event === 'error') {
        error = eventList[index]
        break
      }
    }
    if (error?.message) {
      activity = applyAssistStreamEvent(activity, {
        event: 'status',
        message: error.message,
      }, language)
    }
    const failedMessages = failAssistActivity(activity)
    if (failedMessages.length)
      return [...failedMessages, ...replies, ...plans]
    return [{
      role: 'assistant',
      kind: 'activity',
      status: 'failed',
      message: String(error?.message || ''),
      items: [],
      collapsed: false,
      streaming: false,
    }, ...replies, ...plans]
  }
  return [...finalizeAssistStreamMessages(activity), ...replies, ...plans]
}

function semanticMessageKey(message) {
  if (message?.turnKey?.startsWith('clarification-answer:'))
    return message.turnKey
  if (message?.role === 'user')
    return message.turnKey || `user:${String(message.text || '').trim()}`
  if (message?.kind === 'clarification')
    return `clarification:${message.clarification?.clarification_id || ''}`
  if (message?.kind === 'activity')
    return `activity:${(message.items || []).map(item => item.key || JSON.stringify(item)).join('|')}`
  if (message?.kind === 'plan_summary') {
    const plan = message.plan || {}
    return `plan:${JSON.stringify({
      title: plan.app_name || plan.title || '',
      summary: plan.summary || plan.description || '',
      mode: plan.mode || '',
      nodes: plan.nodes || [],
      edges: plan.edges || [],
      resources: plan.resource_requests || [],
    })}`
  }
  return ''
}

function deduplicateMessages(messages) {
  const seen = new Set()
  return messages.filter((message) => {
    const key = semanticMessageKey(message)
    if (!key || !seen.has(key)) {
      if (key)
        seen.add(key)
      return true
    }
    return false
  })
}

function appendHistoryRecord(messages, record, pendingClarification, language) {
  const payload = record?.payload || {}
  if (record?.role === 'user')
    return [...messages, ...userMessages(record, payload)]
  if (record?.event_type === 'clarification') {
    const pending = pendingClarification?.clarification_id === payload.clarification_id
    return [...messages, {
      role: 'assistant',
      kind: 'clarification',
      clarification: payload,
      status: pending ? 'pending' : 'resolved',
      resolved: !pending,
    }]
  }
  if (record?.event_type === 'tool_call' && payload.name === 'ask_user' && record.status === 'pending') {
    return [...messages, {
      role: 'assistant',
      kind: 'clarification',
      clarification: {
        clarification_id: payload.id || record.id,
        questions: payload.arguments?.questions || payload.questions || [],
      },
      status: 'pending',
      resolved: false,
    }]
  }
  if (record?.event_type === 'tool_call' && payload.name !== 'ask_user') {
    return applyAssistStreamEvent(messages, {
      event: 'tool_call',
      tool_call_id: payload.id || payload.tool_call_id,
      name: payload.name,
      arguments: payload.arguments && typeof payload.arguments === 'object' ? payload.arguments : {},
    }, language, { mode: 'hydrate' })
  }
  if (record?.event_type === 'tool_result') {
    const content = payload.content
    const summary = typeof content === 'string'
      ? content
      : (content && typeof content === 'object' ? String(content.summary || content.message || '') : '')
    return applyAssistStreamEvent(messages, {
      event: 'tool_result',
      tool_call_id: payload.tool_call_id,
      name: payload.name,
      ok: payload.ok,
      error: payload.error,
      summary,
    }, language, { mode: 'hydrate' })
  }
  if (record?.event_type === 'message' && record?.role === 'assistant') {
    const text = String(payload.text || payload.message || '')
    const reasoning = String(payload.reasoning || '')
    if (!text && !reasoning)
      return messages
    return [...messages, {
      role: 'assistant',
      kind: 'assistant_text',
      text,
      reasoning,
      message_id: payload.message_id || record.id,
      streaming: false,
      turnKey: record?.id ? `message:${record.id}` : undefined,
    }]
  }
  const events = Array.isArray(payload.events) ? payload.events : []
  const failed = record?.status === 'failed' || events.some(event => event?.event === 'error')
  return [...messages, ...assistantEventMessages(events, failed, language)]
}

export function buildAssistHistoryMessages(records, pendingClarification = null, language = 'zh-Hans') {
  let messages = []
  for (const record of uniqueRecords(records))
    messages = appendHistoryRecord(messages, record, pendingClarification, language)
  return deduplicateMessages(finalizeAssistStreamMessages(messages))
}

export function formatAssistConversationTimestamp(value, language = 'zh-Hans') {
  const date = new Date(value)
  if (!value || Number.isNaN(date.getTime()))
    return ''
  return new Intl.DateTimeFormat(language === 'zh-Hans' ? 'zh-CN' : 'en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}
