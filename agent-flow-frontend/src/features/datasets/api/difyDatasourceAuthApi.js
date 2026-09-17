// Datasource plugin auth — mirrors web/service/use-datasource.ts
import difyClient from '../../../shared/http/difyClient.js'

/** Dify RAG pipeline datasource provider and action catalog. */
export function fetchRagPipelineDatasourcePlugins() {
  return difyClient.get('/rag/pipelines/datasource-plugins', { silent: true })
}

export function fetchDatasourceAuthList() {
  return difyClient.get('/auth/plugin/datasource/list', { silent: true })
}

export function fetchDefaultDatasourceAuthList() {
  return difyClient.get('/auth/plugin/datasource/default-list', { silent: true })
}

export function fetchDatasourceProviderAuth(pluginId, provider) {
  return difyClient.get(
    `/auth/plugin/datasource/${encodeURIComponent(pluginId)}/${encodeURIComponent(provider)}`,
    { silent: true },
  )
}

export function fetchDatasourceOAuthUrl(provider, credentialId = '') {
  const q = credentialId ? `?credential_id=${encodeURIComponent(credentialId)}` : ''
  return difyClient.get(`/oauth/plugin/${encodeURIComponent(provider)}/datasource/get-authorization-url${q}`)
}

/** Notion pages for import. Contrasts GET /notion/pre-import/pages */
export function fetchNotionPreImportPages({ credentialId, datasetId } = {}) {
  return difyClient.get('/notion/pre-import/pages', {
    params: {
      ...(credentialId ? { credential_id: credentialId } : {}),
      ...(datasetId ? { dataset_id: datasetId } : {}),
    },
  })
}

export function fetchNotionPagePreview(pageId, pageType, credentialId) {
  return difyClient.get(
    `/notion/pages/${encodeURIComponent(pageId)}/${encodeURIComponent(pageType)}/preview`,
    { params: { credential_id: credentialId } },
  )
}

/**
 * Find auth entry by provider name (e.g. notion_datasource, firecrawl, jinareader).
 * @param {object} listResponse
 * @param {string|string[]} providers
 */
export function findDatasourceAuth(listResponse, providers) {
  const list = listResponse?.result || listResponse?.data || (Array.isArray(listResponse) ? listResponse : [])
  const wanted = new Set((Array.isArray(providers) ? providers : [providers]).map(String))
  return list.find((item) => {
    const p = item.provider || item.provider_name || ''
    return wanted.has(p) || [...wanted].some(w => p.includes(w))
  }) || null
}

export function getDatasourceCredentials(authEntry) {
  if (!authEntry)
    return []
  return authEntry.credentials_list || authEntry.credentials || []
}
