import test from 'node:test'
import assert from 'node:assert/strict'
import {
  canDownloadCitationGroup,
  extractRetrieverResourcesFromEvent,
  formatCitationLabel,
  groupCitationsByDocument,
  normalizeCitationItems,
} from './citationUtils.js'

test('normalizeCitationItems maps document fields', () => {
  const items = normalizeCitationItems([
    {
      document_name: '手册.pdf',
      dataset_name: '知识库',
      score: 0.91,
      content: '片段',
      data_source_type: 'upload_file',
      segment_position: 2,
    },
    null,
  ])
  assert.equal(items.length, 1)
  assert.equal(items[0].document_name, '手册.pdf')
  assert.equal(items[0].dataset_name, '知识库')
  assert.equal(items[0].score, 0.91)
  assert.equal(items[0].data_source_type, 'upload_file')
  assert.equal(items[0].segment_position, 2)
  assert.equal(formatCitationLabel(items[0]), '手册.pdf')
  assert.equal(formatCitationLabel({}), '未命名文档')
})

test('extractRetrieverResourcesFromEvent reads message_end metadata', () => {
  const items = extractRetrieverResourcesFromEvent({
    event: 'message_end',
    data: {
      metadata: {
        retriever_resources: [{ document_name: 'A', dataset_name: 'KB' }],
      },
    },
  })
  assert.equal(items.length, 1)
  assert.equal(items[0].document_name, 'A')
})

test('groupCitationsByDocument merges same document_id', () => {
  const groups = groupCitationsByDocument([
    {
      document_id: 'd1',
      document_name: '手册.pdf',
      dataset_name: 'KB',
      content: '第一段',
      score: 0.9,
      segment_position: 1,
    },
    {
      document_id: 'd1',
      document_name: '手册.pdf',
      content: '第二段',
      score: 0.8,
      segment_position: 2,
    },
    {
      document_id: 'd2',
      document_name: 'FAQ.md',
      content: '问答',
      score: 0.7,
    },
  ])
  assert.equal(groups.length, 2)
  assert.equal(groups[0].documentName, '手册.pdf')
  assert.equal(groups[0].datasetName, 'KB')
  assert.equal(groups[0].sources.length, 2)
  assert.equal(groups[0].sources[1].content, '第二段')
  assert.equal(groups[1].documentName, 'FAQ.md')
  assert.equal(groups[1].sources.length, 1)
})

test('canDownloadCitationGroup requires upload_file and ids', () => {
  assert.equal(canDownloadCitationGroup({
    dataSourceType: 'upload_file',
    documentId: 'doc',
    sources: [{ dataset_id: 'ds', document_id: 'doc' }],
  }), true)
  assert.equal(canDownloadCitationGroup({
    dataSourceType: 'notion',
    documentId: 'doc',
    sources: [{ dataset_id: 'ds', document_id: 'doc' }],
  }), false)
  assert.equal(canDownloadCitationGroup({
    dataSourceType: 'upload_file',
    documentId: '',
    sources: [{ dataset_id: 'ds' }],
  }), false)
})
