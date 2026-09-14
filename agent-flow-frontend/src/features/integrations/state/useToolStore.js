import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { fetchAllTools } from '@/features/integrations/api/difyToolsApi.js'
import { flattenToolCatalog, toolIdentityMatches } from './toolCatalog.js'

export const useToolStore = defineStore('toolStore', () => {
  const groups = ref({ builtin: [], api: [], workflow: [], mcp: [] })
  const loading = ref(false)
  const loaded = ref(false)
  const loadError = ref('')

  const allTools = computed(() => flattenToolCatalog(groups.value))

  async function fetchTools(force = false) {
    if (loaded.value && !force) return allTools.value
    loading.value = true
    loadError.value = ''
    try {
      groups.value = await fetchAllTools()
      loaded.value = true
    } catch (e) {
      loadError.value = e.message || '工具列表加载失败'
      groups.value = { builtin: [], api: [], workflow: [], mcp: [] }
      loaded.value = true
    } finally {
      loading.value = false
    }
    return allTools.value
  }

  function findTool({ provider_type, provider_id, tool_name }) {
    return allTools.value.find(item => toolIdentityMatches(item, { provider_type, provider_id, tool_name })) || null
  }

  return {
    groups,
    allTools,
    loading,
    loaded,
    loadError,
    fetchTools,
    findTool,
  }
})
