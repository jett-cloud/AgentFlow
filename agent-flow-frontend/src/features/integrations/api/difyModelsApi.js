// Console model provider / credential APIs for workspace settings.
import difyClient from '../../../shared/http/difyClient.js'
import { encodeProviderPath } from './difyToolsApi.js'

/** Dify ModelTypeEnum.textGeneration === 'llm' (not 'text-generation'). */
export const DEFAULT_LLM_MODEL_TYPE = 'llm'

export function fetchModelProviders(modelType) {
  return difyClient.get('/workspaces/current/model-providers', {
    params: modelType ? { model_type: modelType } : undefined,
  })
}

export function fetchModelsByType(modelType = DEFAULT_LLM_MODEL_TYPE) {
  return difyClient.get(`/workspaces/current/models/model-types/${encodeURIComponent(modelType)}`)
}

export function fetchTextGenerationModels() {
  return fetchModelsByType(DEFAULT_LLM_MODEL_TYPE)
}

export function fetchProviderCredential(provider, credentialId) {
  return difyClient.get(
    `/workspaces/current/model-providers/${encodeProviderPath(provider)}/credentials`,
    {
      params: credentialId ? { credential_id: credentialId } : undefined,
    },
  )
}

export function createProviderCredential(provider, { name, credentials }) {
  return difyClient.post(
    `/workspaces/current/model-providers/${encodeProviderPath(provider)}/credentials`,
    { name, credentials },
  )
}

export function updateProviderCredential(provider, payload) {
  return difyClient.put(
    `/workspaces/current/model-providers/${encodeProviderPath(provider)}/credentials`,
    payload,
  )
}

export function deleteProviderCredential(provider, { credential_id }) {
  return difyClient.delete(
    `/workspaces/current/model-providers/${encodeProviderPath(provider)}/credentials`,
    { data: { credential_id } },
  )
}

export function switchProviderCredential(provider, { credential_id, model, model_type }) {
  return difyClient.post(
    `/workspaces/current/model-providers/${encodeProviderPath(provider)}/credentials/switch`,
    { credential_id, model, model_type },
  )
}

export function validateProviderCredential(provider, { credentials }) {
  return difyClient.post(
    `/workspaces/current/model-providers/${encodeProviderPath(provider)}/credentials/validate`,
    { credentials },
  )
}

export function fetchModelParameterRules(provider, model) {
  return difyClient.get(
    `/workspaces/current/model-providers/${encodeProviderPath(provider)}/models/parameter-rules`,
    { params: { model } },
  )
}

export function fetchProviderModels(provider) {
  return difyClient.get(
    `/workspaces/current/model-providers/${encodeProviderPath(provider)}/models`,
  )
}
