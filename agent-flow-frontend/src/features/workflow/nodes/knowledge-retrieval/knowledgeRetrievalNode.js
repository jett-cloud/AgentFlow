import { parseSelectorInput } from '../../model/availableVariables.js'

export const KNOWLEDGE_RETRIEVAL_DEFAULTS = {
  query_variable_selector: [],
  query_attachment_selector: [],
  dataset_ids: [],
  retrieval_mode: 'multiple',
  multiple_retrieval_config: {
    top_k: 4,
    score_threshold: undefined,
    reranking_enable: false,
  },
}

export function isKnowledgeQueryInput(variable) {
  return variable?.type === 'string'
}

export function isKnowledgeAttachmentInput(variable) {
  return ['file', 'arrayFile'].includes(variable?.type)
}

export function isKnowledgeRetrievalInputConfigured(data = {}) {
  return parseSelectorInput(data.query_variable_selector).length > 0
    || parseSelectorInput(data.query_attachment_selector).length > 0
}

export const RERANKING_MODES = [
  { label: 'Rerank 模型', value: 'reranking_model' },
  { label: '加权得分', value: 'weighted_score' },
]

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function isValidKnowledgeWeights(weights) {
  if (!isPlainObject(weights))
    return false
  const vector = weights.vector_setting
  const keyword = weights.keyword_setting
  const vectorWeight = vector?.vector_weight
  const keywordWeight = keyword?.keyword_weight
  if (typeof vectorWeight === 'boolean' || typeof keywordWeight === 'boolean')
    return false
  if (typeof vectorWeight !== 'number' || typeof keywordWeight !== 'number')
    return false
  if (!Number.isFinite(vectorWeight) || !Number.isFinite(keywordWeight))
    return false
  if (vectorWeight < 0 || vectorWeight > 1 || keywordWeight < 0 || keywordWeight > 1)
    return false
  if (Math.abs(vectorWeight + keywordWeight - 1) > 1e-6)
    return false
  return Boolean(
    String(vector?.embedding_provider_name || '').trim()
    && String(vector?.embedding_model_name || '').trim(),
  )
}

export function applyRerankingMode(config = {}, mode) {
  return { ...config, reranking_mode: mode }
}

export function applyWeightedScore(config = {}, weights) {
  return { ...config, weights }
}

export function defaultWeightedScoreFromDataset(dataset) {
  return syncWeightedScoreEmbedding(null, dataset ? [dataset] : [])
}

export function sharedDatasetEmbedding(datasets = []) {
  const embeddings = (Array.isArray(datasets) ? datasets : []).map(dataset => ({
    provider: String(dataset?.embedding_model_provider || '').trim(),
    model: String(dataset?.embedding_model || '').trim(),
  }))
  if (!embeddings.length || embeddings.some(item => !item.provider || !item.model))
    return null
  const key = `${embeddings[0].provider}::${embeddings[0].model}`
  if (embeddings.some(item => `${item.provider}::${item.model}` !== key))
    return null
  return embeddings[0]
}

export function syncWeightedScoreEmbedding(weights, datasets = []) {
  const current = isPlainObject(weights) ? weights : {}
  const vector = isPlainObject(current.vector_setting) ? current.vector_setting : {}
  const keyword = isPlainObject(current.keyword_setting) ? current.keyword_setting : {}
  const embedding = sharedDatasetEmbedding(datasets)
  const vectorWeight = typeof vector.vector_weight === 'number' && Number.isFinite(vector.vector_weight)
    ? vector.vector_weight
    : 0.7
  const keywordWeight = typeof keyword.keyword_weight === 'number' && Number.isFinite(keyword.keyword_weight)
    ? keyword.keyword_weight
    : Number((1 - vectorWeight).toFixed(2))
  return {
    vector_setting: {
      vector_weight: vectorWeight,
      embedding_provider_name: embedding?.provider || '',
      embedding_model_name: embedding?.model || '',
    },
    keyword_setting: { keyword_weight: keywordWeight },
  }
}

export function normalizeKnowledgeRetrievalData(data = {}) {
  const retrievalMode = ['single', 'multiple'].includes(data.retrieval_mode)
    ? data.retrieval_mode
    : 'multiple'
  const legacyDatasetIds = data.dataset_id ? [data.dataset_id] : []
  const multiple = {
    ...KNOWLEDGE_RETRIEVAL_DEFAULTS.multiple_retrieval_config,
    ...(data.multiple_retrieval_config || {}),
  }
  if (data.top_k !== undefined)
    multiple.top_k = data.top_k
  if (data.score_threshold !== undefined)
    multiple.score_threshold = data.score_threshold

  const normalized = {
    ...data,
    query_variable_selector: parseSelectorInput(data.query_variable_selector),
    query_attachment_selector: parseSelectorInput(data.query_attachment_selector),
    dataset_ids: Array.isArray(data.dataset_ids) ? [...data.dataset_ids] : legacyDatasetIds,
    retrieval_mode: retrievalMode,
  }
  if (retrievalMode === 'multiple') {
    normalized.multiple_retrieval_config = multiple
    delete normalized.single_retrieval_config
  }
  else {
    normalized.single_retrieval_config = {
      ...(data.single_retrieval_config || {}),
      model: {
        provider: '',
        name: '',
        mode: 'chat',
        completion_params: {},
        ...(data.single_retrieval_config?.model || {}),
      },
    }
    delete normalized.multiple_retrieval_config
  }
  delete normalized.dataset_id
  delete normalized.top_k
  delete normalized.score_threshold
  return normalized
}

export function isKnowledgeMultipleConfigValid(data = {}) {
  if (data.retrieval_mode !== 'multiple')
    return true
  const config = data.multiple_retrieval_config || {}
  const topK = config.top_k
  if (typeof topK === 'boolean' || !Number.isInteger(topK) || topK < 1 || topK > 10)
    return false
  if (config.score_threshold !== undefined && config.score_threshold !== null) {
    const threshold = config.score_threshold
    if (typeof threshold === 'boolean' || typeof threshold !== 'number' || !Number.isFinite(threshold) || threshold < 0 || threshold > 1)
      return false
  }
  if (config.reranking_mode === 'weighted_score')
    return isValidKnowledgeWeights(config.weights)
  if (config.reranking_mode === 'reranking_model' || !config.reranking_mode) {
    if (!config.reranking_enable)
      return true
    return Boolean(
      String(config.reranking_model?.provider || '').trim()
      && String(config.reranking_model?.model || '').trim(),
    )
  }
  return false
}

export function isKnowledgeMetadataValid(data = {}) {
  if (data.metadata_filtering_mode === 'automatic') {
    return Boolean(data.metadata_model_config?.provider && data.metadata_model_config?.name)
  }
  if (data.metadata_filtering_mode !== 'manual')
    return true
  const block = data.metadata_filtering_conditions
  if (!['and', 'or'].includes(block?.logical_operator) || !block?.conditions?.length)
    return false
  return block.conditions.every((condition) => {
    if (!String(condition?.name || '').trim() || !condition?.comparison_operator)
      return false
    if (['empty', 'not empty', 'is null', 'is not null', 'exists', 'not exists'].includes(condition.comparison_operator))
      return true
    return condition.value !== '' && condition.value !== undefined && condition.value !== null
  })
}

