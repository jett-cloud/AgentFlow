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
    query_variable_selector: Array.isArray(data.query_variable_selector)
      ? [...data.query_variable_selector]
      : [],
    query_attachment_selector: Array.isArray(data.query_attachment_selector)
      ? [...data.query_attachment_selector]
      : [],
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
  const topK = Number(config.top_k)
  if (!Number.isInteger(topK) || topK < 1 || topK > 10)
    return false
  if (config.score_threshold !== undefined && config.score_threshold !== null) {
    const threshold = Number(config.score_threshold)
    if (!Number.isFinite(threshold) || threshold < 0 || threshold > 1)
      return false
  }
  if (config.reranking_enable) {
    return Boolean(config.reranking_model?.provider && config.reranking_model?.model)
  }
  return true
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

