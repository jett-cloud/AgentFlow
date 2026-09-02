import { parseSelectorInput } from '../../model/availableVariables.js'

export const KNOWLEDGE_BASE_DEFAULTS = {
  index_chunk_variable_selector: [],
  keyword_number: 10,
  retrieval_model: {
    top_k: 3,
    score_threshold_enabled: false,
    score_threshold: 0.5,
  },
}

const CHUNK_SCHEMA_TYPES = {
  text_model: new Set(['general_structure', 'multimodal_general_structure']),
  hierarchical_model: new Set(['parent_child_structure', 'multimodal_parent_child_structure']),
  qa_model: new Set(['qa_structure']),
}

export function isKnowledgeChunkInput(variable, chunkStructure) {
  return CHUNK_SCHEMA_TYPES[chunkStructure]?.has(variable?.schemaType) || false
}

export function normalizeKnowledgeBaseData(data = {}) {
  const retrievalModel = {
    ...KNOWLEDGE_BASE_DEFAULTS.retrieval_model,
    ...(data.retrieval_model || {}),
  }
  if (data.top_k !== undefined)
    retrievalModel.top_k = data.top_k
  if (data.score_threshold !== undefined)
    retrievalModel.score_threshold = data.score_threshold
  const normalized = {
    ...data,
    index_chunk_variable_selector: parseSelectorInput(data.index_chunk_variable_selector),
    keyword_number: data.keyword_number ?? KNOWLEDGE_BASE_DEFAULTS.keyword_number,
    retrieval_model: retrievalModel,
  }
  delete normalized.top_k
  delete normalized.score_threshold
  return normalized
}

export function isKnowledgeRetrievalSettingValid(data = {}) {
  const retrieval = data.retrieval_model || {}
  if (!['hybrid_search', 'semantic_search', 'full_text_search', 'keyword_search'].includes(retrieval.search_method))
    return false
  const topK = Number(retrieval.top_k)
  if (!Number.isInteger(topK) || topK < 1 || topK > 20)
    return false
  if (retrieval.score_threshold_enabled) {
    const threshold = Number(retrieval.score_threshold)
    if (!Number.isFinite(threshold) || threshold < 0 || threshold > 1)
      return false
  }
  if (retrieval.reranking_enable) {
    return Boolean(
      retrieval.reranking_model?.reranking_provider_name
      && retrieval.reranking_model?.reranking_model_name,
    )
  }
  return true
}

