<template>
  <div class="hit-page">
    <header class="page-header">
      <div>
        <h1>召回测试</h1>
        <p>输入查询，验证知识库检索效果。对齐 Dify hitTesting。</p>
      </div>
    </header>

    <div class="layout">
      <section class="query-panel">
        <el-alert
          v-if="!canRetrievalRecall"
          title="当前账号没有召回测试权限"
          type="warning"
          show-icon
          :closable="false"
          class="index-warning"
        />
        <el-alert
          v-if="indexWarning"
          :title="indexWarning"
          type="warning"
          show-icon
          :closable="false"
          class="index-warning"
        >
          <template #default>
            <el-button link type="warning" @click="openDocuments">查看文档索引状态</el-button>
          </template>
        </el-alert>
        <el-input
          v-model="query"
          type="textarea"
          :rows="4"
          placeholder="输入要测试的问题…"
        />
        <div class="params">
          <el-form label-position="top" inline>
            <el-form-item v-if="!isExternal" label="检索方法">
              <el-select v-model="searchMethod" style="width: 160px">
                <el-option label="向量检索" value="semantic_search" />
                <el-option label="全文检索" value="full_text_search" />
                <el-option label="混合检索" value="hybrid_search" />
              </el-select>
            </el-form-item>
            <el-form-item label="Top K">
              <el-input-number v-model="topK" :min="1" :max="20" />
            </el-form-item>
            <el-form-item label="Score 阈值">
              <el-switch v-model="scoreEnabled" />
              <el-input-number
                v-if="scoreEnabled"
                v-model="scoreThreshold"
                :min="0"
                :max="1"
                :step="0.05"
                style="margin-left: 8px"
              />
            </el-form-item>
            <el-form-item v-if="!isExternal" label="Rerank">
              <el-switch v-model="rerankEnable" />
              <el-select
                v-if="rerankEnable"
                v-model="rerankKey"
                filterable
                clearable
                placeholder="选择 Rerank 模型"
                style="width: 220px; margin-left: 8px"
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
        </div>
        <el-button type="primary" :loading="running" :disabled="!canSubmit" @click="runTest">
          测试
        </el-button>

        <div class="history">
          <div class="history-header">
            <h3>历史查询</h3>
            <span v-if="historyTotal">{{ historyTotal }} 条</span>
          </div>
          <div class="history-list" v-loading="historyLoading">
            <button
              v-for="item in historyRecords"
              :key="item.id"
              type="button"
              class="hist-item"
              :title="item.text"
              @click="query = item.text"
            >
              <span class="hist-query">{{ item.text }}</span>
              <time
                v-if="item.createdAt"
                :datetime="new Date(item.createdAt * 1000).toISOString()"
                class="hist-time"
              >
                {{ new Date(item.createdAt * 1000).toLocaleString('zh-CN', {
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                  hour12: false,
                }) }}
              </time>
            </button>
            <p v-if="!historyRecords.length" class="history-empty">暂无历史查询</p>
          </div>
          <el-pagination
            v-if="historyTotal > historyPageSize"
            v-model:current-page="historyPage"
            class="history-pagination"
            small
            background
            layout="prev, pager, next"
            :page-size="historyPageSize"
            :total="historyTotal"
            @current-change="loadHistory"
          />
        </div>
      </section>

      <section class="result-panel" v-loading="running">
        <h3>命中结果（{{ recordsHits.length }}）</h3>
        <article v-for="(hit, i) in recordsHits" :key="i" class="hit-card">
          <div class="hit-top">
            <span class="score">score {{ formatScore(hit.score) }}</span>
            <span class="doc">{{ hitTitle(hit) }}</span>
          </div>
          <pre class="content">{{ hitContent(hit) }}</pre>
        </article>
        <p v-if="!running && tested && !recordsHits.length" class="empty">无命中结果</p>
        <p v-else-if="!tested" class="empty">输入查询后点击测试</p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  externalHitTesting,
  fetchDatasetDetail,
  fetchDocuments,
  fetchHitTestingRecords,
  hitTesting,
} from '@/features/datasets/api/difyDatasetsApi.js'
import { fetchModelsByType } from '@/features/integrations/api/difyModelsApi.js'
import { getDatasetCapabilities } from '@/features/datasets/model/datasetCapabilities.js'
import {
  buildExternalHitTestingBody,
  buildHitTestingBody,
  isExternalDataset,
  selectHitTestingApi,
} from '@/features/datasets/model/hitTestingRequest.js'
import { normalizeHitTestingHistoryPage, resolveHitTestingSearch } from '@/features/datasets/model/hitTestingState.js'
import {
  flattenModelCatalog,
  isRerankConfigValid,
  parseRerankKey,
  rerankModelKey,
} from '@/features/datasets/model/retrievalModel.js'

const route = useRoute()
const router = useRouter()
const query = ref('')
const searchMethod = ref('semantic_search')
const topK = ref(4)
const scoreEnabled = ref(false)
const scoreThreshold = ref(0.5)
const rerankEnable = ref(false)
const rerankKey = ref('')
const rerankModels = ref([])
const running = ref(false)
const tested = ref(false)
const recordsHits = ref([])
const historyRecords = ref([])
const historyPage = ref(1)
const historyPageSize = 5
const historyTotal = ref(0)
const historyLoading = ref(false)
const indexWarning = ref('')
const isExternal = ref(false)
const canRetrievalRecall = ref(true)

const currentRetrievalModel = computed(() => {
  const rerank = parseRerankKey(rerankKey.value)
  return {
    reranking_enable: rerankEnable.value,
    reranking_model: rerank,
  }
})

const canSubmit = computed(() => {
  if (!canRetrievalRecall.value || !query.value.trim())
    return false
  if (isExternal.value)
    return true
  return isRerankConfigValid(currentRetrievalModel.value)
})

function datasetId() {
  return route.params.datasetId
}

function formatScore(score) {
  if (score == null || Number.isNaN(Number(score)))
    return '—'
  return Number(score).toFixed(4)
}

function hitTitle(hit) {
  return hit.segment?.document?.name || hit.document?.name || hit.title || '文档'
}

function hitContent(hit) {
  if (typeof hit.segment?.content === 'string')
    return hit.segment.content
  if (typeof hit.content === 'string')
    return hit.content
  return hit.content?.content || ''
}

function openDocuments() {
  router.push(`/datasets/${datasetId()}/documents`)
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

async function loadRetrievalState() {
  try {
    const dataset = await fetchDatasetDetail(datasetId())
    isExternal.value = isExternalDataset(dataset)
    canRetrievalRecall.value = getDatasetCapabilities(dataset.permission_keys).canRetrievalRecall
    const retrievalModel = dataset.retrieval_model_dict || dataset.retrieval_model || {}
    topK.value = retrievalModel.top_k || topK.value
    scoreEnabled.value = Boolean(retrievalModel.score_threshold_enabled)
    scoreThreshold.value = retrievalModel.score_threshold ?? scoreThreshold.value
    rerankEnable.value = Boolean(retrievalModel.reranking_enable)
    rerankKey.value = rerankModelKey(retrievalModel)

    if (isExternal.value) {
      indexWarning.value = ''
      return
    }

    const documentsResponse = await fetchDocuments(datasetId(), { page: 1, limit: 100 })
    const resolution = resolveHitTestingSearch({
      preferredMethod: retrievalModel.search_method || searchMethod.value,
      documents: documentsResponse.data || [],
    })
    searchMethod.value = resolution.method
    indexWarning.value = resolution.warning
  }
  catch {
    indexWarning.value = ''
  }
}

async function loadHistory(page = historyPage.value) {
  historyLoading.value = true
  try {
    const res = await fetchHitTestingRecords(datasetId(), { page, limit: historyPageSize })
    const history = normalizeHitTestingHistoryPage(res)
    historyRecords.value = history.rows
    historyPage.value = history.page
    historyTotal.value = history.total
  }
  catch {
    historyRecords.value = []
    historyTotal.value = 0
  }
  finally {
    historyLoading.value = false
  }
}

async function runTest() {
  const q = query.value.trim()
  if (!q || !canRetrievalRecall.value)
    return
  if (!isExternal.value && !isRerankConfigValid(currentRetrievalModel.value)) {
    ElMessage.warning('请选择 Rerank 模型')
    return
  }
  running.value = true
  tested.value = true
  try {
    const rerank = parseRerankKey(rerankKey.value)
    const api = selectHitTestingApi({ provider: isExternal.value ? 'external' : 'vendor' })
    const request = api === 'externalHitTesting' ? externalHitTesting : hitTesting
    const body = api === 'externalHitTesting'
      ? buildExternalHitTestingBody({
          query: q,
          topK: topK.value,
          scoreEnabled: scoreEnabled.value,
          scoreThreshold: scoreThreshold.value,
        })
      : buildHitTestingBody({
          query: q,
          searchMethod: searchMethod.value,
          topK: topK.value,
          scoreEnabled: scoreEnabled.value,
          scoreThreshold: scoreThreshold.value,
          rerankEnable: rerankEnable.value,
          rerankProvider: rerank.reranking_provider_name,
          rerankModel: rerank.reranking_model_name,
        })
    const res = await request(datasetId(), body)
    recordsHits.value = res.records || res.data || []
    historyPage.value = 1
    await loadHistory(1)
  }
  catch (e) {
    ElMessage.error(e.message || '召回测试失败')
    recordsHits.value = []
  }
  finally {
    running.value = false
  }
}

onMounted(() => {
  loadHistory()
  loadRetrievalState()
  loadRerankModels()
})
</script>

<style scoped>
.hit-page {
  padding: 20px 24px 24px;
  box-sizing: border-box;
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
.layout {
  display: grid;
  grid-template-columns: minmax(280px, 380px) 1fr;
  gap: 16px;
  margin-top: 16px;
  min-height: 420px;
}
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
}
.query-panel, .result-panel {
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  padding: 16px;
}
.params { margin: 12px 0; }
.index-warning { margin-bottom: 12px; }
.history { margin-top: 20px; }
.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.history-header span {
  color: #98a2b3;
  font-size: 12px;
}
.history h3, .result-panel h3 {
  margin: 0;
  font-size: 14px;
  color: #344054;
}
.history-list {
  border: 1px solid #eaecf0;
  border-radius: 8px;
}
.hist-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  text-align: left;
  border: 0;
  border-bottom: 1px solid #eaecf0;
  background: #fff;
  padding: 8px 10px;
  cursor: pointer;
  color: #475467;
}
.hist-item:last-of-type { border-bottom: 0; }
.hist-item:hover {
  background: #f8faff;
}
.hist-query {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: #344054;
  font-size: 13px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hist-time {
  flex-shrink: 0;
  color: #98a2b3;
  font-size: 11px;
}
.history-pagination {
  justify-content: center;
  margin-top: 10px;
}
.history-empty {
  margin: 0;
  padding: 20px 12px;
  color: #98a2b3;
  font-size: 12px;
  text-align: center;
}
.hit-card {
  border: 1px solid #eaecf0;
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 10px;
}
.hit-top {
  display: flex;
  gap: 10px;
  margin-bottom: 8px;
  font-size: 12px;
}
.score { color: #3538cd; font-weight: 600; }
.doc { color: #667085; }
.content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 13px;
  color: #344054;
  line-height: 1.5;
}
.empty {
  color: #98a2b3;
  text-align: center;
  padding: 40px 12px;
}
</style>
