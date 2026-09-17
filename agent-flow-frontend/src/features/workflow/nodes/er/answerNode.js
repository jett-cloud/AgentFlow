import { AppMode } from '../../model/appModes.js'

export const ANSWER_DEFAULTS = {
  variables: [],
  answer: '',
}

export function normalizeAnswerNodeData(data = {}) {
  return {
    ...data,
    type: 'answer',
    variables: Array.isArray(data.variables) ? data.variables : [],
    answer: String(data.answer ?? ''),
  }
}

export function isAnswerAllowedInMode(mode) {
  return mode === AppMode.ADVANCED_CHAT
}

export function isAnswerVariableSupported(variable) {
  return variable?.type !== 'arrayObject'
}

export function getAnswerValidationErrors(data = {}) {
  return normalizeAnswerNodeData(data).answer.trim() ? [] : ['请填写回复内容']
}
