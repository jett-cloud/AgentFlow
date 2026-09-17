/**
 * Rewrite downstream variable references when an upstream output is renamed.
 * Contrasts Dify handleOutVarRenameChange + updateNodeVars / replaceOldVarInText.
 */

function samePrefix(selector, oldSelector) {
  if (!Array.isArray(selector) || selector.length < oldSelector.length)
    return false
  return oldSelector.every((part, index) => String(selector[index]) === String(part))
}

export function rewriteSelector(selector, oldSelector, newSelector) {
  if (!samePrefix(selector, oldSelector))
    return selector
  if (!Array.isArray(newSelector) || newSelector.length === 0)
    return []
  return [...newSelector, ...selector.slice(oldSelector.length)]
}

export function rewriteVarTokens(text, oldSelector, newSelector) {
  const value = String(text || '')
  if (!value || !oldSelector?.length)
    return text
  const oldKey = oldSelector.join('.')
  if (!Array.isArray(newSelector) || newSelector.length === 0)
    return value.replaceAll(`{{#${oldKey}#}}`, '')
  const newKey = newSelector.join('.')
  return value
    .replaceAll(`{{#${oldKey}#}}`, `{{#${newKey}#}}`)
    .replaceAll(`{{#${oldKey}.`, `{{#${newKey}.`)
}

function looksLikeSelector(value) {
  return Array.isArray(value)
    && value.length >= 2
    && value.every(item => typeof item === 'string' || typeof item === 'number')
}

function rewriteValue(value, oldSelector, newSelector, key = '') {
  if (value == null)
    return value
  if (typeof value === 'string') {
    const next = rewriteVarTokens(value, oldSelector, newSelector)
    return next === value ? value : next
  }
  if (Array.isArray(value)) {
    if (looksLikeSelector(value)) {
      const current = value.map(String)
      const next = rewriteSelector(current, oldSelector, newSelector)
      if (next.join('.') !== current.join('.'))
        return next
      const keyLower = String(key || '').toLowerCase()
      if (keyLower.includes('selector') || current[0] === String(oldSelector[0]))
        return value
    }
    let changed = false
    const next = value.map((item) => {
      const rewritten = rewriteValue(item, oldSelector, newSelector, key)
      if (rewritten !== item)
        changed = true
      return rewritten
    })
    return changed ? next : value
  }
  if (typeof value === 'object') {
    let changed = false
    const next = {}
    for (const [childKey, childVal] of Object.entries(value)) {
      const rewritten = rewriteValue(childVal, oldSelector, newSelector, childKey)
      if (rewritten !== childVal)
        changed = true
      next[childKey] = rewritten
    }
    return changed ? next : value
  }
  return value
}

export function rewriteVarReferencesInNodeData(data, oldSelector, newSelector) {
  if (!data || !oldSelector?.length)
    return data
  return rewriteValue(data, oldSelector, newSelector)
}

export function listOutputVarNames(data = {}) {
  const type = data.type
  if (type === 'start' || type === 'trigger-webhook' || type === 'trigger-schedule' || type === 'trigger-plugin')
    return (Array.isArray(data.variables) ? data.variables : []).map(item => String(item?.variable || '')).filter(Boolean)
  if (type === 'code')
    return Object.keys(data.outputs && typeof data.outputs === 'object' ? data.outputs : {})
  if (type === 'parameter-extractor')
    return (Array.isArray(data.parameters) ? data.parameters : []).map(item => String(item?.name || '')).filter(Boolean)
  if (type === 'human-input') {
    return (Array.isArray(data.inputs) ? data.inputs : [])
      .map(item => String(item?.output_variable_name || item?.variable || ''))
      .filter(Boolean)
  }
  if (type === 'agent' || type === 'agent-v2') {
    return (Array.isArray(data.agent_declared_outputs) ? data.agent_declared_outputs : [])
      .map(item => String(item?.name || ''))
      .filter(Boolean)
  }
  return []
}

/**
 * Detect a single rename or delete of a user-declared output variable.
 * @returns {{ oldName: string, newName: string } | null}
 */
export function detectOutVarRename(previousData, nextData) {
  const oldNames = listOutputVarNames(previousData)
  const newNames = listOutputVarNames(nextData)
  const oldSet = new Set(oldNames)
  const newSet = new Set(newNames)
  const removed = oldNames.filter(name => !newSet.has(name))
  const added = newNames.filter(name => !oldSet.has(name))
  if (removed.length === 1 && added.length <= 1)
    return { oldName: removed[0], newName: added[0] || '' }
  return null
}

export function buildOutVarSelectors(nodeId, oldName, newName) {
  const oldSelector = [String(nodeId), String(oldName)]
  const newSelector = newName ? [String(nodeId), String(newName)] : []
  return { oldSelector, newSelector }
}
