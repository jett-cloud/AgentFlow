export function flattenModelCatalog(payload) {
  const data = payload?.data || payload || []
  return (Array.isArray(data) ? data : []).flatMap(provider => (provider.models || []).map(model => ({
    provider: provider.provider || provider.provider_name || '',
    providerLabel: provider.label?.zh_Hans || provider.label?.en_US || provider.label || provider.provider,
    model: model.model || model.model_name,
    label: model.label?.zh_Hans || model.label?.en_US || model.label || model.model,
  }))).filter(item => item.provider && item.model)
}

export function isRerankConfigValid(retrievalModel) {
  if (!retrievalModel?.reranking_enable)
    return true
  return Boolean(
    retrievalModel.reranking_model?.reranking_provider_name
    && retrievalModel.reranking_model?.reranking_model_name,
  )
}

export function rerankModelKey(retrievalModel) {
  const model = retrievalModel?.reranking_model
  if (!model?.reranking_provider_name || !model?.reranking_model_name)
    return ''
  return `${model.reranking_provider_name}::${model.reranking_model_name}`
}

export function parseRerankKey(key) {
  const [provider = '', model = ''] = String(key || '').split('::')
  return {
    reranking_provider_name: provider,
    reranking_model_name: model,
  }
}
