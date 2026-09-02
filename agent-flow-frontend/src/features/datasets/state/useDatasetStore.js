import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  fetchDatasets,
  fetchDatasetDetail,
  fetchRetrievalSetting,
  createEmptyDataset,
  deleteDataset,
} from '@/features/datasets/api/difyDatasetsApi.js'

export const useDatasetStore = defineStore('datasetStore', () => {
  const datasets = ref([])
  const total = ref(0)
  const loading = ref(false)
  const loadError = ref('')
  const retrievalSetting = ref(null)
  const currentDataset = ref(null)

  async function loadDatasets({ page = 1, limit = 50, keyword = '' } = {}) {
    loading.value = true
    loadError.value = ''
    try {
      const response = await fetchDatasets({ page, limit, keyword })
      datasets.value = response.data || response.items || []
      total.value = response.total || datasets.value.length
    }
    catch (e) {
      loadError.value = e.message || '知识库列表加载失败'
      datasets.value = []
      total.value = 0
    }
    finally {
      loading.value = false
    }
    return datasets.value
  }

  async function loadDatasetDetail(datasetId) {
    currentDataset.value = await fetchDatasetDetail(datasetId)
    return currentDataset.value
  }

  async function createEmpty(name) {
    const created = await createEmptyDataset({ name })
    await loadDatasets()
    return created
  }

  async function removeDataset(datasetId) {
    await deleteDataset(datasetId)
    datasets.value = datasets.value.filter(d => d.id !== datasetId)
    total.value = Math.max(0, total.value - 1)
  }

  async function loadRetrievalSetting() {
    try {
      retrievalSetting.value = await fetchRetrievalSetting()
    }
    catch {
      retrievalSetting.value = null
    }
    return retrievalSetting.value
  }

  function findById(id) {
    return datasets.value.find(d => d.id === id) || null
  }

  return {
    datasets,
    total,
    loading,
    loadError,
    retrievalSetting,
    currentDataset,
    loadDatasets,
    loadDatasetDetail,
    createEmpty,
    removeDataset,
    loadRetrievalSetting,
    findById,
  }
})
