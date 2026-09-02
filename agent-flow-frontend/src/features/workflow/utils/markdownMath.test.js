import test from 'node:test'
import assert from 'node:assert/strict'
import { extractMathSlots, restoreMathSlots, renderMathSlot } from './markdownMath.js'
import { renderMarkdown } from './helpers.js'

test('extractMathSlots finds display and inline math', () => {
  const { text, slots } = extractMathSlots('area $$E=mc^2$$ and $a+b$ end')
  assert.equal(slots.length, 2)
  assert.equal(slots[0].displayMode, true)
  assert.equal(slots[0].body, 'E=mc^2')
  assert.equal(slots[1].displayMode, false)
  assert.equal(slots[1].body, 'a+b')
  assert.match(text, /\u0000MATH0\u0000/)
  assert.match(text, /\u0000MATH1\u0000/)
})

test('renderMathSlot emits katex html', () => {
  const html = renderMathSlot({ displayMode: false, body: 'x^2' })
  assert.match(html, /katex/)
  assert.match(html, /x/)
})

test('restoreMathSlots replaces placeholders', () => {
  const slots = [{ displayMode: false, body: '1+1' }]
  const html = restoreMathSlots('before \u0000MATH0\u0000 after', slots)
  assert.match(html, /katex/)
  assert.match(html, /before/)
  assert.match(html, /after/)
})

test('renderMarkdown renders inline math', () => {
  const html = renderMarkdown('结果 $x^2$ 完成')
  assert.match(html, /katex/)
  assert.match(html, /结果/)
})

test('renderMarkdown keeps mermaid fence as pre.mermaid', () => {
  const html = renderMarkdown('```mermaid\ngraph TD; A-->B;\n```')
  assert.match(html, /<pre class="mermaid">/)
  assert.match(html, /graph TD/)
})
