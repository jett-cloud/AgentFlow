/**
 * Think-tag preprocess + segment split for Markdown.
 * Contrasts Dify markdown-utils preprocessThinkTag + ThinkBlock.
 */

export const END_THINK_FLAG = '[ENDTHINKFLAG]'

/**
 * @param {string} content
 * @returns {string}
 */
export function preprocessThinkTag(content) {
  if (typeof content !== 'string')
    return ''
  const thinkOpenTagRegex = /(<think>\s*)+/g
  const thinkCloseTagRegex = /(\s*<\/think>)+/g
  return content
    .replace(thinkOpenTagRegex, '<details data-think=true>\n')
    .replace(thinkCloseTagRegex, `\n${END_THINK_FLAG}</details>`)
    .replace(/(<\/details>)(?![^\S\r\n]*[\r\n])(?![^\S\r\n]*$)/g, '$1\n')
}

/**
 * @param {string} preprocessed
 * @returns {Array<{ type: 'md' | 'think', text: string, complete: boolean }>}
 */
export function splitThinkSegments(preprocessed) {
  const source = String(preprocessed || '')
  if (!source)
    return []

  /** @type {Array<{ type: 'md' | 'think', text: string, complete: boolean }>} */
  const parts = []
  const openTag = '<details data-think=true>'
  let cursor = 0

  while (cursor < source.length) {
    const openIdx = source.indexOf(openTag, cursor)
    if (openIdx === -1) {
      parts.push({ type: 'md', text: source.slice(cursor), complete: true })
      break
    }
    if (openIdx > cursor)
      parts.push({ type: 'md', text: source.slice(cursor, openIdx), complete: true })

    const bodyStart = openIdx + openTag.length
    // Skip optional leading newline from preprocess.
    const contentStart = source[bodyStart] === '\n' ? bodyStart + 1 : bodyStart
    const closeIdx = source.indexOf('</details>', contentStart)
    if (closeIdx === -1) {
      parts.push({
        type: 'think',
        text: source.slice(contentStart),
        complete: false,
      })
      break
    }
    parts.push({
      type: 'think',
      text: source.slice(contentStart, closeIdx),
      complete: true,
    })
    cursor = closeIdx + '</details>'.length
  }

  return parts.filter(part => part.text.length > 0 || part.type === 'think')
}

/**
 * @param {string} thinkBody
 * @returns {{ body: string, hasEndFlag: boolean }}
 */
export function stripEndThinkFlag(thinkBody) {
  const text = String(thinkBody || '')
  return {
    hasEndFlag: text.includes(END_THINK_FLAG),
    body: text.replace(/\[ENDTHINKFLAG\]/g, ''),
  }
}

/**
 * @param {{ complete?: boolean, hasEndFlag?: boolean, isResponding?: boolean }} args
 * @returns {boolean}
 */
export function isThinkBlockComplete({ hasEndFlag = false, isResponding = false } = {}) {
  // Contrasts Dify useThinkTimer: end flag OR response no longer active.
  return Boolean(hasEndFlag || !isResponding)
}

/**
 * Build safe HTML shell for a think segment (inner body already markdown-rendered).
 * @param {{ bodyHtml: string, isComplete: boolean }} args
 * @returns {string}
 */
export function renderThinkBlockHtml({ bodyHtml, isComplete }) {
  const label = isComplete ? '已思考' : '思考中…'
  const openAttr = isComplete ? '' : ' open'
  return (
    `<details class="md-think" data-think="true"${openAttr}>`
    + `<summary class="md-think-summary">${label}</summary>`
    + `<div class="md-think-body">${bodyHtml || ''}</div>`
    + '</details>'
  )
}
