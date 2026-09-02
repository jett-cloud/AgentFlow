<template>
  <div class="docs-page">
    <header class="page-header">
      <div>
        <h1>文档</h1>
        <p>上传并索引文档后，可在工作流「知识检索」节点中选用本知识库。</p>
      </div>
      <el-button type="primary" @click="goCreate">添加文档</el-button>
    </header>

    <div class="toolbar">
      <el-input
        v-model="keyword"
        clearable
        placeholder="搜索文档"
        class="search"
        @keyup.enter="reload"
        @clear="reload"
      />
      <el-select v-model="status" clearable placeholder="状态" style="width: 140px" @change="reload">
        <el-option label="全部" value="all" />
        <el-option label="排队中" value="queuing" />
        <el-option label="索引中" value="indexing" />
        <el-option label="可用" value="available" />
        <el-option label="错误" value="error" />
        <el-option label="已禁用" value="disabled" />
        <el-option label="已归档" value="archived" />
      </el-select>
      <el-button :loading="loading" @click="reload">刷新</el-button>
    </div>

    <div v-if="selected.length" class="batch-bar">
      <span>已选 {{ selected.length }}</span>
      <el-button size="small" :disabled="!batch.canEnable" @click="batchStatus('enable')">启用</el-button>
      <el-button size="small" :disabled="!batch.canDisable" @click="batchStatus('disable')">禁用</el-button>
      <el-button size="small" type="danger" :disabled="!batch.canDelete || !canDeleteDocs" @click="batchDelete">
        删除
      </el-button>
      <el-button size="small" @click="openBatchMeta">元数据</el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="documents"
      stripe
      empty-text="暂无文档"
      @selection-change="onSelectionChange"
    >
      <el-table-column type="selection" width="42" />
      <el-table-column prop="name" label="名称" min-width="200" show-overflow-tooltip />
      <el-table-column label="状态" min-width="160">
        <template #default="{ row }">
          <div class="status-cell">
            <el-tooltip
              v-if="isErrorRow(row)"
              :content="documentIndexingError(row) || '点击查看失败原因'"
              placement="top"
              :show-after="200"
            >
              <span class="status is-error is-clickable" @click="showIndexingError(row)">错误</span>
            </el-tooltip>
            <span v-else class="status" :class="statusClass(row)">{{ statusText(row) }}</span>
            <el-button
              v-if="isErrorRow(row)"
              link
              type="danger"
              @click="showIndexingError(row)"
            >
              原因
            </el-button>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="分段" width="100">
        <template #default="{ row }">
          {{ row.completed_segments ?? row.segment_count ?? 0 }}
          <template v-if="row.total_segments"> / {{ row.total_segments }}</template>
        </template>
      </el-table-column>
      <el-table-column label="字数" width="100">
        <template #default="{ row }">{{ row.word_count ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="命中" width="80">
        <template #default="{ row }">{{ row.hit_count ?? 0 }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button link type="primary" @click="openDoc(row)">详情</el-button>
            <el-button
              v-if="documentRowActions(row).canRetry"
              link
              type="warning"
              @click="retry(row)"
            >
              重试
            </el-button>
            <el-dropdown trigger="click" @command="cmd => onRowCommand(cmd, row)">
              <el-button link>更多</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-if="isErrorRow(row)" command="error">查看失败原因</el-dropdown-item>
                  <el-dropdown-item v-if="documentRowActions(row).canRename" command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item v-if="documentRowActions(row).canDownload" command="download">下载</el-dropdown-item>
                  <el-dropdown-item v-if="documentRowActions(row).canPause" command="pause">暂停索引</el-dropdown-item>
                  <el-dropdown-item v-if="documentRowActions(row).canResume" command="resume">恢复索引</el-dropdown-item>
                  <el-dropdown-item v-if="documentRowActions(row).canArchive" command="archive">归档</el-dropdown-item>
                  <el-dropdown-item v-if="documentRowActions(row).canUnarchive" command="un_archive">取消归档</el-dropdown-item>
                  <el-dropdown-item
                    v-if="documentRowActions(row).canDelete && canDeleteDocs"
                    command="delete"
                    divided
                  >
                    删除
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="limit"
        layout="prev, pager, next"
        :total="total"
        @current-change="reload"
        @size-change="reload"
      />
    </div>

    <el-dialog v-model="errorOpen" title="索引失败原因" width="560px">
      <pre class="error-log">{{ errorText || '索引失败，未返回具体原因。可点击重试。' }}</pre>
      <template #footer>
        <el-button @click="errorOpen = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="metaOpen" title="批量编辑元数据" width="480px">
      <p class="meta-hint">已选 {{ selected.length }} 个文档。空值且未改动的字段会跳过；内置字段不可编辑。</p>
      <el-form v-if="metaEdits.length" label-position="top">
        <el-form-item v-for="item in metaEdits" :key="item.id" :label="`${item.name} (${typeLabel(item.type)})`">
          <el-input-number
            v-if="item.type === 'number'"
            v-model="item.value"
            style="width: 100%"
            controls-position="right"
            @change="item.dirty = true"
          />
          <el-date-picker
            v-else-if="item.type === 'time'"
            v-model="item.value"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            style="width: 100%"
            @change="item.dirty = true"
          />
          <el-input
            v-else
            v-model="item.value"
            :placeholder="item.isMultipleValue ? '多个值，填写后覆盖' : ''"
            @input="item.dirty = true"
          />
        </el-form-item>
      </el-form>
      <p v-else class="meta-hint">请先在知识库设置中定义元数据字段。</p>
      <template #footer>
        <el-button @click="metaOpen = false">取消</el-button>
        <el-button type="primary" :loading="metaSaving" :disabled="!metaEdits.length" @click="saveBatchMeta">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteDocuments,
  fetchDatasetMetadata,
  fetchDocumentDownloadUrl,
  fetchDocumentIndexingStatus,
  fetchDocuments,
  patchDocumentsStatus,
  pauseDocumentIndexing,
  renameDocument,
  resumeDocumentIndexing,
  retryDocuments,
  updateDocumentsMetadata,
} from '@/features/datasets/api/difyDatasetsApi.js'
import { isTerminalIndexingStatus } from '@/features/datasets/model/createDocumentPayload.js'
import { getDatasetCapabilities } from '@/features/datasets/model/datasetCapabilities.js'
import { batchDocumentActions, documentIndexingError, documentRowActions } from '@/features/datasets/model/documentActions.js'
import {
  buildDocumentsMetadataBody,
  mergeDocumentMetadataForBatch,
  METADATA_TYPES,
} from '@/features/datasets/model/metadataFields.js'
import { useDatasetStore } from '@/features/datasets/state/useDatasetStore.js'

const route = useRoute()
const router = useRouter()
const store = useDatasetStore()
const documents = ref([])
const selected = ref([])
const total = ref(0)
const page = ref(1)
const limit = ref(20)
const keyword = ref('')
const status = ref('all')
const loading = ref(false)
const metaOpen = ref(false)
const metaSaving = ref(false)
const metaEdits = ref([])
const errorOpen = ref(false)
const errorText = ref('')
let pollTimer = null

const batch = computed(() => batchDocumentActions(selected.value))
const canDeleteDocs = computed(() => getDatasetCapabilities(store.currentDataset?.permission_keys).canDelete)

function datasetId() {
  return route.params.datasetId
}

function typeLabel(type) {
  return METADATA_TYPES.find(item => item.value === type)?.label || type || '文本'
}

async function showIndexingError(row) {
  let text = documentIndexingError(row)
  if (!text && row?.id) {
    try {
      const res = await fetchDocumentIndexingStatus(datasetId(), row.id)
      text = documentIndexingError({
        indexing_status: 'error',
        error: res?.error ?? res?.data?.error,
      })
      if (text)
        row.error = text
    }
    catch {
      text = ''
    }
  }
  errorText.value = text || '索引失败，未返回具体原因。可点击重试。'
  errorOpen.value = true
}

function isErrorRow(row) {
  const s = String(row?.display_status || row?.indexing_status || '').toLowerCase()
  return s === 'error'
}

async function openBatchMeta() {
  try {
    const res = await fetchDatasetMetadata(datasetId())
    const schema = res.doc_metadata || res.data?.doc_metadata || []
    const merged = mergeDocumentMetadataForBatch(selected.value)
    metaEdits.value = fieldsFromSchema(schema, merged)
    metaOpen.value = true
  }
  catch (e) {
    ElMessage.error(e.message || '元数据加载失败')
  }
}

function fieldsFromSchema(schema, merged) {
  return (Array.isArray(schema) ? schema : []).map((field) => {
    const current = merged.find(item => item.id === field.id)
    return {
      id: field.id,
      name: field.name,
      type: field.type,
      value: current?.isMultipleValue ? '' : (current?.value ?? ''),
      isMultipleValue: Boolean(current?.isMultipleValue),
      dirty: false,
    }
  })
}

async function saveBatchMeta() {
  const dirty = metaEdits.value.filter(item => item.dirty)
  if (!dirty.length) {
    ElMessage.warning('没有修改')
    return
  }
  const ids = selectedIds(selected.value)
  const body = buildDocumentsMetadataBody(ids, dirty.map(item => ({
    id: item.id,
    name: item.name,
    value: item.type === 'number' && item.value !== '' && item.value != null
      ? Number(item.value)
      : (item.value === '' ? null : item.value),
  })))
  metaSaving.value = true
  try {
    await updateDocumentsMetadata(datasetId(), body.operation_data)
    ElMessage.success('已更新元数据')
    metaOpen.value = false
    selected.value = []
    await reload()
  }
  catch (e) {
    ElMessage.error(e.message || '保存失败')
  }
  finally {
    metaSaving.value = false
  }
}

function onSelectionChange(rows) {
  selected.value = rows
}

function statusText(row) {
  if (row.enabled === false || row.display_status === 'disabled')
    return '已禁用'
  if (row.archived)
    return '已归档'
  const s = row.display_status || row.indexing_status || ''
  const map = {
    waiting: '排队中',
    queuing: '排队中',
    parsing: '解析中',
    cleaning: '清洗中',
    splitting: '分段中',
    indexing: '索引中',
    completed: '可用',
    available: '可用',
    error: '错误',
    paused: '已暂停',
  }
  return map[s] || s || '—'
}

function statusClass(row) {
  const s = String(row.display_status || row.indexing_status || '')
  if (s === 'error')
    return 'is-error'
  if (s === 'completed' || s === 'available')
    return 'is-ok'
  if (!isTerminalIndexingStatus(s))
    return 'is-run'
  return ''
}

function goCreate() {
  router.push(`/datasets/${datasetId()}/documents/create`)
}

function openDoc(row) {
  router.push(`/datasets/${datasetId()}/documents/${row.id}`)
}

function selectedIds(rows) {
  return (rows || []).map(row => row.id).filter(Boolean)
}

async function retry(row) {
  try {
    await retryDocuments(datasetId(), [row.id])
    ElMessage.success('已重新提交索引')
    reload()
  }
  catch (e) {
    ElMessage.error(e.message || '重试失败')
  }
}

async function batchStatus(action) {
  const ids = selectedIds(selected.value)
  if (!ids.length)
    return
  try {
    await patchDocumentsStatus(datasetId(), action, ids)
    ElMessage.success('已更新')
    selected.value = []
    await reload()
  }
  catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

async function confirmDelete(ids, name) {
  if (!canDeleteDocs.value || !ids.length)
    return
  const tip = name
    ? `确认删除文档「${name}」？此操作不可恢复。`
    : `确认删除选中的 ${ids.length} 个文档？此操作不可恢复。`
  await ElMessageBox.confirm(tip, '删除文档', { type: 'warning' })
  await deleteDocuments(datasetId(), ids)
  ElMessage.success('已删除')
  selected.value = []
  await reload()
}

async function batchDelete() {
  try {
    await confirmDelete(selectedIds(selected.value))
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
}

async function downloadDoc(row) {
  try {
    const res = await fetchDocumentDownloadUrl(datasetId(), row.id)
    const url = res?.url || res?.data?.url
    if (!url)
      throw new Error('未返回下载地址')
    const anchor = window.document.createElement('a')
    anchor.href = url
    anchor.download = row.name || 'document'
    anchor.target = '_blank'
    anchor.rel = 'noopener noreferrer'
    window.document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  }
  catch (e) {
    ElMessage.error(e.message || '下载失败')
  }
}

async function renameDoc(row) {
  try {
    const { value } = await ElMessageBox.prompt('新名称', '重命名文档', {
      inputValue: row.name || '',
      inputPattern: /\S+/,
      inputErrorMessage: '请输入名称',
    })
    await renameDocument(datasetId(), row.id, value.trim())
    ElMessage.success('已重命名')
    await reload()
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
}

async function onRowCommand(cmd, row) {
  try {
    if (cmd === 'error') {
      showIndexingError(row)
      return
    }
    if (cmd === 'rename') {
      await renameDoc(row)
      return
    }
    if (cmd === 'download') {
      await downloadDoc(row)
      return
    }
    if (cmd === 'pause') {
      await pauseDocumentIndexing(datasetId(), row.id)
      ElMessage.success('已暂停')
      await reload()
      return
    }
    if (cmd === 'resume') {
      await resumeDocumentIndexing(datasetId(), row.id)
      ElMessage.success('已恢复')
      await reload()
      return
    }
    if (cmd === 'archive' || cmd === 'un_archive') {
      await patchDocumentsStatus(datasetId(), cmd, [row.id])
      ElMessage.success('已更新')
      await reload()
      return
    }
    if (cmd === 'delete')
      await confirmDelete([row.id], row.name)
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function maybeStartPoll() {
  stopPoll()
  const busy = documents.value.some((d) => {
    const s = d.indexing_status || d.display_status
    return s && !isTerminalIndexingStatus(s) && s !== 'available' && s !== 'disabled'
  })
  if (busy) {
    pollTimer = setInterval(() => {
      reload({ silent: true })
    }, 3000)
  }
}

async function reload({ silent = false } = {}) {
  if (!silent)
    loading.value = true
  try {
    const res = await fetchDocuments(datasetId(), {
      page: page.value,
      limit: limit.value,
      keyword: keyword.value.trim(),
      status: status.value || 'all',
    })
    documents.value = res.data || []
    total.value = res.total || 0
    maybeStartPoll()
  }
  catch (e) {
    if (!silent)
      ElMessage.error(e.message || '文档列表加载失败')
  }
  finally {
    loading.value = false
  }
}

onMounted(reload)
watch(() => route.params.datasetId, () => {
  page.value = 1
  selected.value = []
  reload()
})
onBeforeUnmount(stopPoll)
</script>

<style scoped>
.docs-page {
  padding: 20px 24px 24px;
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
.toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.search {
  max-width: 260px;
}
.batch-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #475467;
}
.meta-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: #667085;
}
.status.is-ok { color: #027a48; }
.status.is-error { color: #b42318; }
.status.is-run { color: #b54708; }
.status.is-clickable {
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.status-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}
.row-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  white-space: nowrap;
}
.row-actions :deep(.el-button) {
  margin-left: 0;
}
.error-log {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.5;
  color: #b42318;
  max-height: 360px;
  overflow: auto;
}
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
