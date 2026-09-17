<template>
  <div class="connect-page">
    <header class="page-header">
      <button type="button" class="back" @click="$router.push('/datasets')">← 知识库</button>
      <h1>连接外部知识库</h1>
      <p>注册外部检索 API，再绑定外部知识库 ID。对齐 Dify `/datasets/connect`。</p>
    </header>

    <div class="layout">
      <section class="card">
        <div class="card-head">
          <h2>外部知识 API</h2>
          <el-button size="small" type="primary" @click="openApiModal()">添加 API</el-button>
        </div>
        <el-table v-loading="apiLoading" :data="apis" empty-text="暂无外部 API">
          <el-table-column prop="name" label="名称" min-width="120" />
          <el-table-column label="Endpoint" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.settings?.endpoint || '—' }}</template>
          </el-table-column>
          <el-table-column label="绑定" width="80">
            <template #default="{ row }">{{ row.dataset_bindings?.length || 0 }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openApiModal(row)">编辑</el-button>
              <el-button link type="danger" @click="removeApi(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="card">
        <h2>连接知识库</h2>
        <el-form label-position="top" class="form">
          <el-form-item label="外部知识 API" required>
            <el-select v-model="form.apiId" placeholder="选择已注册 API" style="width: 100%">
              <el-option
                v-for="item in apis"
                :key="item.id"
                :label="item.name"
                :value="item.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="外部知识库 ID" required>
            <el-input v-model="form.externalKnowledgeId" placeholder="外部服务中的 knowledge id" />
          </el-form-item>
          <el-form-item label="显示名称" required>
            <el-input v-model="form.name" maxlength="40" show-word-limit />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="form.description" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item label="Top K">
            <el-input-number v-model="form.topK" :min="1" :max="20" />
          </el-form-item>
          <el-form-item label="Score 阈值">
            <el-switch v-model="form.scoreEnabled" />
            <el-input-number
              v-if="form.scoreEnabled"
              v-model="form.scoreThreshold"
              :min="0"
              :max="1"
              :step="0.05"
              style="margin-left: 8px"
            />
          </el-form-item>
          <el-button type="primary" :loading="connecting" @click="connect">连接并创建</el-button>
        </el-form>
      </section>
    </div>

    <el-dialog v-model="apiModalOpen" :title="editingApi ? '编辑外部 API' : '添加外部 API'" width="480px">
      <el-form label-position="top">
        <el-form-item label="名称" required>
          <el-input v-model="apiForm.name" maxlength="40" />
        </el-form-item>
        <el-form-item label="Endpoint" required>
          <el-input v-model="apiForm.endpoint" placeholder="https://..." />
        </el-form-item>
        <el-form-item label="API Key" required>
          <el-input v-model="apiForm.api_key" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="apiModalOpen = false">取消</el-button>
        <el-button type="primary" :loading="apiSaving" @click="saveApi">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  checkExternalKnowledgeApiUsage,
  createExternalKnowledgeApi,
  createExternalKnowledgeBase,
  deleteExternalKnowledgeApi,
  fetchExternalKnowledgeApis,
  updateExternalKnowledgeApi,
} from '@/features/datasets/api/difyDatasetsApi.js'
import { useDatasetStore } from '@/features/datasets/state/useDatasetStore.js'

const router = useRouter()
const store = useDatasetStore()
const apis = ref([])
const apiLoading = ref(false)
const connecting = ref(false)
const apiModalOpen = ref(false)
const apiSaving = ref(false)
const editingApi = ref(null)

const form = reactive({
  apiId: '',
  externalKnowledgeId: '',
  name: '',
  description: '',
  topK: 4,
  scoreEnabled: false,
  scoreThreshold: 0.5,
})

const apiForm = reactive({
  name: '',
  endpoint: '',
  api_key: '',
})

async function loadApis() {
  apiLoading.value = true
  try {
    const res = await fetchExternalKnowledgeApis({ limit: 50 })
    apis.value = res.data || res.items || []
    if (!form.apiId && apis.value.length)
      form.apiId = apis.value[0].id
  }
  catch (e) {
    ElMessage.error(e.message || '外部 API 列表加载失败')
  }
  finally {
    apiLoading.value = false
  }
}

function openApiModal(row = null) {
  editingApi.value = row
  apiForm.name = row?.name || ''
  apiForm.endpoint = row?.settings?.endpoint || ''
  apiForm.api_key = row?.settings?.api_key || ''
  apiModalOpen.value = true
}

async function saveApi() {
  if (!apiForm.name.trim() || !apiForm.endpoint.trim() || !apiForm.api_key.trim()) {
    ElMessage.warning('请填写完整 API 信息')
    return
  }
  apiSaving.value = true
  try {
    const payload = {
      name: apiForm.name.trim(),
      endpoint: apiForm.endpoint.trim(),
      api_key: apiForm.api_key.trim(),
    }
    if (editingApi.value)
      await updateExternalKnowledgeApi(editingApi.value.id, payload)
    else
      await createExternalKnowledgeApi(payload)
    ElMessage.success('已保存')
    apiModalOpen.value = false
    await loadApis()
  }
  catch (e) {
    ElMessage.error(e.message || '保存失败')
  }
  finally {
    apiSaving.value = false
  }
}

async function removeApi(row) {
  try {
    try {
      const used = await checkExternalKnowledgeApiUsage(row.id)
      if (used?.is_using)
        await ElMessageBox.confirm(`该 API 正被 ${used.count || ''} 个知识库使用，确认删除？`, '删除确认', { type: 'warning' })
      else
        await ElMessageBox.confirm(`确认删除「${row.name}」？`, '删除确认', { type: 'warning' })
    }
    catch (e) {
      if (e === 'cancel')
        return
      await ElMessageBox.confirm(`确认删除「${row.name}」？`, '删除确认', { type: 'warning' })
    }
    await deleteExternalKnowledgeApi(row.id)
    ElMessage.success('已删除')
    await loadApis()
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
}

async function connect() {
  if (!form.apiId || !form.externalKnowledgeId.trim() || !form.name.trim()) {
    ElMessage.warning('请填写 API、外部知识库 ID 与名称')
    return
  }
  connecting.value = true
  try {
    const created = await createExternalKnowledgeBase({
      name: form.name.trim(),
      description: form.description,
      external_knowledge_api_id: form.apiId,
      external_knowledge_id: form.externalKnowledgeId.trim(),
      provider: 'external',
      external_retrieval_model: {
        top_k: form.topK,
        score_threshold: form.scoreThreshold,
        score_threshold_enabled: form.scoreEnabled,
      },
    })
    await store.loadDatasets()
    ElMessage.success('已连接外部知识库')
    router.push(`/datasets/${created.id}/hitTesting`)
  }
  catch (e) {
    ElMessage.error(e.message || '连接失败')
  }
  finally {
    connecting.value = false
  }
}

onMounted(loadApis)
</script>

<style scoped>
.connect-page {
  padding: 20px 24px 40px;
  box-sizing: border-box;
  background: #f8fafc;
  min-height: 100%;
}
.back {
  border: none;
  background: transparent;
  color: #667085;
  cursor: pointer;
  font-size: 12px;
  padding: 0;
  margin-bottom: 8px;
}
.page-header h1 {
  margin: 0;
  font-size: 22px;
  color: #101828;
}
.page-header p {
  margin: 6px 0 0;
  font-size: 13px;
  color: #667085;
}
.layout {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 16px;
  margin-top: 16px;
}
@media (max-width: 960px) {
  .layout { grid-template-columns: 1fr; }
}
.card {
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  padding: 16px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.card h2 {
  margin: 0 0 12px;
  font-size: 16px;
}
.form { max-width: 480px; }
</style>
