import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import {
  KNOWLEDGE_RETRIEVAL_DEFAULTS,
  isKnowledgeAttachmentInput,
  isKnowledgeMultipleConfigValid,
  isKnowledgeQueryInput,
  isKnowledgeRetrievalInputConfigured,
  isValidKnowledgeWeights,
  normalizeKnowledgeRetrievalData,
  syncWeightedScoreEmbedding,
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

test('normalization migrates legacy string selectors', () => {
  const normalized = normalizeKnowledgeRetrievalData({
    type: 'knowledge-retrieval',
    query_variable_selector: 'llm.text',
    query_attachment_selector: 'sys.files',
    dataset_ids: ['ds-1'],
    retrieval_mode: 'multiple',
  })

  assert.deepEqual(normalized.query_variable_selector, ['llm', 'text'])
  assert.deepEqual(normalized.query_attachment_selector, ['sys', 'files'])
})

test('knowledge retrieval exposes the official result output', () => {
  const outputs = getNodeOutputVars({ data: { type: 'knowledge-retrieval' } })
  assert.deepEqual(outputs, [{ variable: 'result', type: 'arrayObject', des: '检索结果' }])
})

test('weighted-score rerank validates weights instead of a rerank model', () => {
  const data = {
    retrieval_mode: 'multiple',
    multiple_retrieval_config: {
      top_k: 4,
      score_threshold: null,
      reranking_enable: true,
      reranking_mode: 'weighted_score',
      weights: {
        vector_setting: {
          vector_weight: 0.7,
          embedding_provider_name: 'provider',
          embedding_model_name: 'embedding-model',
        },
        keyword_setting: { keyword_weight: 0.3 },
      },
    },
  }

  assert.equal(isKnowledgeMultipleConfigValid(data), true)
  assert.equal(isKnowledgeMultipleConfigValid({
    ...data,
    multiple_retrieval_config: { ...data.multiple_retrieval_config, weights: undefined },
  }), false)
  assert.equal(isKnowledgeMultipleConfigValid({
    ...data,
    multiple_retrieval_config: {
      ...data.multiple_retrieval_config,
      weights: {
        vector_setting: {
          vector_weight: 0.8,
          embedding_provider_name: 'provider',
          embedding_model_name: 'embedding-model',
        },
        keyword_setting: { keyword_weight: 0.3 },
      },
    },
  }), false)
  assert.equal(isKnowledgeMultipleConfigValid({
    ...data,
    multiple_retrieval_config: {
      ...data.multiple_retrieval_config,
      weights: {
        vector_setting: {
          vector_weight: 0.7,
          embedding_provider_name: '',
          embedding_model_name: 'embedding-model',
        },
        keyword_setting: { keyword_weight: 0.3 },
      },
    },
  }), false)
  assert.equal(isKnowledgeMultipleConfigValid({
    retrieval_mode: 'multiple',
    multiple_retrieval_config: {
      top_k: 4,
      reranking_enable: true,
      reranking_mode: 'reranking_model',
    },
  }), false)
})

test('weighted-score treats null and non-object weights as invalid without throwing', () => {
  for (const weights of [null, ['bad'], 'bad', 1]) {
    assert.equal(isValidKnowledgeWeights(weights), false)
    assert.equal(isKnowledgeMultipleConfigValid({
      retrieval_mode: 'multiple',
      multiple_retrieval_config: {
        top_k: 4,
        reranking_mode: 'weighted_score',
        weights,
      },
    }), false)
  }
})

test('switching datasets updates embedding but keeps user weights', () => {
  const weights = {
    vector_setting: {
      vector_weight: 0.4,
      embedding_provider_name: 'provider-a',
      embedding_model_name: 'model-a',
    },
    keyword_setting: { keyword_weight: 0.6 },
  }
  const next = syncWeightedScoreEmbedding(weights, [{
    embedding_model_provider: 'provider-b',
    embedding_model: 'model-b',
  }])
  assert.equal(next.vector_setting.vector_weight, 0.4)
  assert.equal(next.keyword_setting.keyword_weight, 0.6)
  assert.equal(next.vector_setting.embedding_provider_name, 'provider-b')
  assert.equal(next.vector_setting.embedding_model_name, 'model-b')
  assert.equal(isValidKnowledgeWeights(next), true)
})

test('switching to a dataset without embedding clears provider fields and blocks save', () => {
  const next = syncWeightedScoreEmbedding({
    vector_setting: {
      vector_weight: 0.7,
      embedding_provider_name: 'provider-a',
      embedding_model_name: 'model-a',
    },
    keyword_setting: { keyword_weight: 0.3 },
  }, [{ name: 'empty-kb' }])
  assert.equal(next.vector_setting.embedding_provider_name, '')
  assert.equal(next.vector_setting.embedding_model_name, '')
  assert.equal(next.vector_setting.vector_weight, 0.7)
  assert.equal(isValidKnowledgeWeights(next), false)
  assert.equal(isKnowledgeMultipleConfigValid({
    retrieval_mode: 'multiple',
    multiple_retrieval_config: { top_k: 4, reranking_mode: 'weighted_score', weights: next },
  }), false)
})

test('mixed dataset embeddings are incompatible and clear provider fields', () => {
  const next = syncWeightedScoreEmbedding({
    vector_setting: {
      vector_weight: 0.5,
      embedding_provider_name: 'provider-a',
      embedding_model_name: 'model-a',
    },
    keyword_setting: { keyword_weight: 0.5 },
  }, [
    { embedding_model_provider: 'provider-a', embedding_model: 'model-a' },
    { embedding_model_provider: 'provider-b', embedding_model: 'model-b' },
  ])
  assert.equal(next.vector_setting.embedding_provider_name, '')
  assert.equal(next.vector_setting.embedding_model_name, '')
  assert.equal(isValidKnowledgeWeights(next), false)
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

test('generator-shaped knowledge retrieval round-trips through the frontend DSL', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'kr',
      type: 'custom',
      data: {
        type: 'knowledge-retrieval',
        query_variable_selector: ['start', 'query'],
        query_attachment_selector: [],
        dataset_ids: ['ds-1'],
        retrieval_mode: 'multiple',
        multiple_retrieval_config: { top_k: 4, score_threshold: null, reranking_enable: false },
        future_field: 'preserved',
      },
    }],
    edges: [],
  })
  const exported = flowToGraph(flow.nodes, flow.edges).nodes[0]
  assert.deepEqual(exported.data.query_variable_selector, ['start', 'query'])
  assert.deepEqual(exported.data.dataset_ids, ['ds-1'])
  assert.equal(exported.data.retrieval_mode, 'multiple')
  assert.equal(exported.data.multiple_retrieval_config.top_k, 4)
  assert.equal(exported.data.future_field, 'preserved')
})

test('knowledge retrieval outputs only result and keeps the default source handle', () => {
  const node = { data: { type: 'knowledge-retrieval' } }
  assert.deepEqual(getNodeOutputVars(node), [
    { variable: 'result', type: 'arrayObject', des: '检索结果' },
  ])
  assert.equal(getNodeOutputBranches(node.data).some(branch => branch.id === 'source'), true)
})
