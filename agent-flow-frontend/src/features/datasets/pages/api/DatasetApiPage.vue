<template>
  <div class="api-page" v-loading="loading">
    <header class="page-header">
      <div>
        <h1>API</h1>
        <p>启用知识库 Service API、管理密钥与关联应用。对齐 Dify sidebar extra-info。</p>
      </div>
    </header>

    <section class="card">
      <div class="row">
        <div>
          <h2>Service API</h2>
          <p class="hint">开启后可通过 API 访问本知识库文档能力。</p>
        </div>
        <el-switch
          :model-value="enableApi"
          :loading="toggling"
          @change="onToggleApi"
        />
      </div>
      <div class="base-url">
        <span>API Base URL</span>
        <code>{{ apiBaseUrl || '—' }}</code>
        <el-button
          v-if="apiBaseUrl"
          link
          type="primary"
          @click="copy(apiBaseUrl)"
        >
          复制
        </el-button>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>API Keys（工作区级）</h2>
        <el-button type="primary" size="small" :loading="creatingKey" @click="createKey">
          创建密钥
        </el-button>
      </div>
      <el-table :data="apiKeys" empty-text="暂无密钥">
        <el-table-column label="密钥" min-width="220">
          <template #default="{ row }">
            <code>{{ maskToken(row.token) }}</code>
            <el-button link type="primary" @click="copy(row.token)">复制</el-button>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="最近使用" width="180">
          <template #default="{ row }">{{ formatTime(row.last_used_at) || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button link type="danger" @click="removeKey(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="card">
      <h2>关联应用（{{ relatedTotal }}）</h2>
      <el-table :data="relatedApps" empty-text="暂无关联应用">
        <el-table-column prop="name" label="应用" min-width="160" />
        <el-table-column prop="mode" label="类型" width="120" />
        <el-table-column label="ID" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.id }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createDatasetApiKey,
  deleteDatasetApiKey,
  disableDatasetServiceApi,
  enableDatasetServiceApi,
  fetchDatasetApiBaseInfo,
  fetchDatasetApiKeys,
  fetchDatasetDetail,
  fetchDatasetRelatedApps,
} from '@/features/datasets/api/difyDatasetsApi.js'
import { useDatasetStore } from '@/features/datasets/state/useDatasetStore.js'

const route = useRoute()
const store = useDatasetStore()
const loading = ref(false)
const toggling = ref(false)
const creatingKey = ref(false)
const enableApi = ref(false)
const apiBaseUrl = ref('')
const apiKeys = ref([])
const relatedApps = ref([])
const relatedTotal = ref(0)

function datasetId() {
  return route.params.datasetId
}

function maskToken(token) {
  const t = String(token || '')
  if (t.length <= 8)
    return t
  return `${t.slice(0, 4)}…${t.slice(-4)}`
}

function formatTime(value) {
  if (!value)
    return ''
  const n = Number(value)
  const date = Number.isFinite(n) && n < 1e12 ? new Date(n * 1000) : new Date(value)
  if (Number.isNaN(date.getTime()))
    return String(value)
  return date.toLocaleString()
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  }
  catch {
    ElMessage.error('复制失败')
  }
}

async function load() {
  loading.value = true
  try {
    const [ds, base, keys, apps] = await Promise.all([
      fetchDatasetDetail(datasetId()),
      fetchDatasetApiBaseInfo().catch(() => null),
      fetchDatasetApiKeys().catch(() => ({ data: [] })),
      fetchDatasetRelatedApps(datasetId()).catch(() => ({ data: [], total: 0 })),
    ])
    store.currentDataset = ds
    enableApi.value = !!ds.enable_api
    apiBaseUrl.value = base?.api_base_url || ''
    apiKeys.value = keys?.data || []
    relatedApps.value = apps?.data || []
    relatedTotal.value = apps?.total ?? relatedApps.value.length
  }
  catch (e) {
    ElMessage.error(e.message || '加载失败')
  }
  finally {
    loading.value = false
  }
}

async function onToggleApi(next) {
  toggling.value = true
  try {
    if (next)
      await enableDatasetServiceApi(datasetId())
    else
      await disableDatasetServiceApi(datasetId())
    enableApi.value = !!next
    ElMessage.success(next ? '已启用 API' : '已关闭 API')
    const ds = await fetchDatasetDetail(datasetId())
    store.currentDataset = ds
    enableApi.value = !!ds.enable_api
  }
  catch (e) {
    ElMessage.error(e.message || '切换失败')
  }
  finally {
    toggling.value = false
  }
}

async function createKey() {
  creatingKey.value = true
  try {
    const created = await createDatasetApiKey()
    ElMessage.success('已创建密钥')
    if (created?.token)
      await copy(created.token)
    await load()
  }
  catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
  finally {
    creatingKey.value = false
  }
}

async function removeKey(row) {
  try {
    await ElMessageBox.confirm('确认删除该 API Key？', '删除密钥', { type: 'warning' })
    await deleteDatasetApiKey(row.id)
    ElMessage.success('已删除')
    await load()
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
}

onMounted(load)
watch(() => route.params.datasetId, load)
</script>

<style scoped>
.api-page {
  padding: 20px 24px 40px;
  box-sizing: border-box;
}
.page-header h1 {
  margin: 0;
  font-size: 20px;
  color: #101828;
}
.page-header p {
  margin: 6px 0 16px;
  font-size: 13px;
  color: #667085;
}
.card {
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 14px;
}
.card h2 {
  margin: 0 0 8px;
  font-size: 15px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.card-head h2 { margin: 0; }
.row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.hint {
  margin: 0;
  font-size: 12px;
  color: #667085;
}
.base-url {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
  color: #475467;
}
.base-url code {
  background: #f2f4f7;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
}
</style>
