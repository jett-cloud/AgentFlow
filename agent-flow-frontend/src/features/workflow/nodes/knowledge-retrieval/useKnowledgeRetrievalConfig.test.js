import test from 'node:test'
import assert from 'node:assert/strict'
import {
  applyRerankingMode,
  applyWeightedScore,
  isValidKnowledgeWeights,
  normalizeKnowledgeRetrievalData,
  syncWeightedScoreEmbedding,
} from './knowledgeRetrievalNode.js'

test('switching reranking mode keeps top_k and score threshold', () => {
  const current = {
    top_k: 6,
    score_threshold: 0.4,
    reranking_enable: true,
    reranking_mode: 'reranking_model',
    reranking_model: { provider: 'cohere', model: 'rerank' },
  }
  const next = applyRerankingMode(current, 'weighted_score')
  assert.equal(next.reranking_mode, 'weighted_score')
  assert.equal(next.top_k, 6)
  assert.equal(next.score_threshold, 0.4)
  assert.deepEqual(next.reranking_model, { provider: 'cohere', model: 'rerank' })
})

test('setting weighted score preserves top_k and score threshold', () => {
  const current = {
    top_k: 8,
    score_threshold: 0.2,
    reranking_mode: 'weighted_score',
  }
  const weights = {
    vector_setting: {
      vector_weight: 0.7,
      embedding_provider_name: 'openai',
      embedding_model_name: 'text-embedding-3-small',
    },
    keyword_setting: { keyword_weight: 0.3 },
  }
  const next = applyWeightedScore(current, weights)
  assert.equal(next.top_k, 8)
  assert.equal(next.score_threshold, 0.2)
  assert.deepEqual(next.weights, weights)
})

test('single/multiple switch still drops the inactive retrieval config', () => {
  const multiple = normalizeKnowledgeRetrievalData({
    retrieval_mode: 'multiple',
    multiple_retrieval_config: { top_k: 4, reranking_enable: false },
    single_retrieval_config: { model: { provider: 'openai', name: 'gpt-4o' } },
  })
  assert.equal(multiple.single_retrieval_config, undefined)
  assert.equal(multiple.multiple_retrieval_config.top_k, 4)

  const single = normalizeKnowledgeRetrievalData({
    retrieval_mode: 'single',
    multiple_retrieval_config: { top_k: 4, reranking_enable: false },
    single_retrieval_config: { model: { provider: 'openai', name: 'gpt-4o' } },
  })
  assert.equal(single.multiple_retrieval_config, undefined)
  assert.equal(single.single_retrieval_config.model.name, 'gpt-4o')
})

test('null and non-object weights stay invalid without throwing', () => {
  for (const weights of [null, ['bad'], 'bad'])
    assert.equal(isValidKnowledgeWeights(weights), false)
})

test('dataset switch refreshes embedding and missing embedding blocks save', () => {
  const kept = syncWeightedScoreEmbedding({
    vector_setting: {
      vector_weight: 0.4,
      embedding_provider_name: 'provider-a',
      embedding_model_name: 'model-a',
    },
    keyword_setting: { keyword_weight: 0.6 },
  }, [{ embedding_model_provider: 'provider-b', embedding_model: 'model-b' }])
  assert.equal(kept.vector_setting.embedding_provider_name, 'provider-b')
  assert.equal(kept.keyword_setting.keyword_weight, 0.6)
  assert.equal(isValidKnowledgeWeights(kept), true)

  const cleared = syncWeightedScoreEmbedding(kept, [{ name: 'no-embedding' }])
  assert.equal(cleared.vector_setting.embedding_provider_name, '')
  assert.equal(isValidKnowledgeWeights(cleared), false)

  const mixed = syncWeightedScoreEmbedding(kept, [
    { embedding_model_provider: 'provider-a', embedding_model: 'model-a' },
    { embedding_model_provider: 'provider-b', embedding_model: 'model-b' },
  ])
  assert.equal(mixed.vector_setting.embedding_model_name, '')
  assert.equal(isValidKnowledgeWeights(mixed), false)
})
