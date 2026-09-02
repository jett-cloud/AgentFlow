function trimmedText(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function labelsText(labels) {
  if (!Array.isArray(labels))
    return ''

  return labels.map(trimmedText).filter(Boolean).join('、')
}

function answerText(answer) {
  return labelsText(answer?.labels)
    || trimmedText(answer?.text)
    || trimmedText(answer?.other_text)
    || trimmedText(answer?.value)
    || trimmedText(answer?.selected_value)
}

export function clarificationAnswerText(answers) {
  if (!Array.isArray(answers))
    return ''

  return answers
    .map(answerText)
    .filter(Boolean)
    .join('\n')
}

export function questionOptions(question) {
  return Array.isArray(question?.options) ? question.options.filter(option => option && (option.value || option.label)) : []
}

export function isChoiceQuestion(question) {
  const kind = question?.kind
  return (kind === 'single_choice' || kind === 'multi_choice' || kind === 'select' || kind === 'resource_select')
    && questionOptions(question).length > 0
}

export function optionValue(option) {
  return String(option?.value || option?.label || '').trim()
}

export function optionLabel(option) {
  return String(option?.label || option?.value || '').trim()
}

export function shouldSubmitOnChipClick(questions, question) {
  return Array.isArray(questions)
    && questions.length === 1
    && question?.kind === 'single_choice'
    && questionOptions(question).length > 0
}

export function emptyClarificationDraft(question) {
  return { selected: [], other: '' }
}

export function toggleClarificationOption(draft, question, value) {
  const current = draft?.[question.id] || emptyClarificationDraft(question)
  const selected = Array.isArray(current.selected) ? [...current.selected] : []
  if (question?.kind === 'multi_choice') {
    const index = selected.indexOf(value)
    if (index >= 0)
      selected.splice(index, 1)
    else
      selected.push(value)
  }
  else {
    selected.splice(0, selected.length, value)
  }
  return {
    ...draft,
    [question.id]: { ...current, selected },
  }
}

export function buildClarificationAnswers(questions, draft = {}) {
  return (Array.isArray(questions) ? questions : []).map((question) => {
    const state = draft[question.id] || emptyClarificationDraft(question)
    const selected = Array.isArray(state.selected) ? state.selected.filter(Boolean) : []
    const other = trimmedText(state.other)
    const labels = selected.map((value) => {
      const match = questionOptions(question).find(option => optionValue(option) === value)
      return match ? optionLabel(match) : value
    })
    if (isChoiceQuestion(question)) {
      const kind = question.kind === 'multi_choice' ? 'multi_choice' : 'single_choice'
      return {
        question_id: question.id,
        kind,
        labels,
        other_text: other,
        text: [...labels, other].filter(Boolean).join('、'),
      }
    }
    return {
      question_id: question.id,
      kind: 'text',
      text: other || selected[0] || '',
      other_text: other,
    }
  }).filter(answer => answerText(answer))
}

export function canSubmitClarification(questions, draft = {}) {
  return buildClarificationAnswers(questions, draft).length > 0
}
