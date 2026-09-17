import { createRouter, createWebHashHistory } from 'vue-router'
import { getDifyProfile } from '@/shared/auth/difyAuth.js'
import { refreshAccessTokenOrReLogin } from '@/shared/auth/difyRefreshToken.js'
import { ElMessage } from 'element-plus'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../../features/auth/pages/LoginPage.vue'),
  },
  {
    path: '/',
    name: 'copilot',
    component: () => import('../../features/workflow/pages/WorkflowPage.vue'),
  },
  {
    path: '/integrations',
    name: 'integrations',
    component: () => import('../../features/integrations/pages/Integrations.vue'),
  },
  {
    path: '/integrations/tools/ai-create',
    name: 'ai-tool-plugin-studio',
    component: () => import('../../features/integrations/pages/AiToolPluginStudio.vue'),
  },
  {
    path: '/integrations/mcp/connect',
    name: 'mcp-remote-connect',
    component: () => import('../../features/integrations/pages/McpRemoteAssistant.vue'),
  },
  {
    path: '/integrations/mcp/ai-create',
    redirect: '/integrations/mcp/connect',
  },
  {
    path: '/integrations/marketplace/tools',
    name: 'marketplace-tools',
    component: () => import('../../features/integrations/marketplace/MarketplaceBrowsePage.vue'),
    props: { category: 'tool' },
  },
  {
    path: '/integrations/marketplace/tools/:org/:name',
    name: 'marketplace-tools-detail',
    component: () => import('../../features/integrations/marketplace/MarketplaceDetailPage.vue'),
    props: { category: 'tool' },
  },
  {
    path: '/integrations/marketplace/models',
    name: 'marketplace-models',
    component: () => import('../../features/integrations/marketplace/MarketplaceBrowsePage.vue'),
    props: { category: 'model' },
  },
  {
    path: '/integrations/marketplace/models/:org/:name',
    name: 'marketplace-models-detail',
    component: () => import('../../features/integrations/marketplace/MarketplaceDetailPage.vue'),
    props: { category: 'model' },
  },
  {
    path: '/datasets',
    name: 'datasets',
    component: () => import('../../features/datasets/pages/DatasetListPage.vue'),
  },
  {
    path: '/datasets/create',
    name: 'datasets-create',
    component: () => import('../../features/datasets/pages/create/DatasetCreateWizard.vue'),
  },
  {
    path: '/datasets/create-from-pipeline',
    name: 'datasets-create-from-pipeline',
    component: () => import('../../features/datasets/pages/create-from-pipeline/CreateFromPipelinePage.vue'),
  },
  {
    path: '/datasets/connect',
    name: 'datasets-connect',
    component: () => import('../../features/datasets/pages/connect/ConnectExternalKbPage.vue'),
  },
  {
    path: '/datasets/:datasetId',
    component: () => import('../../features/datasets/pages/DatasetDetailLayout.vue'),
    children: [
      {
        path: '',
        redirect: to => ({ name: 'dataset-documents', params: { datasetId: to.params.datasetId } }),
      },
      {
        path: 'documents',
        name: 'dataset-documents',
        component: () => import('../../features/datasets/pages/documents/DocumentListPage.vue'),
      },
      {
        path: 'documents/create',
        name: 'dataset-documents-create',
        component: () => import('../../features/datasets/pages/create/DatasetCreateWizard.vue'),
        props: route => ({ datasetId: route.params.datasetId }),
      },
      {
        path: 'documents/:documentId',
        name: 'dataset-document-detail',
        component: () => import('../../features/datasets/pages/documents/DocumentDetailPage.vue'),
      },
      {
        path: 'hitTesting',
        name: 'dataset-hit-testing',
        component: () => import('../../features/datasets/pages/hit-testing/HitTestingPage.vue'),
      },
      {
        path: 'settings',
        name: 'dataset-settings',
        component: () => import('../../features/datasets/pages/settings/DatasetSettingsPage.vue'),
      },
      {
        path: 'access-config',
        name: 'dataset-access-config',
        component: () => import('../../features/datasets/pages/access-config/DatasetAccessConfigPage.vue'),
      },
      {
        path: 'pipeline',
        name: 'dataset-pipeline',
        component: () => import('../../features/datasets/pages/pipeline/PipelineEditorPage.vue'),
      },
      {
        path: 'api',
        name: 'dataset-api',
        component: () => import('../../features/datasets/pages/api/DatasetApiPage.vue'),
      },
    ],
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach(async (to) => {
  try {
    await getDifyProfile({ silent: true, skipAuthRedirect: true })
    if (to.path === '/login')
      return { path: '/', replace: true }
    return true
  }
  catch (error) {
    if (to.path === '/login')
      return true

    const status = error?.response?.status ?? error?.status
    if (status === 401) {
      try {
        await refreshAccessTokenOrReLogin()
        await getDifyProfile({ silent: true, skipAuthRedirect: true })
        if (to.path === '/login')
          return { path: '/', replace: true }
        return true
      }
      catch {
        return {
          path: '/login',
          query: { redirect: to.fullPath },
          replace: true,
        }
      }
    }

    // Network / 5xx: do not treat as logged-out.
    ElMessage.error(error?.message || '无法验证登录状态，请稍后重试')
    if (to.path === '/login')
      return true
    // Allow first paint / in-app navigation; APIs may still fail until recovery.
    return true
  }
})

export default router
