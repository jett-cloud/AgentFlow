import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  KNOWLEDGE_RETRIEVAL_DEFAULTS,
  isKnowledgeAttachmentInput,
  isKnowledgeQueryInput,
  normalizeKnowledgeRetrievalData,
} from './knowledgeRetrievalNode.js'

test('new knowledge-retrieval nodes use Dify defaults', () => {
  const { newNode } = generateNewNode({ type: 'knowledge-retrieval', id: 'kr-1' })
  assert.deepEqual(newNode.data, {
    type: 'knowledge-retrieval',
    title: '知识检索',
    ...KNOWLEDGE_RETRIEVAL_DEFAULTS,
  })
})

test('query and attachment selectors accept only their official variable types', () => {
  assert.equal(isKnowledgeQueryInput({ type: 'string' }), true)
  assert.equal(isKnowledgeQueryInput({ type: 'number' }), false)
  assert.equal(isKnowledgeAttachmentInput({ type: 'file' }), true)
  assert.equal(isKnowledgeAttachmentInput({ type: 'arrayFile' }), true)
  assert.equal(isKnowledgeAttachmentInput({ type: 'string' }), false)
})

test('normalization migrates legacy dataset_id and top-level retrieval settings', () => {
  const normalized = normalizeKnowledgeRetrievalData({
    dataset_id: 'dataset-1',
    top_k: 7,
    score_threshold: 0.6,
    future: true,
  })
  assert.deepEqual(normalized.dataset_ids, ['dataset-1'])
  assert.equal(normalized.dataset_id, undefined)
  assert.equal(normalized.multiple_retrieval_config.top_k, 7)
  assert.equal(normalized.multiple_retrieval_config.score_threshold, 0.6)
  assert.equal(normalized.top_k, undefined)
  assert.equal(normalized.future, true)
})

test('knowledge retrieval exposes the official result output', () => {
  const outputs = getNodeOutputVars({ data: { type: 'knowledge-retrieval' } })
  assert.deepEqual(outputs, [{ variable: 'result', type: 'arrayObject', des: '检索结果' }])
})

test('DSL round-trip preserves fields and checklist rejects incomplete retrieval settings', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'kr-1',
      type: 'custom',
      data: {
        type: 'knowledge-retrieval',
        query_variable_selector: [],
        query_attachment_selector: [],
        dataset_ids: [],
        retrieval_mode: 'multiple',
        multiple_retrieval_config: {
          top_k: 0,
          score_threshold: 2,
          reranking_enable: true,
          reranking_model: { provider: '', model: '' },
        },
        metadata_filtering_mode: 'manual',
        metadata_filtering_conditions: {
          logical_operator: 'and',
          conditions: [{ id: 'meta-1', name: '', comparison_operator: 'is', value: '' }],
        },
        future: 1,
      },
    }],
    edges: [],
  })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.future, 1)

  const issues = buildWorkflowChecklist({
    nodes: [{ id: 'start', data: { type: 'start' } }, { id: 'kr-1', data: exported.nodes[0].data }],
    edges: [{ source: 'start', target: 'kr-1' }],
  })
  assert.ok(issues.some(issue => issue.id === 'kr-kr-1'))
  assert.ok(issues.some(issue => issue.id === 'kr-multiple-kr-1'))
  assert.ok(issues.some(issue => issue.id === 'kr-metadata-kr-1'))
})
