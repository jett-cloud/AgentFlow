<template>
  <div class="wizard">
    <header class="wizard-header">
      <button type="button" class="back" @click="goBack">← 返回</button>
      <h1>{{ isAddMode ? '添加文档' : '创建知识库' }}</h1>
      <el-steps :active="step - 1" finish-status="success" align-center class="steps">
        <el-step title="选择数据源" />
        <el-step title="分段与清洗" />
        <el-step title="处理并完成" />
      </el-steps>
    </header>

    <!-- Step 1 -->
    <section v-if="step === 1" class="panel">
      <h2>数据来源</h2>
      <el-radio-group v-model="dataSourceType" class="source-tabs">
        <el-radio-button value="upload_file">导入已有文本</el-radio-button>
        <el-radio-button value="notion_import">Notion</el-radio-button>
        <el-radio-button value="website_crawl">网页</el-radio-button>
      </el-radio-group>

      <div v-if="dataSourceType === 'upload_file'" class="upload-box">
        <el-upload
          drag
          multiple
          :auto-upload="false"
          :show-file-list="false"
          accept=".txt,.md,.mdx,.pdf,.html,.xlsx,.xls,.docx,.csv,.eml,.msg,.pptx,.ppt,.xml,.epub"
          @change="onFileChange"
        >
          <div class="upload-inner">
            <p>拖拽文件到此处，或点击上传</p>
            <p class="hint">支持 PDF / Word / Markdown / TXT / CSV 等</p>
          </div>
        </el-upload>
        <ul v-if="pendingFiles.length" class="file-list">
          <li v-for="(f, i) in pendingFiles" :key="f.uid || i">
            <span>{{ f.name }}</span>
            <span class="size">{{ formatSize(f.size) }}</span>
            <el-button link type="danger" @click="removePending(i)">移除</el-button>
          </li>
        </ul>
      </div>

      <NotionSourcePanel
        v-else-if="dataSourceType === 'notion_import'"
        v-model="notionState"
        :dataset-id="resolvedDatasetIdForSource"
      />

      <WebsiteSourcePanel
        v-else
        v-model="websiteState"
      />

      <div class="footer">
        <el-button type="primary" :disabled="!canGoStep2" @click="goStep2">下一步</el-button>
      </div>
    </section>

    <!-- Step 2 -->
    <section v-else-if="step === 2" class="panel" v-loading="loadingRule">
      <h2>分段与索引设置</h2>

      <el-form label-position="top" class="form">
        <el-form-item label="分段模式">
          <el-radio-group v-model="docForm">
            <el-radio value="text_model">通用</el-radio>
            <el-radio value="hierarchical_model">父子分段</el-radio>
            <el-radio value="qa_model">问答</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="索引方式">
          <el-radio-group v-model="indexingTechnique">
            <el-radio value="high_quality">高质量（推荐，需 Embedding）</el-radio>
            <el-radio value="economy">经济</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="indexingTechnique === 'high_quality'" label="Embedding 模型" required>
          <el-select
            v-model="embeddingKey"
            filterable
            placeholder="选择 Embedding 模型"
            style="width: 100%"
          >
            <el-option
              v-for="m in embeddingModels"
              :key="`${m.provider}/${m.model}`"
              :label="`${m.providerLabel} / ${m.label}`"
              :value="`${m.provider}::${m.model}`"
            />
          </el-select>
          <p v-if="!embeddingModels.length" class="hint">
            未检测到 Embedding 模型，请先在
            <RouterLink to="/integrations?tab=models">工作区集成</RouterLink>
            配置。
          </p>
        </el-form-item>

        <el-form-item label="检索方法">
          <el-select v-model="searchMethod" style="width: 100%">
            <el-option label="向量检索" value="semantic_search" />
            <el-option label="全文检索" value="full_text_search" />
            <el-option label="混合检索" value="hybrid_search" />
          </el-select>
        </el-form-item>

        <el-form-item label="Top K">
          <el-input-number v-model="topK" :min="1" :max="20" />
        </el-form-item>

        <el-form-item label="分段标识符">
          <el-input v-model="separator" placeholder="例如 \n\n" />
        </el-form-item>
        <el-form-item label="分段最大长度">
          <el-input-number v-model="maxTokens" :min="50" :max="4000" />
        </el-form-item>
        <el-form-item v-if="docForm !== 'hierarchical_model'" label="分段重叠">
          <el-input-number v-model="chunkOverlap" :min="0" :max="500" />
        </el-form-item>

        <template v-if="docForm === 'hierarchical_model'">
          <el-form-item label="父分段模式">
            <el-radio-group v-model="parentMode">
              <el-radio value="paragraph">段落</el-radio>
              <el-radio value="full-doc">全文</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="子分段标识符">
            <el-input v-model="childSeparator" placeholder="例如 \n" />
          </el-form-item>
          <el-form-item label="子分段最大长度">
            <el-input-number v-model="childMaxTokens" :min="50" :max="4000" />
          </el-form-item>
        </template>

        <el-form-item label="预处理">
          <el-checkbox v-model="removeExtraSpaces">去除多余空格</el-checkbox>
          <el-checkbox v-model="removeUrlsEmails">去除 URL 和邮箱</el-checkbox>
        </el-form-item>

        <el-form-item label="文本语言">
          <el-select v-model="docLanguage" style="width: 100%">
            <el-option label="中文" value="Chinese" />
            <el-option label="English" value="English" />
          </el-select>
        </el-form-item>

        <el-form-item v-if="indexingTechnique === 'high_quality'" label="Rerank">
          <el-switch v-model="rerankEnable" />
          <el-select
            v-if="rerankEnable"
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
      </el-form>

      <div class="preview-block">
        <div class="preview-head">
          <h3>分段预览</h3>
          <el-button size="small" :loading="estimating" @click="runEstimate">预估并预览</el-button>
        </div>
        <p v-if="estimateMeta" class="hint">
          约 {{ estimateMeta.total_segments }} 段
          <template v-if="estimateMeta.tokens != null"> · {{ estimateMeta.tokens }} tokens</template>
        </p>
        <p v-if="estimateError" class="error">{{ estimateError }}</p>
        <ul v-if="estimatePreview.length" class="preview-list">
          <li v-for="(item, i) in estimatePreview" :key="i">
            <strong v-if="item.question">Q {{ item.question }}</strong>
            <pre>{{ item.content || item.answer || '' }}</pre>
          </li>
        </ul>
      </div>

      <div class="footer">
        <el-button @click="step = 1">上一步</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">保存并处理</el-button>
      </div>
    </section>

    <!-- Step 3 -->
    <section v-else class="panel">
      <h2>嵌入处理</h2>
      <p class="hint">文档已提交索引，正在处理…</p>
      <el-table :data="indexingRows" empty-text="暂无进度">
        <el-table-column prop="name" label="文档" min-width="180" />
        <el-table-column label="状态" width="140">
          <template #default="{ row }">{{ row.indexing_status }}</template>
        </el-table-column>
        <el-table-column label="进度" width="160">
          <template #default="{ row }">
            {{ row.completed_segments ?? 0 }} / {{ row.total_segments ?? 0 }}
          </template>
        </el-table-column>
      </el-table>
      <div class="footer">
        <el-button type="primary" @click="goDocuments">进入知识库</el-button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { uploadConsoleFile } from '@/shared/media/difyFilesApi.js'
import {
  createDocument,
  createFirstDocument,
  fetchBatchIndexingStatus,
  fetchDefaultProcessRule,
  fetchIndexingEstimate,
} from '@/features/datasets/api/difyDatasetsApi.js'
import { fetchModelsByType } from '@/features/integrations/api/difyModelsApi.js'
import {
  buildFileCreateDocumentPayload,
  buildIndexingEstimateBody,
  buildNotionCreateDocumentPayload,
  buildNotionInfoList,
  buildWebsiteCreateDocumentPayload,
  buildWizardProcessRule,
  DEFAULT_CRAWL_OPTIONS,
  DEFAULT_RETRIEVAL_MODEL,
  isTerminalIndexingStatus,
  normalizeProcessRule,
} from '@/features/datasets/model/createDocumentPayload.js'
import { flattenModelCatalog, isRerankConfigValid, parseRerankKey } from '@/features/datasets/model/retrievalModel.js'
import { useDatasetStore } from '@/features/datasets/state/useDatasetStore.js'
import NotionSourcePanel from './sources/NotionSourcePanel.vue'
import WebsiteSourcePanel from './sources/WebsiteSourcePanel.vue'

const props = defineProps({
  datasetId: { type: String, default: '' },
})

const route = useRoute()
const router = useRouter()
const datasetStore = useDatasetStore()

const step = ref(1)
const dataSourceType = ref('upload_file')
const pendingFiles = ref([])
const notionState = ref({ credentialId: '', pages: [] })
const websiteState = ref({
  provider: 'jinareader',
  url: '',
  jobId: '',
  pages: [],
  selectedUrls: [],
  options: { ...DEFAULT_CRAWL_OPTIONS },
})
const docForm = ref('text_model')
const indexingTechnique = ref('high_quality')
const embeddingKey = ref('')
const embeddingModels = ref([])
const rerankModels = ref([])
const rerankEnable = ref(false)
const rerankKey = ref('')
const searchMethod = ref('semantic_search')
const topK = ref(4)
const separator = ref('\n\n')
const maxTokens = ref(1024)
const chunkOverlap = ref(50)
const parentMode = ref('paragraph')
const childSeparator = ref('\n')
const childMaxTokens = ref(512)
const removeExtraSpaces = ref(true)
const removeUrlsEmails = ref(false)
const docLanguage = ref('Chinese')
const uploadedFileIds = ref([])
const estimating = ref(false)
const estimateMeta = ref(null)
const estimatePreview = ref([])
const estimateError = ref('')
const loadingRule = ref(false)
const creating = ref(false)
const resultDatasetId = ref('')
const resultBatch = ref('')
const indexingRows = ref([])
let pollTimer = null

const isAddMode = computed(() => Boolean(props.datasetId || route.params.datasetId))
const resolvedDatasetIdForSource = computed(() => props.datasetId || route.params.datasetId || '')

const canGoStep2 = computed(() => {
  if (dataSourceType.value === 'upload_file')
    return pendingFiles.value.length > 0
  if (dataSourceType.value === 'notion_import')
    return Boolean(notionState.value.credentialId && notionState.value.pages?.length)
  if (dataSourceType.value === 'website_crawl') {
    return Boolean(
      websiteState.value.jobId
      && websiteState.value.selectedUrls?.length,
    )
  }
  return false
})

function resolvedDatasetId() {
  return props.datasetId || route.params.datasetId || resultDatasetId.value
}

function goBack() {
  if (isAddMode.value)
    router.push(`/datasets/${resolvedDatasetId()}/documents`)
  else
    router.push('/datasets')
}

function goDocuments() {
  const id = resolvedDatasetId()
  if (id)
    router.push(`/datasets/${id}/documents`)
  else
    router.push('/datasets')
}

function formatSize(size) {
  if (!size)
    return ''
  if (size < 1024)
    return `${size} B`
  if (size < 1024 * 1024)
    return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function onFileChange(uploadFile) {
  const raw = uploadFile.raw
  if (!raw)
    return
  pendingFiles.value.push(raw)
  uploadedFileIds.value = []
}

async function loadEmbeddingModels() {
  try {
    const res = await fetchModelsByType('text-embedding')
    embeddingModels.value = flattenModelCatalog(res)
    if (!embeddingKey.value && embeddingModels.value.length)
      embeddingKey.value = `${embeddingModels.value[0].provider}::${embeddingModels.value[0].model}`
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

async function loadProcessRule() {
  loadingRule.value = true
  try {
    const raw = await fetchDefaultProcessRule()
    const rule = normalizeProcessRule(raw)
    separator.value = rule.rules.segmentation.separator
    maxTokens.value = rule.rules.segmentation.max_tokens
    chunkOverlap.value = rule.rules.segmentation.chunk_overlap
    const preprocess = rule.rules.pre_processing_rules || []
    removeExtraSpaces.value = preprocess.find(item => item.id === 'remove_extra_spaces')?.enabled !== false
    removeUrlsEmails.value = Boolean(preprocess.find(item => item.id === 'remove_urls_emails')?.enabled)
    if (rule.rules.parent_mode)
      parentMode.value = rule.rules.parent_mode
    if (rule.rules.subchunk_segmentation) {
      childSeparator.value = rule.rules.subchunk_segmentation.separator || childSeparator.value
      childMaxTokens.value = rule.rules.subchunk_segmentation.max_tokens ?? childMaxTokens.value
    }
  }
  catch {
    /* keep wizard defaults */
  }
  finally {
    loadingRule.value = false
  }
}

async function goStep2() {
  if (!canGoStep2.value) {
    if (dataSourceType.value === 'upload_file')
      ElMessage.warning('请先选择文件')
    else if (dataSourceType.value === 'notion_import')
      ElMessage.warning('请选择 Notion 凭证与页面')
    else
      ElMessage.warning('请先完成网页爬取并选择页面')
    return
  }
  step.value = 2
  estimateMeta.value = null
  estimatePreview.value = []
  estimateError.value = ''
  await Promise.all([loadProcessRule(), loadEmbeddingModels(), loadRerankModels()])
}

function currentProcessRule() {
  return buildWizardProcessRule({
    docForm: docForm.value,
    separator: separator.value,
    maxTokens: maxTokens.value,
    chunkOverlap: chunkOverlap.value,
    removeExtraSpaces: removeExtraSpaces.value,
    removeUrlsEmails: removeUrlsEmails.value,
    parentMode: parentMode.value,
    childSeparator: childSeparator.value,
    childMaxTokens: childMaxTokens.value,
  })
}

function currentRetrievalModel() {
  const rerank = parseRerankKey(rerankKey.value)
  return {
    ...DEFAULT_RETRIEVAL_MODEL,
    search_method: searchMethod.value,
    top_k: topK.value,
    reranking_enable: rerankEnable.value,
    reranking_model: rerank,
  }
}

function removePending(index) {
  pendingFiles.value.splice(index, 1)
  uploadedFileIds.value = []
}

async function ensureUploadedFiles() {
  if (dataSourceType.value !== 'upload_file')
    return []
  if (uploadedFileIds.value.length === pendingFiles.value.length && uploadedFileIds.value.length)
    return uploadedFileIds.value
  const ids = []
  for (const file of pendingFiles.value) {
    const uploaded = await uploadConsoleFile(file, { source: 'datasets' })
    const id = uploaded?.id
    if (!id)
      throw new Error(`文件 ${file.name} 上传失败`)
    ids.push(id)
  }
  uploadedFileIds.value = ids
  return ids
}

async function runEstimate() {
  estimating.value = true
  estimateError.value = ''
  try {
    const fileIds = await ensureUploadedFiles()
    const body = buildIndexingEstimateBody({
      dataSourceType: dataSourceType.value,
      fileIds,
      notionInfoList: dataSourceType.value === 'notion_import'
        ? buildNotionInfoList(notionState.value.pages, notionState.value.credentialId)
        : undefined,
      websiteInfoList: dataSourceType.value === 'website_crawl'
        ? {
            provider: websiteState.value.provider,
            job_id: websiteState.value.jobId,
            urls: websiteState.value.selectedUrls,
            only_main_content: websiteState.value.options?.only_main_content !== false,
          }
        : undefined,
      indexingTechnique: indexingTechnique.value,
      processRule: currentProcessRule(),
      docForm: docForm.value,
      docLanguage: docLanguage.value,
      datasetId: resolvedDatasetIdForSource.value || undefined,
    })
    const res = await fetchIndexingEstimate(body)
    estimateMeta.value = {
      total_segments: res?.total_segments ?? 0,
      tokens: res?.tokens,
    }
    estimatePreview.value = res?.qa_preview?.length
      ? res.qa_preview
      : (res?.preview || []).slice(0, 8)
  }
  catch (e) {
    estimateMeta.value = null
    estimatePreview.value = []
    estimateError.value = e.message || '预估失败'
  }
  finally {
    estimating.value = false
  }
}

async function buildCreatePayload({ provider, model }) {
  const shared = {
    indexingTechnique: indexingTechnique.value,
    docForm: docForm.value,
    docLanguage: docLanguage.value,
    processRule: currentProcessRule(),
    retrievalModel: currentRetrievalModel(),
    embeddingModel: model || '',
    embeddingModelProvider: provider || '',
  }

  if (dataSourceType.value === 'notion_import') {
    return buildNotionCreateDocumentPayload({
      pages: notionState.value.pages,
      credentialId: notionState.value.credentialId,
      ...shared,
    })
  }

  if (dataSourceType.value === 'website_crawl') {
    return buildWebsiteCreateDocumentPayload({
      provider: websiteState.value.provider,
      jobId: websiteState.value.jobId,
      urls: websiteState.value.selectedUrls,
      onlyMainContent: websiteState.value.options?.only_main_content !== false,
      ...shared,
    })
  }

  const uploadedIds = await ensureUploadedFiles()
  return buildFileCreateDocumentPayload({
    fileIds: uploadedIds,
    ...shared,
  })
}

async function submitCreate() {
  if (indexingTechnique.value === 'high_quality' && !embeddingKey.value) {
    ElMessage.warning('请选择 Embedding 模型')
    return
  }
  if (!isRerankConfigValid(currentRetrievalModel())) {
    ElMessage.warning('请选择 Rerank 模型')
    return
  }

  creating.value = true
  try {
    const [provider, model] = embeddingKey.value
      ? embeddingKey.value.split('::')
      : ['', '']

    const payload = await buildCreatePayload({ provider, model })
    const existingId = props.datasetId || route.params.datasetId
    const result = existingId
      ? await createDocument(existingId, payload)
      : await createFirstDocument(payload)

    resultDatasetId.value = result?.dataset?.id || existingId || ''
    resultBatch.value = result?.batch || ''
    indexingRows.value = (result?.documents || []).map(d => ({
      id: d.id,
      name: d.name,
      indexing_status: d.indexing_status || 'waiting',
      completed_segments: d.completed_segments || 0,
      total_segments: d.total_segments || 0,
    }))

    await datasetStore.loadDatasets()
    step.value = 3
    startPoll()
  }
  catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
  finally {
    creating.value = false
  }
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function pollOnce() {
  const id = resolvedDatasetId()
  const batch = resultBatch.value
  if (!id || !batch)
    return
  try {
    const res = await fetchBatchIndexingStatus(id, batch)
    const rows = res?.data || []
    if (!rows.length)
      return
    const byId = Object.fromEntries(rows.map(r => [r.id, r]))
    indexingRows.value = indexingRows.value.map((row) => {
      const next = byId[row.id]
      if (!next)
        return row
      return {
        ...row,
        indexing_status: next.indexing_status,
        completed_segments: next.completed_segments,
        total_segments: next.total_segments,
        error: next.error,
      }
    })
    const done = indexingRows.value.every(r => isTerminalIndexingStatus(r.indexing_status))
    if (done)
      stopPoll()
  }
  catch { /* keep polling */ }
}

function startPoll() {
  stopPoll()
  pollOnce()
  pollTimer = setInterval(pollOnce, 2500)
}

onMounted(() => {
  if (isAddMode.value)
    datasetStore.loadDatasetDetail(resolvedDatasetId()).catch(() => {})
})

onBeforeUnmount(stopPoll)
</script>

<style scoped>
.wizard {
  height: 100%;
  overflow: auto;
  padding: 20px 24px 40px;
  box-sizing: border-box;
  background: #f8fafc;
}
.wizard-header {
  max-width: 880px;
  margin: 0 auto 20px;
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
.wizard-header h1 {
  margin: 0 0 16px;
  font-size: 22px;
  color: #101828;
}
.steps {
  margin-bottom: 8px;
}
.panel {
  max-width: 880px;
  margin: 0 auto;
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  padding: 20px;
}
.panel h2 {
  margin: 0 0 16px;
  font-size: 16px;
}
.source-tabs {
  margin-bottom: 16px;
}
.upload-box {
  margin-bottom: 16px;
}
.upload-inner {
  padding: 24px;
  color: #475467;
}
.hint {
  font-size: 12px;
  color: #98a2b3;
}
.file-list {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
}
.file-list li {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #f2f4f7;
  font-size: 13px;
}
.file-list .size {
  color: #98a2b3;
  margin-left: auto;
}
.form {
  max-width: 560px;
}
.preview-block {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #eaecf0;
}
.preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.preview-head h3 {
  margin: 0;
  font-size: 14px;
  color: #344054;
}
.preview-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  max-height: 280px;
  overflow: auto;
}
.preview-list li {
  border: 1px solid #eaecf0;
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 8px;
  font-size: 13px;
}
.preview-list pre {
  margin: 6px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  color: #344054;
}
.error {
  color: #b42318;
  font-size: 13px;
}
.footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}
</style>
