<template>
  <div class="doc-detail" v-loading="loadingDoc">
    <header class="page-header">
      <div>
        <button type="button" class="back" @click="goDocs">← 文档列表</button>
        <h1>{{ document?.name || '文档分段' }}</h1>
        <p class="meta">
          状态：{{ document?.display_status || document?.indexing_status || '—' }}
          · {{ formLabel }}
          · 字数 {{ document?.word_count ?? '—' }}
          · 分段 {{ total }}
        </p>
      </div>
      <div class="header-actions">
        <el-button v-if="rowActions.canRename" @click="renameDoc">重命名</el-button>
        <el-button v-if="rowActions.canDownload" @click="downloadDoc">下载</el-button>
        <el-button v-if="rowActions.canEnable" @click="setStatus('enable')">启用</el-button>
        <el-button v-if="rowActions.canDisable" @click="setStatus('disable')">禁用</el-button>
        <el-button v-if="rowActions.canPause" @click="pauseDoc">暂停索引</el-button>
        <el-button v-if="rowActions.canResume" @click="resumeDoc">恢复索引</el-button>
        <el-button v-if="rowActions.canArchive" @click="setStatus('archive')">归档</el-button>
        <el-button v-if="rowActions.canUnarchive" @click="setStatus('un_archive')">取消归档</el-button>
        <el-button @click="downloadCsvTemplate">CSV 模板</el-button>
        <el-button :loading="importing" @click="pickCsv">CSV 导入</el-button>
        <el-button type="primary" @click="openCreate">添加分段</el-button>
      </div>
    </header>

    <el-alert
      v-if="indexingError || rowActions.canRetry"
      type="error"
      show-icon
      :closable="false"
      class="error-banner"
      title="索引失败"
    >
      <pre class="error-log">{{ indexingError || '未返回具体原因。可返回列表后点击重试。' }}</pre>
    </el-alert>

    <input
      ref="csvInput"
      type="file"
      accept=".csv,text/csv"
      class="hidden-input"
      @change="onCsvPicked"
    >

    <div class="toolbar">
      <el-input
        v-model="keyword"
        clearable
        placeholder="搜索分段"
        class="search"
        @keyup.enter="applyFilters"
        @clear="applyFilters"
      />
      <el-select v-model="enabledFilter" style="width: 140px" @change="applyFilters">
        <el-option label="全部" value="all" />
        <el-option label="已启用" :value="true" />
        <el-option label="已禁用" :value="false" />
      </el-select>
      <el-button :loading="loading" @click="applyFilters">刷新</el-button>
    </div>

    <div class="batch-bar">
      <el-checkbox
        :model-value="allSelected"
        :indeterminate="selectedIds.length > 0 && !allSelected"
        :disabled="!total || loading || selectingAll || batchOperating"
        @change="toggleSelectAll"
      >
        全选全部 {{ total }} 条
      </el-checkbox>
      <span v-if="selectedIds.length">已选 {{ selectedIds.length }}</span>
      <el-button size="small" :loading="batchAction === 'enable'" :disabled="!batch.canEnable || batchOperating" @click="batchEnable">
        启用所选
      </el-button>
      <el-button size="small" :loading="batchAction === 'disable'" :disabled="!batch.canDisable || batchOperating" @click="batchDisable">
        禁用所选
      </el-button>
      <el-button size="small" type="danger" :loading="batchAction === 'delete'" :disabled="!batch.canDelete || batchOperating" @click="batchDelete">
        删除所选
      </el-button>
    </div>

    <div v-loading="loading" class="segment-list">
      <article v-for="seg in segments" :key="seg.id" class="segment-card">
        <div class="seg-top">
          <el-checkbox :model-value="selectedIds.includes(seg.id)" @change="checked => toggleSelect(seg, checked)" />
          <span class="pos">#{{ seg.position ?? '—' }}</span>
          <el-tag size="small" :type="seg.enabled === false ? 'info' : 'success'">
            {{ seg.enabled === false ? '已禁用' : '已启用' }}
          </el-tag>
          <span class="stats">{{ seg.word_count ?? 0 }} 字 · 命中 {{ seg.hit_count ?? 0 }}</span>
          <div class="actions">
            <el-button v-if="isHierarchical" link @click="toggleChildren(seg)">
              {{ expanded[seg.id] ? '收起子分段' : '子分段' }}
            </el-button>
            <el-button link type="primary" @click="openEdit(seg)">编辑</el-button>
            <el-button link @click="toggleEnabled(seg)">
              {{ seg.enabled === false ? '启用' : '禁用' }}
            </el-button>
            <el-button link type="danger" @click="remove(seg)">删除</el-button>
          </div>
        </div>
        <p v-if="isQa && (seg.content || seg.answer)" class="qa-label">问</p>
        <pre class="content">{{ seg.content }}</pre>
        <template v-if="isQa && seg.answer">
          <p class="qa-label">答</p>
          <pre class="content">{{ seg.answer }}</pre>
        </template>
        <p v-if="seg.keywords?.length" class="keywords">
          关键词：{{ seg.keywords.join('、') }}
        </p>
        <p v-if="attachmentNames(seg).length" class="keywords">
          附件：{{ attachmentNames(seg).join('、') }}
        </p>
        <div v-if="expanded[seg.id]" class="children" v-loading="childLoading[seg.id]">
          <article v-for="child in childrenBySeg[seg.id] || []" :key="child.id" class="child-card">
            <pre class="content">{{ child.content }}</pre>
            <div class="child-actions">
              <el-button link type="primary" @click="editChild(seg, child)">编辑</el-button>
              <el-button link type="danger" @click="removeChild(seg, child)">删除</el-button>
            </div>
          </article>
          <p v-if="!(childrenBySeg[seg.id] || []).length" class="empty child-empty">暂无子分段</p>
          <div class="child-add">
            <el-input v-model="childDrafts[seg.id]" type="textarea" :rows="2" placeholder="新增子分段内容" />
            <el-button :loading="childSaving[seg.id]" @click="addChild(seg)">添加子分段</el-button>
          </div>
        </div>
      </article>
      <p v-if="!loading && !segments.length" class="empty">暂无分段</p>
    </div>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="limit"
        layout="prev, pager, next"
        :total="total"
        @current-change="changePage"
      />
    </div>

    <el-dialog
      v-model="dialogOpen"
      :title="editing ? '编辑分段' : '添加分段'"
      width="640px"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item :label="isQa ? '问题' : '内容'" required>
          <el-input v-model="form.content" type="textarea" :rows="8" :placeholder="isQa ? '问题' : '分段文本'" />
        </el-form-item>
        <el-form-item v-if="isQa" label="答案" required>
          <el-input v-model="form.answer" type="textarea" :rows="6" placeholder="答案" />
        </el-form-item>
        <el-form-item label="关键词（逗号分隔）">
          <el-input v-model="form.keywordsText" placeholder="可选" />
        </el-form-item>
        <el-form-item label="附件">
          <el-button :loading="uploading" @click="pickAttachment">上传附件</el-button>
          <ul v-if="form.attachments.length" class="file-list">
            <li v-for="(file, i) in form.attachments" :key="file.id">
              <span>{{ file.name || file.id }}</span>
              <el-button link type="danger" @click="form.attachments.splice(i, 1)">移除</el-button>
            </li>
          </ul>
        </el-form-item>
        <el-form-item v-if="isHierarchical && editing">
          <el-checkbox v-model="form.regenerateChildChunks">保存后重新生成子分段</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveSegment">保存</el-button>
      </template>
    </el-dialog>

    <input
      ref="attachInput"
      type="file"
      class="hidden-input"
      @change="onAttachmentPicked"
    >
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addChildChunk,
  addSegment,
  deleteChildChunk,
  deleteSegments,
  disableSegments,
  enableSegments,
  fetchChildChunks,
  fetchDocumentDetail,
  fetchDocumentDownloadUrl,
  fetchDocumentIndexingStatus,
  fetchSegmentBatchImportStatus,
  fetchSegments,
  importSegmentsCsv,
  patchDocumentsStatus,
  pauseDocumentIndexing,
  renameDocument,
  resumeDocumentIndexing,
  updateChildChunk,
  updateSegment,
} from '@/features/datasets/api/difyDatasetsApi.js'
import { documentIndexingError, documentRowActions } from '@/features/datasets/model/documentActions.js'
import {
  batchSegmentActions,
  buildSegmentBody,
  chunkSegmentIds,
  collectAllSegments,
  csvImportTemplateText,
  isHierarchicalDocument,
  isQaDocument,
  isSegmentBatchImportFinished,
} from '@/features/datasets/model/segmentPayload.js'
import { uploadConsoleFile } from '@/shared/media/difyFilesApi.js'

const route = useRoute()
const router = useRouter()
const document = ref(null)
const segments = ref([])
const selectedIds = ref([])
const selectedSegmentsById = ref({})
const total = ref(0)
const page = ref(1)
const limit = ref(20)
const keyword = ref('')
const enabledFilter = ref('all')
const loading = ref(false)
const selectingAll = ref(false)
const batchAction = ref('')
const loadingDoc = ref(false)
const dialogOpen = ref(false)
const editing = ref(null)
const saving = ref(false)
const importing = ref(false)
const uploading = ref(false)
const csvInput = ref(null)
const attachInput = ref(null)
const expanded = reactive({})
const childrenBySeg = reactive({})
const childLoading = reactive({})
const childDrafts = reactive({})
const childSaving = reactive({})
const form = reactive({
  content: '',
  answer: '',
  keywordsText: '',
  attachments: [],
  regenerateChildChunks: false,
})
const rowActions = computed(() => documentRowActions(document.value))
const indexingError = computed(() => documentIndexingError(document.value))
const isQa = computed(() => isQaDocument(document.value))
const isHierarchical = computed(() => isHierarchicalDocument(document.value))
const selectedSegments = computed(() => selectedIds.value
  .map(id => selectedSegmentsById.value[id])
  .filter(Boolean))
const batch = computed(() => batchSegmentActions(selectedSegments.value))
const allSelected = computed(() => total.value > 0 && selectedIds.value.length === total.value)
const batchOperating = computed(() => Boolean(batchAction.value))
const formLabel = computed(() => {
  if (isQa.value)
    return '问答'
  if (isHierarchical.value)
    return '父子分段'
  return '通用分段'
})

let importPollTimer = null
let importPollCount = 0
const IMPORT_POLL_MAX = 60

function datasetId() {
  return route.params.datasetId
}
function documentId() {
  return route.params.documentId
}

function goDocs() {
  router.push(`/datasets/${datasetId()}/documents`)
}

function parseKeywords(text) {
  return String(text || '')
    .split(/[,，]/)
    .map(s => s.trim())
    .filter(Boolean)
}

function attachmentNames(seg) {
  if (Array.isArray(seg?.attachments) && seg.attachments.length)
    return seg.attachments.map(item => item.name || item.id).filter(Boolean)
  return []
}

function clearSelection() {
  selectedIds.value = []
  selectedSegmentsById.value = {}
}

function setSelectedSegments(items) {
  const byId = {}
  for (const item of items) {
    if (item?.id)
      byId[item.id] = item
  }
  selectedSegmentsById.value = byId
  selectedIds.value = Object.keys(byId)
}

function toggleSelect(segment, checked) {
  const id = segment.id
  if (checked) {
    if (!selectedIds.value.includes(id)) {
      selectedIds.value = [...selectedIds.value, id]
      selectedSegmentsById.value = { ...selectedSegmentsById.value, [id]: segment }
    }
    return
  }
  selectedIds.value = selectedIds.value.filter(item => item !== id)
  const next = { ...selectedSegmentsById.value }
  delete next[id]
  selectedSegmentsById.value = next
}

async function toggleSelectAll(checked) {
  if (!checked) {
    clearSelection()
    return
  }

  selectingAll.value = true
  try {
    const allSegments = await collectAllSegments(({ page: nextPage, limit: pageSize }) =>
      fetchSegments(datasetId(), documentId(), {
        page: nextPage,
        limit: pageSize,
        keyword: keyword.value.trim(),
        enabled: enabledFilter.value,
      }))
    setSelectedSegments(allSegments)
    ElMessage.success(`已选择全部 ${allSegments.length} 个分段`)
  }
  catch (e) {
    clearSelection()
    ElMessage.error(e.message || '全选失败')
  }
  finally {
    selectingAll.value = false
  }
}

async function setStatus(action) {
  try {
    await patchDocumentsStatus(datasetId(), action, [documentId()])
    ElMessage.success('已更新')
    await loadDocument()
  }
  catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

async function pauseDoc() {
  try {
    await pauseDocumentIndexing(datasetId(), documentId())
    ElMessage.success('已暂停')
    await loadDocument()
  }
  catch (e) {
    ElMessage.error(e.message || '暂停失败')
  }
}

async function resumeDoc() {
  try {
    await resumeDocumentIndexing(datasetId(), documentId())
    ElMessage.success('已恢复')
    await loadDocument()
  }
  catch (e) {
    ElMessage.error(e.message || '恢复失败')
  }
}

async function renameDoc() {
  try {
    const { value } = await ElMessageBox.prompt('新名称', '重命名文档', {
      inputValue: document.value?.name || '',
      inputPattern: /\S+/,
      inputErrorMessage: '请输入名称',
    })
    await renameDocument(datasetId(), documentId(), value.trim())
    ElMessage.success('已重命名')
    await loadDocument()
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
}

async function downloadDoc() {
  try {
    const res = await fetchDocumentDownloadUrl(datasetId(), documentId())
    const url = res?.url || res?.data?.url
    if (!url)
      throw new Error('未返回下载地址')
    const anchor = window.document.createElement('a')
    anchor.href = url
    anchor.download = document.value?.name || 'document'
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

function downloadCsvTemplate() {
  const blob = new Blob([csvImportTemplateText(isQa.value)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = window.document.createElement('a')
  anchor.href = url
  anchor.download = isQa.value ? 'segments-qa.csv' : 'segments.csv'
  window.document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function pickCsv() {
  csvInput.value?.click()
}

function stopImportPoll() {
  if (importPollTimer) {
    clearInterval(importPollTimer)
    importPollTimer = null
  }
  importPollCount = 0
}

async function pollImportStatus(jobId) {
  importPollCount += 1
  const res = await fetchSegmentBatchImportStatus(jobId)
  const status = res?.job_status || res?.data?.job_status
  if (isSegmentBatchImportFinished(status)) {
    stopImportPoll()
    importing.value = false
    if (status === 'completed') {
      ElMessage.success('CSV 导入完成')
      await reload()
    }
    else {
      ElMessage.error('CSV 导入失败')
    }
    return true
  }
  if (importPollCount >= IMPORT_POLL_MAX) {
    stopImportPoll()
    importing.value = false
    ElMessage.warning('导入仍在进行，请稍后刷新')
    return true
  }
  return false
}

async function onCsvPicked(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file)
    return
  if (!String(file.name || '').toLowerCase().endsWith('.csv')) {
    ElMessage.warning('仅支持 CSV 文件')
    return
  }
  importing.value = true
  stopImportPoll()
  try {
    const uploaded = await uploadConsoleFile(file, { source: 'datasets' })
    const uploadFileId = uploaded?.id || uploaded?.data?.id
    if (!uploadFileId)
      throw new Error('文件上传失败')
    const res = await importSegmentsCsv(datasetId(), documentId(), uploadFileId)
    const jobId = res?.job_id || res?.data?.job_id
    if (!jobId)
      throw new Error('未返回导入任务')
    const done = await pollImportStatus(jobId)
    if (!done) {
      importPollTimer = setInterval(() => {
        pollImportStatus(jobId).catch((e) => {
          stopImportPoll()
          importing.value = false
          ElMessage.error(e.message || '导入状态查询失败')
        })
      }, 2000)
    }
  }
  catch (e) {
    importing.value = false
    ElMessage.error(e.message || 'CSV 导入失败')
  }
}

async function loadDocument() {
  loadingDoc.value = true
  try {
    const detail = await fetchDocumentDetail(datasetId(), documentId())
    document.value = detail
    if (documentRowActions(detail).canRetry && !documentIndexingError(detail)) {
      const res = await fetchDocumentIndexingStatus(datasetId(), documentId())
      const error = res?.error ?? res?.data?.error
      if (error)
        document.value = { ...detail, error }
    }
  }
  catch (e) {
    ElMessage.error(e.message || '文档加载失败')
  }
  finally {
    loadingDoc.value = false
  }
}

async function reload({ preserveSelection = false } = {}) {
  loading.value = true
  try {
    const res = await fetchSegments(datasetId(), documentId(), {
      page: page.value,
      limit: limit.value,
      keyword: keyword.value.trim(),
      enabled: enabledFilter.value,
    })
    segments.value = res.data || []
    total.value = res.total || 0
    if (!preserveSelection)
      clearSelection()
  }
  catch (e) {
    ElMessage.error(e.message || '分段列表加载失败')
  }
  finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  return reload()
}

function changePage() {
  return reload({ preserveSelection: true })
}

function resetForm() {
  form.content = ''
  form.answer = ''
  form.keywordsText = ''
  form.attachments = []
  form.regenerateChildChunks = false
}

function openCreate() {
  editing.value = null
  resetForm()
  dialogOpen.value = true
}

function openEdit(seg) {
  editing.value = seg
  form.content = seg.content || ''
  form.answer = seg.answer || ''
  form.keywordsText = (seg.keywords || []).join(', ')
  form.attachments = Array.isArray(seg.attachments)
    ? seg.attachments.map(item => ({ id: item.id, name: item.name || item.id }))
    : []
  form.regenerateChildChunks = false
  dialogOpen.value = true
}

function pickAttachment() {
  attachInput.value?.click()
}

async function onAttachmentPicked(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file)
    return
  uploading.value = true
  try {
    const uploaded = await uploadConsoleFile(file, { source: 'datasets' })
    const id = uploaded?.id || uploaded?.data?.id
    if (!id)
      throw new Error('附件上传失败')
    form.attachments.push({ id, name: uploaded?.name || file.name })
  }
  catch (e) {
    ElMessage.error(e.message || '附件上传失败')
  }
  finally {
    uploading.value = false
  }
}

async function saveSegment() {
  const content = form.content.trim()
  if (!content) {
    ElMessage.warning(isQa.value ? '请输入问题' : '请输入分段内容')
    return
  }
  if (isQa.value && !form.answer.trim()) {
    ElMessage.warning('请输入答案')
    return
  }
  const body = buildSegmentBody({
    content,
    answer: form.answer,
    keywords: parseKeywords(form.keywordsText),
    attachmentIds: form.attachments.map(item => item.id).filter(Boolean),
    isQa: isQa.value,
    regenerateChildChunks: Boolean(editing.value && isHierarchical.value && form.regenerateChildChunks),
  })
  saving.value = true
  try {
    if (editing.value) {
      await updateSegment(datasetId(), documentId(), editing.value.id, body)
      ElMessage.success('已更新')
    }
    else {
      await addSegment(datasetId(), documentId(), body)
      ElMessage.success('已添加')
    }
    dialogOpen.value = false
    await reload()
  }
  catch (e) {
    ElMessage.error(e.message || '保存失败')
  }
  finally {
    saving.value = false
  }
}

async function toggleEnabled(seg) {
  try {
    if (seg.enabled === false)
      await enableSegments(datasetId(), documentId(), [seg.id])
    else
      await disableSegments(datasetId(), documentId(), [seg.id])
    await reload()
  }
  catch (e) {
    ElMessage.error(e.message || '操作失败')
  }
}

async function remove(seg) {
  try {
    await ElMessageBox.confirm('确认删除该分段？', '删除分段', { type: 'warning' })
    await deleteSegments(datasetId(), documentId(), [seg.id])
    ElMessage.success('已删除')
    await reload()
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
}

async function batchEnable() {
  const ids = selectedSegments.value.filter(seg => seg.enabled === false).map(seg => seg.id)
  if (!ids.length)
    return
  try {
    batchAction.value = 'enable'
    for (const batchIds of chunkSegmentIds(ids))
      await enableSegments(datasetId(), documentId(), batchIds)
    ElMessage.success('已启用')
    await reload()
  }
  catch (e) {
    ElMessage.error(e.message || '启用失败')
  }
  finally {
    batchAction.value = ''
  }
}

async function batchDisable() {
  const ids = selectedSegments.value.filter(seg => seg.enabled !== false).map(seg => seg.id)
  if (!ids.length)
    return
  try {
    batchAction.value = 'disable'
    for (const batchIds of chunkSegmentIds(ids))
      await disableSegments(datasetId(), documentId(), batchIds)
    ElMessage.success('已禁用')
    await reload()
  }
  catch (e) {
    ElMessage.error(e.message || '禁用失败')
  }
  finally {
    batchAction.value = ''
  }
}

async function batchDelete() {
  const ids = selectedIds.value
  if (!ids.length)
    return
  try {
    await ElMessageBox.confirm(`确认删除选中的 ${ids.length} 个分段？`, '批量删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    batchAction.value = 'delete'
    for (const batchIds of chunkSegmentIds(ids))
      await deleteSegments(datasetId(), documentId(), batchIds)
    ElMessage.success('已删除')
    await reload()
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
  finally {
    batchAction.value = ''
  }
}

async function loadChildren(seg) {
  childLoading[seg.id] = true
  try {
    const res = await fetchChildChunks(datasetId(), documentId(), seg.id)
    childrenBySeg[seg.id] = Array.isArray(res?.data) ? res.data : []
  }
  catch (e) {
    ElMessage.error(e.message || '子分段加载失败')
  }
  finally {
    childLoading[seg.id] = false
  }
}

async function toggleChildren(seg) {
  if (expanded[seg.id]) {
    expanded[seg.id] = false
    return
  }
  expanded[seg.id] = true
  if (childDrafts[seg.id] == null)
    childDrafts[seg.id] = ''
  if (!Array.isArray(childrenBySeg[seg.id]))
    await loadChildren(seg)
}

async function addChild(seg) {
  const content = String(childDrafts[seg.id] || '').trim()
  if (!content) {
    ElMessage.warning('请输入子分段内容')
    return
  }
  childSaving[seg.id] = true
  try {
    await addChildChunk(datasetId(), documentId(), seg.id, content)
    childDrafts[seg.id] = ''
    ElMessage.success('已添加子分段')
    await loadChildren(seg)
  }
  catch (e) {
    ElMessage.error(e.message || '添加失败')
  }
  finally {
    childSaving[seg.id] = false
  }
}

async function editChild(seg, child) {
  try {
    const { value } = await ElMessageBox.prompt('子分段内容', '编辑子分段', {
      inputValue: child.content || '',
      inputType: 'textarea',
      inputPattern: /\S+/,
      inputErrorMessage: '请输入内容',
    })
    await updateChildChunk(datasetId(), documentId(), seg.id, child.id, value.trim())
    ElMessage.success('已更新')
    await loadChildren(seg)
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
}

async function removeChild(seg, child) {
  try {
    await ElMessageBox.confirm('确认删除该子分段？', '删除子分段', { type: 'warning' })
    await deleteChildChunk(datasetId(), documentId(), seg.id, child.id)
    ElMessage.success('已删除')
    await loadChildren(seg)
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
}

onMounted(async () => {
  await loadDocument()
  await reload()
})

onBeforeUnmount(() => {
  stopImportPoll()
})

watch(
  () => [route.params.datasetId, route.params.documentId],
  async () => {
    page.value = 1
    stopImportPoll()
    await loadDocument()
    await reload()
  },
)
</script>

<style scoped>
.doc-detail {
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
.back {
  border: none;
  background: transparent;
  color: #667085;
  cursor: pointer;
  font-size: 12px;
  padding: 0;
  margin-bottom: 6px;
}
.page-header h1 {
  margin: 0;
  font-size: 20px;
  color: #101828;
  word-break: break-word;
}
.header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}
.meta {
  margin: 6px 0 0;
  font-size: 12px;
  color: #98a2b3;
}
.error-banner {
  margin-bottom: 12px;
}
.error-log {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.5;
  font-family: inherit;
}
.toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.search { max-width: 260px; }
.batch-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #475467;
}
.hidden-input {
  display: none;
}
.segment-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 120px;
}
.segment-card {
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 10px;
  padding: 12px 14px;
}
.seg-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.pos {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: #475467;
}
.stats {
  font-size: 12px;
  color: #98a2b3;
}
.actions {
  margin-left: auto;
  display: flex;
  gap: 4px;
}
.qa-label {
  margin: 0 0 4px;
  font-size: 12px;
  color: #667085;
}
.content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 13px;
  color: #344054;
  line-height: 1.5;
  max-height: 200px;
  overflow: auto;
}
.keywords {
  margin: 8px 0 0;
  font-size: 12px;
  color: #667085;
}
.children {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #eaecf0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.child-card {
  background: #f9fafb;
  border-radius: 8px;
  padding: 8px 10px;
}
.child-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  margin-top: 4px;
}
.child-add {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.child-empty {
  padding: 8px 0;
}
.file-list {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}
.file-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  color: #344054;
}
.empty {
  text-align: center;
  color: #98a2b3;
  padding: 32px;
}
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
