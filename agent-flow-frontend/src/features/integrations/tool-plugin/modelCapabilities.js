const FUNCTION_CALLING_FEATURES = new Set(['tool-call', 'multi-tool-call'])

export function supportsFunctionCalling(model) {
  return (model?.features || []).some(feature => FUNCTION_CALLING_FEATURES.has(feature))
}

export function filterFunctionCallingProviders(providers) {
  return (providers || [])
    .map(provider => ({
      ...provider,
      models: (provider.models || []).filter(supportsFunctionCalling),
    }))
    .filter(provider => provider.models.length > 0)
}
