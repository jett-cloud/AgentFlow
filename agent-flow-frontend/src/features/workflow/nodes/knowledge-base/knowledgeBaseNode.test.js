import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import {
  KNOWLEDGE_BASE_DEFAULTS,
  isKnowledgeChunkInput,
  normalizeKnowledgeBaseData,
} from './knowledgeBaseNode.js'

test('new knowledge-index nodes use Dify defaults', () => {
  const { newNode } = generateNewNode({ type: 'knowledge-index', id: 'kb-1' })
  assert.deepEqual(newNode.data, {
    type: 'knowledge-index',
    title: '知识库',
    ...KNOWLEDGE_BASE_DEFAULTS,
  })
})

test('chunk selector only accepts the structure selected by the user', () => {
  assert.equal(isKnowledgeChunkInput({ schemaType: 'general_structure' }, 'text_model'), true)
  assert.equal(isKnowledgeChunkInput({ schemaType: 'multimodal_general_structure' }, 'text_model'), true)
  assert.equal(isKnowledgeChunkInput({ schemaType: 'qa_structure' }, 'text_model'), false)
  assert.equal(isKnowledgeChunkInput({ schemaType: 'qa_structure' }, 'qa_model'), true)
})

test('normalization migrates legacy retrieval fields and preserves unknown fields', () => {
  const normalized = normalizeKnowledgeBaseData({
    index_chunk_variable_selector: 'document.chunks',
    top_k: 6,
    score_threshold: 0.7,
    future: true,
  })
  assert.deepEqual(normalized.index_chunk_variable_selector, ['document', 'chunks'])
  assert.equal(normalized.retrieval_model.top_k, 6)
  assert.equal(normalized.retrieval_model.score_threshold, 0.7)
  assert.equal(normalized.top_k, undefined)
  assert.equal(normalized.future, true)
})

test('DSL round-trip preserves official fields and checklist rejects incomplete config', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'kb-1',
      type: 'custom',
      data: {
        type: 'knowledge-index',
        chunk_structure: 'text_model',
        index_chunk_variable_selector: [],
        indexing_technique: 'high_quality',
        embedding_model: '',
        embedding_model_provider: '',
        keyword_number: 0,
        retrieval_model: {
          search_method: 'hybrid_search',
          top_k: 0,
          score_threshold_enabled: true,
          score_threshold: 2,
          reranking_enable: true,
        },
        future: 1,
      },
    }],
    edges: [],
  })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.future, 1)
  const issues = buildWorkflowChecklist({ nodes: [{ id: 'kb-1', data: exported.nodes[0].data }], edges: [] })
  assert.ok(issues.some(issue => issue.id === 'kb-chunks-kb-1'))
  assert.ok(issues.some(issue => issue.id === 'kb-embedding-kb-1'))
  assert.ok(issues.some(issue => issue.id === 'kb-retrieval-kb-1'))
})
