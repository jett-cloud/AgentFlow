/**
 * Opening statement / suggested-question variable interpolation.
 * Contrasts Dify web/app/components/base/chat/chat/utils.ts processOpeningStatement.
 *
 * @param {string} openingStatement
 * @param {Record<string, unknown>} inputs
 * @param {Array<{ variable?: string, label?: string }>} inputsForm
 * @returns {string}
 */
export function processOpeningStatement(openingStatement, inputs = {}, inputsForm = []) {
  if (!openingStatement)
    return openingStatement

  return String(openingStatement).replace(/\{\{([^}]+)\}\}/g, (match, key) => {
    const name = inputs?.[key]
    if (name)
      return String(name)

    const valueObj = (Array.isArray(inputsForm) ? inputsForm : [])
      .find(v => v?.variable === key)
    if (!valueObj)
      return match

    const label = valueObj.label
    const labelText = label == null || label === ''
      ? key
      : (typeof label === 'string' ? label : String(label))
    return `{{${labelText}}}`
  })
}

/**
 * @param {string[]} questions
 * @param {Record<string, unknown>} inputs
 * @param {Array<{ variable?: string, label?: string }>} inputsForm
 * @returns {string[]}
 */
export function processOpeningSuggestedQuestions(questions, inputs = {}, inputsForm = []) {
  return (Array.isArray(questions) ? questions : [])
    .map(q => processOpeningStatement(String(q ?? ''), inputs, inputsForm))
    .filter(Boolean)
}
