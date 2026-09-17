// src/stores/useModelStore.js
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { DEFAULT_LLM_MODEL_TYPE, fetchModelProviders, fetchModelsByType } from '@/features/integrations/api/difyModelsApi.js'

/**
 * 1:1 对标 Dify 官方源码: web/app/components/header/account-setting/model-provider-page/declarations.ts
 */
export const ModelFeatureEnum = {
  VISION: 'vision',
  TOOL_CALL: 'tool-call',
  MULTI_TOOL_CALL: 'multi-tool-call',
  AGENT_THOUGHT: 'agent-thought',
  STRUCTURED_OUTPUT: 'structured-output',
}

function normalizeProviders(payload) {
  const data = payload?.data || payload
  if (Array.isArray(data)) {
    return data.map((item) => ({
      provider: item.provider || item.provider_name || 'unknown',
      label: item.label?.zh_Hans || item.label?.en_US || item.label || item.provider || 'Provider',
      icon_small: item.icon_small || null,
      icon_small_dark: item.icon_small_dark || null,
      models: (item.models || []).map((model) => ({
        model: model.model || model.model_name,
        label: model.label?.zh_Hans || model.label?.en_US || model.label || model.model,
        features: model.features || [],
        mode: model.model_properties?.mode || model.mode || 'chat',
      })).filter(model => model.model),
    })).filter(item => item.models.length)
  }
  return []
}

/**
 * Keep Dify ModelProvider shape as-is (see web .../model-provider-page/declarations.ts).
 * Only normalize the provider key; do not flatten labels/icons.
 */
function normalizeProviderCatalog(payload) {
  const data = payload?.data || payload
  if (!Array.isArray(data)) return []
  return data
    .map(item => ({
      ...item,
      provider: item.provider || item.provider_name || '',
      label: item.label || item.provider || '',
      supported_model_types: item.supported_model_types || [],
      configurate_methods: item.configurate_methods || [],
      provider_credential_schema: item.provider_credential_schema || null,
      custom_configuration: item.custom_configuration || { status: 'no-configure' },
      system_configuration: item.system_configuration || { enabled: false, quota_configurations: [] },
      icon_small: item.icon_small || null,
    }))
    .filter(item => item.provider)
}

export const useModelStore = defineStore('modelStore', () => {
  const providers = ref([])
  const providerCatalog = ref([])
  const loading = ref(false)
  const loaded = ref(false)
  const loadError = ref('')
  const fromFallback = ref(false)

  const allModels = computed(() => {
    const list = []
    providers.value.forEach((p) => {
      p.models.forEach((m) => {
        list.push({
          provider: p.provider,
          providerLabel: p.label,
          model: m.model,
          label: m.label,
          features: m.features || [],
          mode: m.mode || 'chat',
        })
      })
    })
    return list
  })

  const hasConfiguredModels = computed(() => allModels.value.length > 0)

  const getModelSpec = (modelName, providerName = '') => {
    if (!modelName) return null
    if (providerName)
      return allModels.value.find(m => m.model === modelName && m.provider === providerName) || null
    return allModels.value.find(m => m.model === modelName) || null
  }

  /** Resolve provider row from model list or catalog (for icons / labels). */
  const getProvider = (providerName = '') => {
    if (!providerName) return null
    return providers.value.find(item => item.provider === providerName)
      || providerCatalog.value.find(item => item.provider === providerName)
      || null
  }

  const fetchModelList = async (force = false) => {
    if (loaded.value && !force) return providers.value
    loading.value = true
    if (!loadError.value || force)
      loadError.value = ''
    fromFallback.value = false
    try {
      const response = await fetchModelsByType(DEFAULT_LLM_MODEL_TYPE)
      providers.value = normalizeProviders(response)
      loaded.value = true
    } catch (e) {
      loadError.value = e.message || '模型列表加载失败'
      providers.value = []
      loaded.value = true
      console.warn('[ModelStore] 模型列表加载失败', e)
    } finally {
      loading.value = false
    }
    return providers.value
  }

  const fetchProviderCatalog = async (force = false) => {
    if (providerCatalog.value.length && !force) return providerCatalog.value
    try {
      const response = await fetchModelProviders()
      providerCatalog.value = normalizeProviderCatalog(response)
      if (!providerCatalog.value.length)
        loadError.value = loadError.value || '工作区暂无模型提供商（需先在 Dify 安装模型插件）'
    } catch (e) {
      console.warn('[ModelStore] 提供商目录加载失败', e)
      providerCatalog.value = []
      loadError.value = e.message || '提供商目录加载失败'
      throw e
    }
    return providerCatalog.value
  }

  /**
   * Align with Dify fetch order:
   * 1) load provider catalog first
   * 2) then load model list by `llm`
   */
  const hydrateModelWorkspace = async (force = false) => {
    await fetchProviderCatalog(force)
    if (!providerCatalog.value.length) {
      providers.value = []
      loaded.value = true
      return { providers: providerCatalog.value, models: providers.value }
    }
    await fetchModelList(force)
    return { providers: providerCatalog.value, models: providers.value }
  }

  return {
    providers,
    providerCatalog,
    allModels,
    hasConfiguredModels,
    loading,
    loaded,
    loadError,
    fromFallback,
    getModelSpec,
    getProvider,
    fetchModelList,
    fetchProviderCatalog,
    hydrateModelWorkspace,
  }
})
