import test from 'node:test'
import assert from 'node:assert/strict'
import {
  isExternalDataset,
  selectHitTestingApi,
  buildHitTestingBody,
  buildExternalHitTestingBody,
  datasetLandingPath,
  shouldRedirectExternalDataset,
} from './hitTestingRequest.js'

test('selects internal hit-testing for vendor datasets', () => {
  assert.equal(isExternalDataset({ provider: 'vendor' }), false)
  assert.equal(selectHitTestingApi({ provider: 'vendor' }), 'hitTesting')
  assert.equal(datasetLandingPath({ id: 'ds-1', provider: 'vendor' }), '/datasets/ds-1/documents')
})

test('selects external hit-testing for external datasets', () => {
  assert.equal(isExternalDataset({ provider: 'external' }), true)
  assert.equal(selectHitTestingApi({ provider: 'external' }), 'externalHitTesting')
  assert.equal(datasetLandingPath({ id: 'ds-2', provider: 'external' }), '/datasets/ds-2/hitTesting')
})

test('internal body includes retrieval_model and selected rerank names', () => {
  const body = buildHitTestingBody({
    query: '合同到期提醒',
    searchMethod: 'hybrid_search',
    topK: 6,
    scoreEnabled: true,
    scoreThreshold: 0.4,
    rerankEnable: true,
    rerankProvider: 'cohere',
    rerankModel: 'rerank-english-v3.0',
  })
  assert.deepEqual(body, {
    query: '合同到期提醒',
    attachment_ids: [],
    retrieval_model: {
      search_method: 'hybrid_search',
      reranking_enable: true,
      reranking_model: {
        reranking_provider_name: 'cohere',
        reranking_model_name: 'rerank-english-v3.0',
      },
      top_k: 6,
      score_threshold_enabled: true,
      score_threshold: 0.4,
    },
  })
})

test('external body uses external_retrieval_model only', () => {
  const body = buildExternalHitTestingBody({
    query: '外部知识',
    topK: 8,
    scoreEnabled: true,
    scoreThreshold: 0.2,
  })
  assert.deepEqual(body, {
    query: '外部知识',
    external_retrieval_model: {
      top_k: 8,
      score_threshold: 0.2,
      score_threshold_enabled: true,
    },
  })
  assert.equal('retrieval_model' in body, false)
  assert.equal('reranking_enable' in (body.external_retrieval_model || {}), false)
})

test('redirects external datasets away from document and pipeline routes', () => {
  assert.equal(shouldRedirectExternalDataset('dataset-documents', true), true)
  assert.equal(shouldRedirectExternalDataset('dataset-pipeline', true), true)
  assert.equal(shouldRedirectExternalDataset('dataset-hit-testing', true), false)
  assert.equal(shouldRedirectExternalDataset('dataset-documents', false), false)
})
