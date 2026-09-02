import { DEFAULT_RETRIEVAL_MODEL } from './createDocumentPayload.js'

export function isExternalDataset(dataset) {
  return dataset?.provider === 'external'
}

export function selectHitTestingApi(dataset) {
  return isExternalDataset(dataset) ? 'externalHitTesting' : 'hitTesting'
}

export function datasetLandingPath(dataset) {
  const id = dataset?.id
  if (!id)
    return '/datasets'
  return isExternalDataset(dataset)
    ? `/datasets/${id}/hitTesting`
    : `/datasets/${id}/documents`
}

export function shouldRedirectExternalDataset(routeName, isExternal) {
  if (!isExternal)
    return false
  return routeName === 'dataset-documents' || routeName === 'dataset-pipeline'
}

export function buildHitTestingBody({
  query,
  searchMethod,
  topK,
  scoreEnabled,
  scoreThreshold,
  rerankEnable,
  rerankProvider,
  rerankModel,
}) {
  return {
    query,
    attachment_ids: [],
    retrieval_model: {
      ...DEFAULT_RETRIEVAL_MODEL,
      search_method: searchMethod,
      top_k: topK,
      score_threshold_enabled: Boolean(scoreEnabled),
      score_threshold: scoreEnabled ? scoreThreshold : 0,
      reranking_enable: Boolean(rerankEnable),
      reranking_model: {
        reranking_provider_name: rerankProvider || '',
        reranking_model_name: rerankModel || '',
      },
    },
  }
}

export function buildExternalHitTestingBody({
  query,
  topK,
  scoreEnabled,
  scoreThreshold,
}) {
  return {
    query,
    external_retrieval_model: {
      top_k: topK,
      score_threshold: scoreEnabled ? scoreThreshold : 0,
      score_threshold_enabled: Boolean(scoreEnabled),
    },
  }
}
