const RETRIEVAL_RECALL = 'dataset.acl.retrieval_recall'
const ACCESS_CONFIG = 'dataset.acl.access_config'
const DELETE = 'dataset.acl.delete'

export function getDatasetCapabilities(permissionKeys) {
  if (!permissionKeys || permissionKeys.length === 0) {
    return {
      canRetrievalRecall: true,
      canAccessConfig: true,
      canDelete: true,
    }
  }
  const keys = new Set(permissionKeys)
  return {
    canRetrievalRecall: keys.has(RETRIEVAL_RECALL),
    canAccessConfig: keys.has(ACCESS_CONFIG),
    canDelete: keys.has(DELETE),
  }
}

export function visibleDatasetTabs({ datasetId, isExternal, canAccessConfig }) {
  const tabs = []
  if (!isExternal) {
    tabs.push({ name: 'dataset-documents', label: '文档', to: `/datasets/${datasetId}/documents` })
  }
  tabs.push({ name: 'dataset-hit-testing', label: '召回测试', to: `/datasets/${datasetId}/hitTesting` })
  tabs.push({ name: 'dataset-settings', label: '设置', to: `/datasets/${datasetId}/settings` })
  if (!isExternal) {
    tabs.push({ name: 'dataset-pipeline', label: '流水线', to: `/datasets/${datasetId}/pipeline` })
  }
  if (canAccessConfig) {
    tabs.push({ name: 'dataset-access-config', label: '访问控制', to: `/datasets/${datasetId}/access-config` })
  }
  tabs.push({ name: 'dataset-api', label: 'API', to: `/datasets/${datasetId}/api` })
  return tabs
}
