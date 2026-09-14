import test from 'node:test'
import assert from 'node:assert/strict'
import { flattenModelCatalog, isRerankConfigValid } from './retrievalModel.js'

test('rerank config is valid when rerank is off even with empty model', () => {
  assert.equal(isRerankConfigValid({
    reranking_enable: false,
    reranking_model: { reranking_provider_name: '', reranking_model_name: '' },
  }), true)
})

test('rerank config is invalid when enabled without provider or model', () => {
  assert.equal(isRerankConfigValid({
    reranking_enable: true,
    reranking_model: { reranking_provider_name: '', reranking_model_name: '' },
  }), false)
  assert.equal(isRerankConfigValid({
    reranking_enable: true,
    reranking_model: { reranking_provider_name: 'cohere', reranking_model_name: '' },
  }), false)
})

test('rerank config is valid only after an explicit provider and model', () => {
  assert.equal(isRerankConfigValid({
    reranking_enable: true,
    reranking_model: {
      reranking_provider_name: 'cohere',
      reranking_model_name: 'rerank-english-v3.0',
    },
  }), true)
})

test('flattenModelCatalog does not pick a default rerank model', () => {
  const catalog = flattenModelCatalog({
    data: [{
      provider: 'cohere',
      label: { en_US: 'Cohere' },
      models: [{ model: 'rerank-english-v3.0', label: { en_US: 'Rerank EN' } }],
    }],
  })
  assert.deepEqual(catalog, [{
    provider: 'cohere',
    providerLabel: 'Cohere',
    model: 'rerank-english-v3.0',
    label: 'Rerank EN',
  }])
  assert.equal(isRerankConfigValid({
    reranking_enable: true,
    reranking_model: { reranking_provider_name: '', reranking_model_name: '' },
  }), false)
})

test('flattenModelCatalog keeps provider icons for model selectors', () => {
  const catalog = flattenModelCatalog({
    data: [{
      provider: 'siliconflow',
      label: { zh_Hans: '硅基流动' },
      icon_small: { zh_Hans: '/console/api/workspaces/current/model-providers/siliconflow/icon_small/zh_Hans' },
      models: [{ model: 'bce-embedding-base_v1', label: { en_US: 'BCE Embedding' } }],
    }],
  })

  assert.deepEqual(catalog, [{
    provider: 'siliconflow',
    providerLabel: '硅基流动',
    providerIcon: { zh_Hans: '/console/api/workspaces/current/model-providers/siliconflow/icon_small/zh_Hans' },
    model: 'bce-embedding-base_v1',
    label: 'BCE Embedding',
  }])
})
