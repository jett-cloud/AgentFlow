import assert from 'node:assert/strict'
import test from 'node:test'
import {
  normalizeHitTestingHistory,
  normalizeHitTestingHistoryPage,
  resolveHitTestingSearch,
} from './hitTestingState.js'

test('keeps server pagination metadata with normalized history rows', () => {
  assert.deepEqual(normalizeHitTestingHistoryPage({
    data: [{
      id: 'query-6',
      queries: [{ content_type: 'text_query', content: '第六条查询' }],
      source: 'hit_testing',
      source_app_id: null,
      created_by_role: 'account',
      created_by: 'user-1',
      created_at: 1_725_000_000,
    }],
    page: 2,
    limit: 5,
    total: 7,
    has_more: false,
  }), {
    rows: [{ id: 'query-6', text: '第六条查询', createdAt: 1_725_000_000 }],
    page: 2,
    total: 7,
  })
})

test('normalizes nested dataset query history into visible rows', () => {
  assert.deepEqual(normalizeHitTestingHistory([
    {
      id: 'query-1',
      queries: [{ content_type: 'text_query', content: '什么是 RAG？' }],
      source: 'hit_testing',
      source_app_id: null,
      created_by_role: 'account',
      created_by: 'user-1',
      created_at: 1_725_000_000,
    },
    {
      id: 'query-2',
      queries: [{
        content_type: 'image_query',
        content: 'file-1',
        file_info: {
          id: 'file-1',
          name: 'architecture.png',
          size: 1024,
          extension: 'png',
          mime_type: 'image/png',
          source_url: '/files/file-1',
        },
      }],
      source: 'hit_testing',
      source_app_id: null,
      created_by_role: 'account',
      created_by: 'user-1',
      created_at: 1_725_000_100,
    },
    {
      id: 'query-3',
      queries: [],
      source: 'hit_testing',
      source_app_id: null,
      created_by_role: 'account',
      created_by: 'user-1',
      created_at: 1_725_000_200,
    },
  ]), [
    { id: 'query-1', text: '什么是 RAG？', createdAt: 1_725_000_000 },
    { id: 'query-2', text: 'architecture.png', createdAt: 1_725_000_100 },
  ])
})

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

