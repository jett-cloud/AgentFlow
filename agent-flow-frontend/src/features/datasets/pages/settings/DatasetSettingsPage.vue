<template>
  <div class="settings-page" v-loading="loading">
    <header class="page-header">
      <div>
        <h1>知识库设置</h1>
        <p>基础信息、索引与检索配置。对齐 Dify settings。</p>
      </div>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </header>

    <el-form label-position="top" class="form">
      <el-form-item label="名称" required>
        <el-input v-model="form.name" maxlength="40" show-word-limit />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="3" />
      </el-form-item>

      <template v-if="!isExternal">
        <el-form-item label="索引方式">
          <el-radio-group v-model="form.indexing_technique">
            <el-radio value="high_quality">高质量</el-radio>
            <el-radio value="economy">经济</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="form.indexing_technique === 'high_quality'" label="Embedding 模型">
          <el-select v-model="embeddingKey" filterable placeholder="选择 Embedding 模型" style="width: 100%">
            <el-option
              v-for="m in embeddingModels"
              :key="`${m.provider}/${m.model}`"
              :label="`${m.providerLabel} / ${m.label}`"
              :value="`${m.provider}::${m.model}`"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="检索方法">
          <el-select v-model="form.retrieval_model.search_method" style="width: 100%">
            <el-option label="向量检索" value="semantic_search" />
            <el-option label="全文检索" value="full_text_search" />
            <el-option label="混合检索" value="hybrid_search" />
          </el-select>
        </el-form-item>
        <el-form-item label="Top K">
          <el-input-number v-model="form.retrieval_model.top_k" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="Score 阈值">
          <el-switch v-model="form.retrieval_model.score_threshold_enabled" />
          <el-input-number
            v-if="form.retrieval_model.score_threshold_enabled"
            v-model="form.retrieval_model.score_threshold"
            :min="0"
            :max="1"
            :step="0.05"
            style="margin-left: 8px"
          />
        </el-form-item>
        <el-form-item label="Rerank">
          <el-switch v-model="form.retrieval_model.reranking_enable" />
          <el-select
            v-if="form.retrieval_model.reranking_enable"
            v-model="rerankKey"
            filterable
            clearable
            placeholder="选择 Rerank 模型"
            style="width: 100%; margin-top: 8px"
          >
            <el-option
              v-for="m in rerankModels"
              :key="`${m.provider}/${m.model}`"
              :label="`${m.providerLabel} / ${m.label}`"
              :value="`${m.provider}::${m.model}`"
            />
          </el-select>
        </el-form-item>
      </template>

      <template v-else>
        <el-alert type="info" :closable="false" title="外部知识库仅支持调整检索 Top K / Score" />
        <el-form-item label="Top K">
          <el-input-number v-model="externalTopK" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="Score 阈值">
          <el-switch v-model="externalScoreEnabled" />
          <el-input-number
            v-if="externalScoreEnabled"
            v-model="externalScore"
            :min="0"
            :max="1"
            :step="0.05"
            style="margin-left: 8px"
          />
        </el-form-item>
      </template>
    </el-form>

    <section v-if="!isExternal" class="meta-card">
      <div class="meta-head">
        <div>
          <h2>元数据</h2>
          <p>定义字段后可批量写入文档，并在知识检索节点中按类型过滤。</p>
        </div>
        <el-button type="primary" size="small" @click="openCreateMeta">添加字段</el-button>
      </div>
      <div class="built-in-row">
        <span>内置元数据</span>
        <el-switch
          :model-value="builtInEnabled"
          :loading="togglingBuiltIn"
          @change="onBuiltInChange"
        />
      </div>
      <ul v-if="builtInEnabled && builtInFields.length" class="built-in-list">
        <li v-for="field in builtInFields" :key="field.name">
          {{ field.name }}
          <span class="type">{{ typeLabel(field.type) }}</span>
        </li>
      </ul>
      <el-table :data="metadataFields" size="small" empty-text="暂无自定义字段">
        <el-table-column prop="name" label="字段名" min-width="140" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ typeLabel(row.type) }}</template>
        </el-table-column>
        <el-table-column label="文档数" width="80">
          <template #default="{ row }">{{ row.count ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button link type="primary" @click="renameMeta(row)">重命名</el-button>
            <el-button link type="danger" @click="removeMeta(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="createOpen" title="添加元数据" width="420px">
      <el-form label-position="top">
        <el-form-item label="字段名" required>
          <el-input v-model="createForm.name" placeholder="例如 category" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="createForm.type" style="width: 100%">
            <el-option
              v-for="item in METADATA_TYPES"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreateMeta">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createDatasetMetadata,
  deleteDatasetMetadata,
  fetchBuiltInMetadataFields,
  fetchDatasetDetail,
  fetchDatasetMetadata,
  renameDatasetMetadata,
  setBuiltInMetadata,
  updateDataset,
} from '@/features/datasets/api/difyDatasetsApi.js'
import { fetchModelsByType } from '@/features/integrations/api/difyModelsApi.js'
import { DEFAULT_RETRIEVAL_MODEL } from '@/features/datasets/model/createDocumentPayload.js'
import { METADATA_TYPES, metadataNameError } from '@/features/datasets/model/metadataFields.js'
import { flattenModelCatalog, isRerankConfigValid, parseRerankKey, rerankModelKey } from '@/features/datasets/model/retrievalModel.js'
import { useDatasetStore } from '@/features/datasets/state/useDatasetStore.js'

const route = useRoute()
const store = useDatasetStore()
const loading = ref(false)
const saving = ref(false)
const embeddingModels = ref([])
const rerankModels = ref([])
const embeddingKey = ref('')
const isExternal = ref(false)
const externalTopK = ref(4)
const externalScoreEnabled = ref(false)
const externalScore = ref(0.5)
const metadataFields = ref([])
const builtInEnabled = ref(false)
const builtInFields = ref([])
const togglingBuiltIn = ref(false)
const createOpen = ref(false)
const creating = ref(false)
const createForm = reactive({ name: '', type: 'string' })

const form = reactive({
  name: '',
  description: '',
  indexing_technique: 'high_quality',
  retrieval_model: { ...DEFAULT_RETRIEVAL_MODEL },
})

const rerankKey = computed({
  get() {
    return rerankModelKey(form.retrieval_model)
  },
  set(key) {
    form.retrieval_model.reranking_model = parseRerankKey(key)
  },
})

function datasetId() {
  return route.params.datasetId
}

function typeLabel(type) {
  return METADATA_TYPES.find(item => item.value === type)?.label || type || '文本'
}

async function loadMetadata() {
  try {
    const res = await fetchDatasetMetadata(datasetId())
    metadataFields.value = res.doc_metadata || res.data?.doc_metadata || []
    builtInEnabled.value = Boolean(res.built_in_field_enabled ?? res.data?.built_in_field_enabled)
  }
  catch {
    metadataFields.value = []
  }
}

async function loadBuiltInFields() {
  try {
    const res = await fetchBuiltInMetadataFields()
    builtInFields.value = res.fields || res.data?.fields || []
  }
  catch {
    builtInFields.value = []
  }
}

function openCreateMeta() {
  createForm.name = ''
  createForm.type = 'string'
  createOpen.value = true
}

async function submitCreateMeta() {
  const name = createForm.name.trim()
  const error = metadataNameError(name)
  if (error) {
    ElMessage.warning(error)
    return
  }
  creating.value = true
  try {
    await createDatasetMetadata(datasetId(), { type: createForm.type, name })
    ElMessage.success('已添加')
    createOpen.value = false
    await loadMetadata()
  }
  catch (e) {
    ElMessage.error(e.message || '添加失败')
  }
  finally {
    creating.value = false
  }
}

async function renameMeta(row) {
  try {
    const { value } = await ElMessageBox.prompt('新字段名', '重命名元数据', {
      inputValue: row.name,
      inputPattern: /^[a-z][a-z0-9_]*$/,
      inputErrorMessage: '字段名须以小写字母开头，仅含小写字母、数字和下划线',
    })
    const name = value.trim()
    const error = metadataNameError(name)
    if (error) {
      ElMessage.warning(error)
      return
    }
    await renameDatasetMetadata(datasetId(), row.id, name)
    ElMessage.success('已重命名')
    await loadMetadata()
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
}

async function removeMeta(row) {
  try {
    await ElMessageBox.confirm(`删除字段「${row.name}」会从文档中移除对应值。`, '删除元数据', { type: 'warning' })
    await deleteDatasetMetadata(datasetId(), row.id)
    ElMessage.success('已删除')
    await loadMetadata()
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
}

async function onBuiltInChange(enabled) {
  togglingBuiltIn.value = true
  try {
    await setBuiltInMetadata(datasetId(), enabled)
    builtInEnabled.value = enabled
    ElMessage.success(enabled ? '已开启内置元数据' : '已关闭内置元数据')
  }
  catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
  finally {
    togglingBuiltIn.value = false
  }
}

async function loadEmbeddingModels() {
  try {
    const res = await fetchModelsByType('text-embedding')
    embeddingModels.value = flattenModelCatalog(res)
  }
  catch {
    embeddingModels.value = []
  }
}

async function loadRerankModels() {
  try {
    const res = await fetchModelsByType('rerank')
    rerankModels.value = flattenModelCatalog(res)
  }
  catch {
    rerankModels.value = []
  }
}

async function load() {
  loading.value = true
  try {
    const ds = await fetchDatasetDetail(datasetId())
    store.currentDataset = ds
    isExternal.value = ds.provider === 'external'
    form.name = ds.name || ''
    form.description = ds.description || ''
    form.indexing_technique = ds.indexing_technique || 'high_quality'
    const rm = ds.retrieval_model_dict || ds.retrieval_model || {}
    form.retrieval_model = {
      ...DEFAULT_RETRIEVAL_MODEL,
      ...rm,
      reranking_model: {
        ...DEFAULT_RETRIEVAL_MODEL.reranking_model,
        ...(rm.reranking_model || {}),
      },
    }
    if (ds.embedding_model_provider && ds.embedding_model)
      embeddingKey.value = `${ds.embedding_model_provider}::${ds.embedding_model}`
    if (isExternal.value) {
      externalTopK.value = rm.top_k ?? 4
      externalScoreEnabled.value = !!rm.score_threshold_enabled
      externalScore.value = rm.score_threshold ?? 0.5
    }
  }
  catch (e) {
    ElMessage.error(e.message || '加载设置失败')
  }
  finally {
    loading.value = false
  }
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入名称')
    return
  }
  if (!isExternal.value && !isRerankConfigValid(form.retrieval_model)) {
    ElMessage.warning('请选择 Rerank 模型')
    return
  }
  saving.value = true
  try {
    if (isExternal.value) {
      await updateDataset(datasetId(), {
        name: form.name.trim(),
        description: form.description,
        external_retrieval_model: {
          top_k: externalTopK.value,
          score_threshold: externalScore.value,
          score_threshold_enabled: externalScoreEnabled.value,
        },
      })
    }
    else {
      const [provider, model] = embeddingKey.value ? embeddingKey.value.split('::') : ['', '']
      const body = {
        name: form.name.trim(),
        description: form.description,
        indexing_technique: form.indexing_technique,
        retrieval_model: { ...form.retrieval_model },
      }
      if (form.indexing_technique === 'high_quality' && provider && model) {
        body.embedding_model = model
        body.embedding_model_provider = provider
      }
      await updateDataset(datasetId(), body)
    }
    ElMessage.success('已保存')
    await load()
  }
  catch (e) {
    ElMessage.error(e.message || '保存失败')
  }
  finally {
    saving.value = false
  }
}

onMounted(async () => {
  await Promise.all([load(), loadEmbeddingModels(), loadRerankModels(), loadMetadata(), loadBuiltInFields()])
})

watch(() => route.params.datasetId, async () => {
  await Promise.all([load(), loadMetadata()])
})
</script>

<style scoped>
.settings-page {
  padding: 20px 24px 40px;
  box-sizing: border-box;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}
.page-header h1 {
  margin: 0;
  font-size: 20px;
  color: #101828;
}
.page-header p {
  margin: 6px 0 0;
  font-size: 13px;
  color: #667085;
}
.form {
  max-width: 560px;
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  padding: 16px 18px;
}
.meta-card {
  max-width: 720px;
  margin-top: 16px;
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  padding: 16px 18px;
}
.meta-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}
.meta-head h2 {
  margin: 0;
  font-size: 16px;
  color: #101828;
}
.meta-head p {
  margin: 4px 0 0;
  font-size: 12px;
  color: #667085;
}
.built-in-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
  color: #344054;
}
.built-in-list {
  margin: 0 0 12px;
  padding: 0;
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: #667085;
}
.built-in-list li {
  background: #f2f4f7;
  border-radius: 999px;
  padding: 2px 8px;
}
.built-in-list .type {
  color: #98a2b3;
}
</style>
