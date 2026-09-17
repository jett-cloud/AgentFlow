import { assistCopy } from './assistLanguage.js'

export function assistErrorsFromAxios(error, language = 'zh-Hans') {
  const data = error?.response?.data ?? error?.data
  const errors = data?.errors ?? error?.errors
  if (Array.isArray(errors) && errors.length > 0)
    return errors

  const message = data?.message ?? error?.message
  if (message) {
    const code = data?.code || error?.code
    return [{ ...(code ? { code } : {}), detail: message }]
  }

  return [{ detail: assistCopy(language).defaultError }]
}

export function assistErrorsFromStreamEvent(ev, language = 'zh-Hans') {
  const errors = ev?.errors
  if (Array.isArray(errors) && errors.length > 0)
    return errors

  const message = ev?.message
  if (message)
    return [{ ...(ev?.code ? { code: ev.code } : {}), detail: message }]

  return [{ detail: assistCopy(language).defaultError }]
}

const FRIENDLY_ERROR_RULES = [
  {
    match: /empty model response/i,
    copyKey: 'emptyModelResponse',
  },
  {
    match: /no JSON object in response/i,
    copyKey: 'noJsonObject',
  },
  {
    match: /output truncated/i,
    copyKey: 'outputTruncated',
  },
  {
    match: /stream ended without a plan event/i,
    copyKey: 'missingPlan',
  },
]

function errorDetailText(error) {
  if (typeof error === 'string')
    return error.trim()

  const detail = error?.detail ?? error?.message
  return detail == null ? '' : String(detail).trim()
}

export function friendlyAssistError(error, language = 'zh-Hans') {
  const copy = assistCopy(language)
  const detail = errorDetailText(error)
  const rawCode = typeof error === 'object' ? String(error?.code || error?.termination_reason || '') : ''
  const code = rawCode === 'provider_error' || detail === 'provider_error' ? 'provider_error' : rawCode
  const codedText = copy.errorCodes[code]
  if (codedText)
    return { text: codedText, raw: detail }
  if (!detail)
    return { text: copy.defaultError, raw: '' }

  const rule = FRIENDLY_ERROR_RULES.find(item => item.match.test(detail))
  return { text: rule ? copy.errorRules[rule.copyKey] : detail, raw: detail }
}

export function assistStatusText(ev, language = 'zh-Hans') {
  const copy = assistCopy(language)
  const stage = ev?.stage
  if (stage === 'planning')
    return copy.planning
  if (stage === 'generating')
    return copy.generatingWorkflow
  return ev?.message || copy.processing
}

export function assistErrorAction(errors) {
  const codes = (errors || []).map(error => String(error?.code || ''))
  if (codes.some(code => code === 'PLANNER_CONTEXT_LIMIT' || code === 'OUTPUT_TRUNCATED'))
    return 'shorten_or_switch_model'
  if (codes.some(code => code === 'CLARIFICATION_ALREADY_RESOLVED' || code.startsWith('CLARIFICATION_') || code === 'INVALID_CLARIFICATION_ID'))
    return 'reload_conversation'
  if (codes.includes('PLANNING_SESSION_CONFLICT') || codes.includes('PLANNER_BUDGET_EXHAUSTED'))
    return 'reload_conversation'
  if (codes.some(code => ['PLANNER_ACTION_LIMIT', 'PLANNER_NO_PROGRESS', 'PLANNER_MISSING_PLAN', 'PLANNER_REQUIREMENT_INVALID', 'PLANNER_POLICY_DENIED', 'PLANNER_CLARIFICATION_LIMIT', 'NETWORK_ERROR', 'CONVERSATION_CHANGE_FAILED', 'provider_error'].includes(code)))
    return 'retry'

  const detail = (errors || []).map(errorDetailText).join(' ')
  if (/network|timeout|failed to fetch|connection/i.test(detail))
    return 'retry'
  return 'none'
}

export function staleApplyNotice({ applyErrors } = {}, language = 'zh-Hans') {
  const fromError = (applyErrors || []).some(error => String(error?.code || '') === 'CANDIDATE_BASE_STALE')
  if (!fromError)
    return ''
  return assistCopy(language).staleApplyNotice
}

export function recoverableAssistBlocker(errors) {
  const detail = (errors || [])
    .map(errorDetailText)
    .filter(Boolean)
    .join(' ')
  if (/(model|provider).{0,80}(api[ _-]?key|credential|unauthori[sz]ed|not configured)|api[ _-]?key.{0,80}(model|provider)/i.test(detail))
    return 'model'
  if (/(tool|plugin).{0,80}(credential|api[ _-]?key|unauthori[sz]ed|not configured)|missing credentials?/i.test(detail))
    return 'tool'
  return ''
}
