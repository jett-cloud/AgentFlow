/**
 * KaTeX helpers for chat/RESULT markdown (Dify streamdown math parity, subset).
 */
import katex from 'katex'

/**
 * Protect $$...$$ / $...$ spans before HTML escaping.
 * @param {string} text
 * @returns {{ text: string, slots: string[] }}
 */
export function extractMathSlots(text) {
  const slots = []
  let next = String(text || '')

  next = next.replace(/\$\$([\s\S]+?)\$\$/g, (_match, body) => {
    const index = slots.length
    slots.push({ displayMode: true, body: String(body || '').trim() })
    return `\u0000MATH${index}\u0000`
  })

  // Inline $...$ — skip $$ leftovers and empty bodies.
  next = next.replace(/\$([^$\n]+?)\$/g, (match, body, offset, full) => {
    if (full[offset - 1] === '$' || full[offset + match.length] === '$')
      return match
    const index = slots.length
    slots.push({ displayMode: false, body: String(body || '').trim() })
    return `\u0000MATH${index}\u0000`
  })

  return { text: next, slots }
}

/**
 * @param {{ displayMode?: boolean, body?: string }} slot
 * @returns {string}
 */
export function renderMathSlot(slot) {
  const body = slot?.body || ''
  if (!body)
    return ''
  try {
    return katex.renderToString(body, {
      throwOnError: false,
      displayMode: Boolean(slot.displayMode),
      output: 'html',
    })
  }
  catch {
    return `<code class="markdown-inline-code">${escapeHtml(body)}</code>`
  }
}

/**
 * @param {string} html
 * @param {Array<{ displayMode?: boolean, body?: string }>} slots
 */
export function restoreMathSlots(html, slots = []) {
  return String(html || '').replace(/\u0000MATH(\d+)\u0000/g, (_match, indexText) => {
    const index = Number(indexText)
    const slot = slots[index]
    if (!slot)
      return ''
    return renderMathSlot(slot)
  })
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}
