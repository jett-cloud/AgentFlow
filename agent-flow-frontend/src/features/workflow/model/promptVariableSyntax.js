/**
 * Workflow prompt variable syntax helpers.
 * Stored form: {{#nodeId.var.path#}}
 */

export const WORKFLOW_VAR_REGEX = /\{\{#(.*?)#\}\}/g

export function formatWorkflowVarToken(selector = []) {
  const parts = (selector || []).filter(Boolean)
  if (!parts.length)
    return ''
  return `{{#${parts.join('.')}#}}`
}

/**
 * Detect an open `{` trigger at caret for typeahead.
 * Returns { start, query } where start is index of `{`, query is text after it.
 */
export function detectBraceTrigger(text, caret) {
  const value = String(text || '')
  const pos = Math.max(0, Math.min(caret ?? value.length, value.length))
  const before = value.slice(0, pos)
  const match = before.match(/\{([^{}\n]{0,75})$/)
  if (!match)
    return null
  // Ignore if already starting a full {{# token
  const openIdx = before.length - match[0].length
  if (value.slice(openIdx, openIdx + 3) === '{{#')
    return null
  return {
    start: openIdx,
    query: match[1] || '',
  }
}

export function insertAtRange(text, start, end, insertion) {
  const value = String(text || '')
  const s = Math.max(0, start)
  const e = Math.max(s, end)
  return {
    text: `${value.slice(0, s)}${insertion}${value.slice(e)}`,
    caret: s + insertion.length,
  }
}

export function filterVarGroups(groups = [], query = '') {
  const q = String(query || '').trim().toLowerCase()
  if (!q)
    return groups
  return groups
    .map((group) => ({
      ...group,
      vars: (group.vars || []).filter((v) => {
        const name = String(v.variable || '').toLowerCase()
        const title = String(group.title || '').toLowerCase()
        // Also match Dify short display names (sys.query → query)
        const show = name.startsWith('sys.') ? name.slice(4) : name
        return name.includes(q)
          || show.includes(q)
          || title.includes(q)
          || `${group.nodeId}.${v.variable}`.toLowerCase().includes(q)
      }),
    }))
    .filter((group) => group.vars.length > 0)
}
