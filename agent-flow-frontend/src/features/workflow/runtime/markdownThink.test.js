import test from 'node:test'
import assert from 'node:assert/strict'
import {
  isThinkBlockComplete,
  preprocessThinkTag,
  renderThinkBlockHtml,
  splitThinkSegments,
  stripEndThinkFlag,
} from './markdownThink.js'
import { renderMarkdown } from '../utils/helpers.js'

test('preprocessThinkTag wraps think into details with ENDTHINKFLAG', () => {
  const out = preprocessThinkTag('<think>this is a thought</think>')
  assert.match(out, /<details data-think=true>/)
  assert.match(out, /\[ENDTHINKFLAG\]<\/details>/)
  assert.match(out, /this is a thought/)
})

test('preprocessThinkTag normalizes nested open tags', () => {
  const out = preprocessThinkTag('<think><think>deep</think></think>')
  assert.equal((out.match(/<details data-think=true>/g) || []).length, 1)
  assert.equal((out.match(/\[ENDTHINKFLAG\]<\/details>/g) || []).length, 1)
})

test('splitThinkSegments handles complete and incomplete blocks', () => {
  const complete = splitThinkSegments(preprocessThinkTag('<think>one</think>\nanswer'))
  assert.equal(complete[0].type, 'think')
  assert.equal(complete[0].complete, true)
  assert.equal(complete[1].type, 'md')
  assert.match(complete[1].text, /answer/)

  const incomplete = splitThinkSegments(preprocessThinkTag('<think>streaming'))
  assert.equal(incomplete.length, 1)
  assert.equal(incomplete[0].type, 'think')
  assert.equal(incomplete[0].complete, false)
  assert.match(incomplete[0].text, /streaming/)
})

test('stripEndThinkFlag and completeness', () => {
  const stripped = stripEndThinkFlag('hello\n[ENDTHINKFLAG]')
  assert.equal(stripped.hasEndFlag, true)
  assert.equal(stripped.body.includes('[ENDTHINKFLAG]'), false)
  assert.equal(isThinkBlockComplete({ hasEndFlag: true, isResponding: true }), true)
  assert.equal(isThinkBlockComplete({ hasEndFlag: false, isResponding: true }), false)
  assert.equal(isThinkBlockComplete({ hasEndFlag: false, isResponding: false }), true)
})

test('renderMarkdown collapses think instead of escaping tags', () => {
  const html = renderMarkdown('<think>secret plan</think>\n**done**', { isResponding: false })
  assert.match(html, /class="md-think"/)
  assert.match(html, /已思考/)
  assert.match(html, /secret plan/)
  assert.match(html, /<strong>done<\/strong>/)
  assert.equal(html.includes('&lt;think&gt;'), false)
  assert.equal(html.includes('[ENDTHINKFLAG]'), false)
})

test('renderMarkdown keeps think open while responding without end flag', () => {
  const html = renderMarkdown('<think>still thinking', { isResponding: true })
  assert.match(html, /思考中…/)
  assert.match(html, / open/)
  assert.match(html, /still thinking/)
})

test('renderThinkBlockHtml builds details shell', () => {
  const html = renderThinkBlockHtml({ bodyHtml: '<em>x</em>', isComplete: true })
  assert.match(html, /已思考/)
  assert.match(html, /<em>x<\/em>/)
  assert.equal(html.includes(' open'), false)
})
