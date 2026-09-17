// Dataset RBAC access-control APIs — mirrors web/service/access-control/use-dataset-access-config.ts
import difyClient from '../../../shared/http/difyClient.js'

export function fetchDatasetAccessPolicy(datasetId, { language = 'zh' } = {}) {
  return difyClient.get(
    `/workspaces/current/rbac/datasets/${encodeURIComponent(datasetId)}/access-policy`,
    { params: { language }, silent: true },
  )
}

export function fetchDatasetUserAccessPolicies(datasetId, { language = 'zh' } = {}) {
  return difyClient.get(
    `/workspaces/current/rbac/datasets/${encodeURIComponent(datasetId)}/user-access-policies`,
    { params: { language }, silent: true },
  )
}

export function updateDatasetOpenScope(datasetId, scope) {
  return difyClient.put(
    `/workspaces/current/rbac/datasets/${encodeURIComponent(datasetId)}/whitelist`,
    { scope },
  )
}

export function updateDatasetUserAccessPolicies(datasetId, accountId, accessPolicyIds) {
  return difyClient.put(
    `/workspaces/current/rbac/datasets/${encodeURIComponent(datasetId)}/users/${encodeURIComponent(accountId)}/access-policies`,
    { access_policy_ids: accessPolicyIds },
  )
}

export function removeDatasetAccessPolicyMembers(datasetId, policyId, accountIds) {
  return difyClient.delete(
    `/workspaces/current/rbac/datasets/${encodeURIComponent(datasetId)}/access-policies/${encodeURIComponent(policyId)}/member-bindings`,
    { data: { account_ids: accountIds } },
  )
}

export function fetchWorkspaceMembers() {
  return difyClient.get('/workspaces/current/members', { silent: true })
}
