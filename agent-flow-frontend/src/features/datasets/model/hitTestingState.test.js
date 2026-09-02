import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveHitTestingSearch } from './hitTestingState.js'

test('falls back to full text when every indexed document failed', () => {
  assert.deepEqual(resolveHitTestingSearch({
    preferredMethod: 'semantic_search',
    documents: [{ indexing_status: 'error', enabled: true }],
  }), {
    method: 'full_text_search',
    warning: '向量索引失败，已切换为全文检索。修复文档索引后可再使用向量或混合检索。',
  })
})

test('keeps vector retrieval when at least one document is available', () => {
  assert.deepEqual(resolveHitTestingSearch({
    preferredMethod: 'hybrid_search',
    documents: [
      { indexing_status: 'completed', enabled: true },
      { indexing_status: 'error', enabled: true },
    ],
  }), { method: 'hybrid_search', warning: '' })
})

test('does not override an explicitly usable full text method', () => {
  assert.deepEqual(resolveHitTestingSearch({
    preferredMethod: 'full_text_search',
    documents: [{ indexing_status: 'error', enabled: true }],
  }), { method: 'full_text_search', warning: '' })
})

