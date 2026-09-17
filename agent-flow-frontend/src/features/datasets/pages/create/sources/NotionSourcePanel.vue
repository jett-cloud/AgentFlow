<template>
  <div class="notion-source">
    <p v-if="loadError" class="hint error">{{ loadError }}</p>
    <div v-else-if="!credentials.length" class="empty-auth">
      <p>未检测到 Notion 数据源授权。</p>
      <p class="hint">需安装并授权 <code>langgenius/notion_datasource</code>（Plugin Daemon）。</p>
      <el-button size="small" :loading="oauthLoading" @click="startOAuth">尝试 OAuth 授权</el-button>
      <el-button size="small" @click="reload">刷新授权</el-button>
    </div>
    <template v-else>
      <el-form label-position="top">
        <el-form-item label="Notion 凭证" required>
          <el-select
            :model-value="credentialId"
            style="width: 100%"
            placeholder="选择凭证"
            @update:model-value="onCredentialChange"
          >
            <el-option
              v-for="c in credentials"
              :key="c.id"
              :label="c.name || c.id"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="toolbar">
        <el-button size="small" :loading="pagesLoading" @click="loadPages">刷新页面列表</el-button>
        <span class="hint">已选 {{ selectedPages.length }} 页</span>
      </div>
      <el-checkbox-group :model-value="selectedIds" class="page-list" @change="onSelectIds">
        <el-checkbox
          v-for="page in pages"
          :key="page.page_id"
          :label="page.page_id"
          class="page-item"
        >
          <span class="page-name">{{ page.page_name || page.page_id }}</span>
          <span class="page-meta">{{ page.type || 'page' }}</span>
        </el-checkbox>
      </el-checkbox-group>
      <p v-if="!pagesLoading && !pages.length" class="hint">暂无页面，请确认凭证权限。</p>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchDatasourceAuthList,
  fetchDatasourceOAuthUrl,
  fetchNotionPreImportPages,
  findDatasourceAuth,
  getDatasourceCredentials,
} from '@/features/datasets/api/difyDatasourceAuthApi.js'

const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({ credentialId: '', pages: [] }),
  },
  datasetId: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue'])

const loadError = ref('')
const credentials = ref([])
const pages = ref([])
const pagesLoading = ref(false)
const oauthLoading = ref(false)
const authProvider = ref('notion_datasource')

const credentialId = computed(() => props.modelValue?.credentialId || '')
const selectedPages = computed(() => props.modelValue?.pages || [])
const selectedIds = computed(() => selectedPages.value.map(p => p.page_id))

function patch(partial) {
  emit('update:modelValue', { ...props.modelValue, ...partial })
}

async function reload() {
  loadError.value = ''
  try {
    const res = await fetchDatasourceAuthList()
    const auth = findDatasourceAuth(res, ['notion_datasource', 'notion'])
    credentials.value = getDatasourceCredentials(auth)
    if (auth?.provider)
      authProvider.value = auth.provider
    if (!credentialId.value && credentials.value.length)
      patch({ credentialId: credentials.value[0].id, pages: [] })
  }
  catch (e) {
    loadError.value = e.message || '数据源授权加载失败（需 Plugin Daemon）'
    credentials.value = []
  }
}

async function startOAuth() {
  oauthLoading.value = true
  try {
    const res = await fetchDatasourceOAuthUrl(authProvider.value)
    const url = res?.authorization_url
    if (!url)
      throw new Error('未返回 authorization_url')
    window.open(url, '_blank', 'noopener')
    ElMessage.info('请在新窗口完成授权后点「刷新授权」')
  }
  catch (e) {
    ElMessage.error(e.message || '无法获取 OAuth 地址')
  }
  finally {
    oauthLoading.value = false
  }
}

function flattenNotionInfo(notionInfo) {
  const workspaces = Array.isArray(notionInfo) ? notionInfo : (notionInfo ? [notionInfo] : [])
  const list = []
  for (const ws of workspaces) {
    const workspaceId = ws.workspace_id || ws.id || ''
    const pagesInWs = ws.pages || ws.notion_info || []
    for (const page of pagesInWs) {
      list.push({
        page_id: page.page_id || page.id,
        page_name: page.page_name || page.name || '',
        page_icon: page.page_icon || null,
        type: page.type || 'page',
        parent_id: page.parent_id || '',
        workspace_id: workspaceId || page.workspace_id || '',
        is_bound: page.is_bound,
      })
    }
  }
  return list.filter(p => p.page_id)
}

async function loadPages() {
  if (!credentialId.value)
    return
  pagesLoading.value = true
  try {
    const res = await fetchNotionPreImportPages({
      credentialId: credentialId.value,
      datasetId: props.datasetId || undefined,
    })
    pages.value = flattenNotionInfo(res?.notion_info || res?.data || res)
  }
  catch (e) {
    ElMessage.error(e.message || 'Notion 页面加载失败')
    pages.value = []
  }
  finally {
    pagesLoading.value = false
  }
}

function onCredentialChange(id) {
  patch({ credentialId: id, pages: [] })
  loadPages()
}

function onSelectIds(ids) {
  const idSet = new Set(ids)
  patch({ pages: pages.value.filter(p => idSet.has(p.page_id)) })
}

onMounted(async () => {
  await reload()
  if (credentialId.value)
    await loadPages()
})

watch(() => props.datasetId, () => {
  if (credentialId.value)
    loadPages()
})
</script>

<style scoped>
.notion-source { margin-top: 8px; }
.empty-auth {
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px dashed #d0d5dd;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.page-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 280px;
  overflow: auto;
  border: 1px solid #eaecf0;
  border-radius: 8px;
  padding: 8px;
}
.page-item {
  margin-right: 0;
  height: auto;
  padding: 4px 0;
}
.page-name { margin-right: 8px; }
.page-meta { color: #98a2b3; font-size: 12px; }
.hint { margin: 0; font-size: 12px; color: #667085; }
.hint.error { color: #b42318; }
code { font-size: 12px; }
</style>
