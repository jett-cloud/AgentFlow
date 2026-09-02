<template>
  <div class="datasets-page">
    <header class="page-header">
      <div>
        <h1>知识库</h1>
        <p>导入文档、分段索引，供工作流「知识检索」节点调用。对齐 Dify `/datasets`。</p>
      </div>
      <div class="header-actions">
        <el-dropdown split-button type="primary" @click="goCreate">
          创建知识库
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="goCreate">导入已有文本</el-dropdown-item>
              <el-dropdown-item @click="openEmptyModal">创建空知识库</el-dropdown-item>
              <el-dropdown-item divided @click="goCreateFromPipeline">从知识流水线创建（P4）</el-dropdown-item>
              <el-dropdown-item @click="goConnect">连接外部知识库</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div class="toolbar">
      <el-input
        v-model="keyword"
        clearable
        placeholder="搜索知识库"
        class="search"
        @keyup.enter="reload"
        @clear="reload"
      />
      <el-button :loading="store.loading" @click="reload">刷新</el-button>
    </div>

    <p v-if="store.loadError" class="error">{{ store.loadError }}</p>

    <div v-loading="store.loading" class="card-grid">
      <article
        v-for="item in store.datasets"
        :key="item.id"
        class="dataset-card"
        @click="openDataset(item)"
      >
        <div class="card-top">
          <h3>{{ item.name }}</h3>
          <el-dropdown trigger="click" @command="cmd => onCardCommand(cmd, item)" @click.stop>
            <button type="button" class="more-btn" @click.stop>⋯</button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="open">打开</el-dropdown-item>
                <el-dropdown-item v-if="canDeleteDataset(item)" command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <p class="desc">{{ item.description || '暂无描述' }}</p>
        <div class="meta">
          <span>{{ item.document_count ?? 0 }} 文档</span>
          <span>{{ item.app_count ?? 0 }} 应用</span>
          <span>{{ indexingLabel(item) }}</span>
        </div>
      </article>

      <div v-if="!store.loading && !store.datasets.length" class="empty">
        <p>还没有知识库</p>
        <el-button type="primary" @click="goCreate">创建第一个知识库</el-button>
      </div>
    </div>

    <el-dialog v-model="emptyModalOpen" title="创建空知识库" width="420px">
      <el-input v-model="emptyName" placeholder="知识库名称" maxlength="40" show-word-limit />
      <template #footer>
        <el-button @click="emptyModalOpen = false">取消</el-button>
        <el-button type="primary" :loading="creatingEmpty" @click="createEmpty">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDatasetStore } from '@/features/datasets/state/useDatasetStore.js'
import { checkDatasetUsedInApp } from '@/features/datasets/api/difyDatasetsApi.js'
import { datasetLandingPath } from '@/features/datasets/model/hitTestingRequest.js'
import { getDatasetCapabilities } from '@/features/datasets/model/datasetCapabilities.js'

const router = useRouter()
const store = useDatasetStore()
const keyword = ref('')
const emptyModalOpen = ref(false)
const emptyName = ref('')
const creatingEmpty = ref(false)

function indexingLabel(item) {
  if (item.provider === 'external')
    return '外部'
  return item.indexing_technique === 'economy' ? '经济' : '高质量'
}

function goCreate() {
  router.push('/datasets/create')
}

function goConnect() {
  router.push('/datasets/connect')
}

function goCreateFromPipeline() {
  router.push('/datasets/create-from-pipeline')
}

function openEmptyModal() {
  emptyName.value = ''
  emptyModalOpen.value = true
}

async function createEmpty() {
  const name = emptyName.value.trim()
  if (!name) {
    ElMessage.warning('请输入名称')
    return
  }
  creatingEmpty.value = true
  try {
    const created = await store.createEmpty(name)
    emptyModalOpen.value = false
    ElMessage.success('已创建')
    router.push(`/datasets/${created.id}/documents`)
  }
  catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
  finally {
    creatingEmpty.value = false
  }
}

function openDataset(item) {
  router.push(datasetLandingPath(item))
}

function canDeleteDataset(item) {
  return getDatasetCapabilities(item?.permission_keys).canDelete
}

async function onCardCommand(cmd, item) {
  if (cmd === 'open') {
    openDataset(item)
    return
  }
  if (cmd === 'delete') {
    try {
      let tip = `确认删除知识库「${item.name}」？此操作不可恢复。`
      try {
        const used = await checkDatasetUsedInApp(item.id)
        if (used?.is_using)
          tip = `知识库「${item.name}」正被应用使用。${tip}`
      }
      catch { /* ignore */ }
      await ElMessageBox.confirm(tip, '删除知识库', {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      })
      await store.removeDataset(item.id)
      ElMessage.success('已删除')
    }
    catch (e) {
      if (e !== 'cancel' && e?.message)
        ElMessage.error(e.message)
    }
  }
}

function reload() {
  return store.loadDatasets({ keyword: keyword.value.trim() })
}

onMounted(() => {
  reload()
})
</script>

<style scoped>
.datasets-page {
  height: 100%;
  padding: 28px 32px 32px;
  box-sizing: border-box;
  background: var(--af-page);
  overflow: auto;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  width: min(100%, 1440px);
  margin: 0 auto 22px;
}
.page-header h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.025em;
  color: var(--af-text-primary);
}
.page-header p {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.5;
  color: var(--af-text-muted);
}
.toolbar {
  display: flex;
  gap: 8px;
  width: min(100%, 1440px);
  margin: 0 auto 16px;
}
.search {
  max-width: 280px;
}
.error {
  color: #b42318;
  font-size: 13px;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
  min-height: 120px;
  width: min(100%, 1440px);
  margin: 0 auto;
}
.dataset-card {
  background: var(--af-surface);
  border: 1px solid var(--af-border);
  border-radius: var(--af-radius-lg);
  padding: 16px;
  cursor: pointer;
  box-shadow: var(--af-shadow-sm);
  transition: border-color var(--af-transition), box-shadow var(--af-transition), transform var(--af-transition);
}
.dataset-card:hover {
  border-color: var(--af-brand-border);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
  transform: translateY(-1px);
}
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}
.card-top h3 {
  margin: 0;
  font-size: 15px;
  color: var(--af-text-primary);
}
.more-btn {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
  color: var(--af-text-muted);
  padding: 0 4px;
}
.desc {
  margin: 8px 0 12px;
  font-size: 12px;
  color: #667085;
  min-height: 32px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 12px;
  color: #98a2b3;
}
.empty {
  grid-column: 1 / -1;
  text-align: center;
  padding: 48px 16px;
  color: #667085;
}
</style>
