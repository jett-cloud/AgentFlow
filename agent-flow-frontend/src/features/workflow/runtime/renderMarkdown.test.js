import test from 'node:test'
import assert from 'node:assert/strict'
import { renderMarkdown } from '../utils/helpers.js'

test('inline code and identifiers preserve underscores without cross-element emphasis', () => {
  const html = renderMarkdown('确认：`source_query` 删除 `node_source_retrieval`，build_node 和 eval_count。_斜体_')
  assert.match(html, /<code class="markdown-inline-code">source_query<\/code>/)
  assert.match(html, /<code class="markdown-inline-code">node_source_retrieval<\/code>/)
  assert.match(html, /build_node 和 eval_count/)
  assert.match(html, /<em>斜体<\/em>/)
  assert.equal((html.match(/<em>/g) || []).length, 1)
})

test('renderMarkdown escapes raw HTML', () => {
  const html = renderMarkdown('<script>alert(1)</script>')
  assert.equal(html.includes('<script>'), false)
  assert.match(html, /&lt;script&gt;/)
})

test('renderMarkdown renders bold italic code links lists headings', () => {
  const html = renderMarkdown([
    '# Title',
    '',
    'Hello **world** and *italics* with `code`.',
    '',
    '- one',
    '- two',
    '',
    '1. a',
    '2. b',
    '',
    '[docs](https://example.com)',
  ].join('\n'))

  assert.match(html, /<h1 class="markdown-heading">Title<\/h1>/)
  assert.match(html, /<strong>world<\/strong>/)
  assert.match(html, /<em>italics<\/em>/)
  assert.match(html, /<code class="markdown-inline-code">code<\/code>/)
  assert.match(html, /<ul class="markdown-list">/)
  assert.match(html, /<ol class="markdown-list">/)
  assert.match(html, /class="markdown-link"/)
  assert.match(html, /href="https:\/\/example.com"/)
})

test('inline code stays literal and escaped during later formatting', () => {
  const html = renderMarkdown('`**bold** _italic_ [link](javascript:alert(1)) <img src=x onerror=alert(1)>`')
  assert.doesNotMatch(html, /<(?:strong|em|a|img)\b/)
  assert.match(html, /\*\*bold\*\* _italic_/)
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/)
})

test('renderMarkdown rejects executable and attribute-injection links', () => {
  const html = renderMarkdown([
    '[script](javascript:alert(1))',
    '[encoded](javascript&colon;alert(1))',
    '[quote](https://example.com/" onclick="alert(1))',
    '[safe](https://example.com/docs?q=one&x=two)',
  ].join('\n'))

  assert.doesNotMatch(html, /javascript:/i)
  assert.doesNotMatch(html, /onclick=/i)
  assert.match(html, /href="https:\/\/example\.com\/docs\?q=one&amp;x=two"/)
})

test('renderMarkdown keeps fenced code blocks', () => {
  const html = renderMarkdown('before\n```js\nconst x = 1\n```\nafter')
  assert.match(html, /<pre class="markdown-code-block"><code>const x = 1<\/code><\/pre>/)
  assert.match(html, /before/)
  assert.match(html, /after/)
})

test('renderMarkdown still escapes script tags outside think', () => {
  const html = renderMarkdown('hi <script>alert(1)</script>')
  assert.equal(html.includes('<script>'), false)
  assert.match(html, /&lt;script&gt;/)
})
