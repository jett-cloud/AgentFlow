export const QUESTION_CLASSIFIER_DEFAULTS = Object.freeze({
  query_variable_selector: [],
  model: { provider: '', name: '', mode: 'chat', completion_params: { temperature: 0.7 } },
  classes: [{ id: '1', name: '', label: 'CLASS 1' }, { id: '2', name: '', label: 'CLASS 2' }],
  _targetBranches: [{ id: '1', name: '' }, { id: '2', name: '' }],
  vision: { enabled: false },
})

export function isQuestionClassifierInput(variable = {}) {
  return variable.type === 'string'
}

export function normalizeQuestionClassifierData(data = {}) {
  const classes = Array.isArray(data.classes) && data.classes.length
    ? data.classes.map((item, index) => ({ ...item, id: String(item.id || index + 1), name: String(item.name || ''), label: item.label || `CLASS ${index + 1}` }))
    : QUESTION_CLASSIFIER_DEFAULTS.classes.map(item => ({ ...item }))
  return {
    ...data,
    query_variable_selector: Array.isArray(data.query_variable_selector) ? data.query_variable_selector.map(String) : [],
    model: { ...QUESTION_CLASSIFIER_DEFAULTS.model, ...(data.model || {}), completion_params: { ...QUESTION_CLASSIFIER_DEFAULTS.model.completion_params, ...(data.model?.completion_params || {}) } },
    classes,
    _targetBranches: classes.map(item => ({ id: item.id, name: item.name })),
    vision: { enabled: false, ...(data.vision || {}) },
  }
}
