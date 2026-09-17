<template>
  <div class="web-source">
    <p v-if="loadError" class="hint error">{{ loadError }}</p>

    <el-radio-group :model-value="provider" class="providers" @update:model-value="onProviderChange">
      <el-radio-button
        v-for="p in providers"
        :key="p.value"
        :value="p.value"
        :disabled="!p.authed"
      >
        {{ p.label }}{{ p.authed ? '' : '（未授权）' }}
      </el-radio-button>
    </el-radio-group>

    <div v-if="!hasAnyAuth" class="empty-auth">
      <p>未检测到网页爬取数据源授权（Firecrawl / Jina / Watercrawl）。</p>
      <p class="hint">请在 Plugin Daemon 中安装并配置对应 datasource 插件凭证。</p>
      <el-button size="small" @click="reloadAuth">刷新授权</el-button>
    </div>

    <template v-else>
      <el-form label-position="top" class="form">
        <el-form-item label="起始 URL" required>
          <el-input :model-value="url" placeholder="https://..." @update:model-value="onUrlChange" />
        </el-form-item>
        <el-form-item label="爬取子页面">
          <el-switch :model-value="options.crawl_sub_pages" @update:model-value="patchOption('crawl_sub_pages', $event)" />
        </el-form-item>
        <el-form-item label="仅正文">
          <el-switch :model-value="options.only_main_content" @update:model-value="patchOption('only_main_content', $event)" />
        </el-form-item>
        <el-form-item label="数量上限">
          <el-input-number
            :model-value="Number(options.limit) || 10"
            :min="1"
            :max="100"
            @update:model-value="patchOption('limit', $event)"
          />
        </el-form-item>
        <el-form-item label="使用 sitemap">
          <el-switch :model-value="options.use_sitemap" @update:model-value="patchOption('use_sitemap', $event)" />
        </el-form-item>
      </el-form>

      <div class="toolbar">
        <el-button type="primary" size="small" :loading="crawling" :disabled="!url.trim()" @click="startCrawl">
          开始爬取
        </el-button>
        <span v-if="statusText" class="hint">{{ statusText }}</span>
      </div>

      <el-checkbox-group
        v-if="pages.length"
        :model-value="selectedUrls"
        class="page-list"
        @change="onSelectUrls"
      >
        <el-checkbox
          v-for="page in pages"
          :key="page.source_url"
          :label="page.source_url"
          class="page-item"
        >
          <span class="page-name">{{ page.title || page.source_url }}</span>
        </el-checkbox>
      </el-checkbox-group>
      <p v-if="pages.length" class="hint">已选 {{ selectedUrls.length }} / {{ pages.length }}</p>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createWebsiteCrawl, fetchWebsiteCrawlStatus } from '@/features/datasets/api/difyDatasetsApi.js'
import {
  fetchDatasourceAuthList,
  findDatasourceAuth,
  getDatasourceCredentials,
} from '@/features/datasets/api/difyDatasourceAuthApi.js'
import { DEFAULT_CRAWL_OPTIONS } from '@/features/datasets/model/createDocumentPayload.js'

const PROVIDER_DEFS = [
  { value: 'jinareader', label: 'Jina Reader', match: ['jinareader', 'jina'] },
  { value: 'firecrawl', label: 'Firecrawl', match: ['firecrawl'] },
  { value: 'watercrawl', label: 'Watercrawl', match: ['watercrawl'] },
]

const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({
      provider: 'jinareader',
      url: '',
      jobId: '',
      pages: [],
      selectedUrls: [],
      options: { ...DEFAULT_CRAWL_OPTIONS },
    }),
  },
})

const emit = defineEmits(['update:modelValue'])

const loadError = ref('')
const authMap = ref({})
const crawling = ref(false)
const statusText = ref('')
let pollTimer = null

const provider = computed(() => props.modelValue?.provider || 'jinareader')
const url = computed(() => props.modelValue?.url || '')
const options = computed(() => props.modelValue?.options || { ...DEFAULT_CRAWL_OPTIONS })
const pages = computed(() => props.modelValue?.pages || [])
const selectedUrls = computed(() => props.modelValue?.selectedUrls || [])

const providers = computed(() => PROVIDER_DEFS.map(p => ({
  ...p,
  authed: !!authMap.value[p.value],
})))

const hasAnyAuth = computed(() => providers.value.some(p => p.authed))

function patch(partial) {
  emit('update:modelValue', { ...props.modelValue, ...partial })
}

function patchOption(key, value) {
  patch({ options: { ...options.value, [key]: value } })
}

function onProviderChange(value) {
  stopPoll()
  patch({
    provider: value,
    jobId: '',
    pages: [],
    selectedUrls: [],
  })
  statusText.value = ''
}

function onUrlChange(value) {
  patch({ url: value })
}

async function reloadAuth() {
  loadError.value = ''
  try {
    const res = await fetchDatasourceAuthList()
    const map = {}
    for (const def of PROVIDER_DEFS) {
      const auth = findDatasourceAuth(res, def.match)
      const creds = getDatasourceCredentials(auth)
      map[def.value] = creds.length > 0
    }
    authMap.value = map
    const current = providers.value.find(p => p.value === provider.value)
    if (current && !current.authed) {
      const first = providers.value.find(p => p.authed)
      if (first)
        onProviderChange(first.value)
    }
  }
  catch (e) {
    loadError.value = e.message || '数据源授权加载失败（需 Plugin Daemon）'
    authMap.value = {}
  }
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function pollStatus(jobId) {
  try {
    const res = await fetchWebsiteCrawlStatus(jobId, provider.value)
    const status = String(res.status || '').toLowerCase()
    const data = res.data || []
    statusText.value = `状态 ${status} · ${res.current ?? data.length}/${res.total ?? data.length}`
    if (data.length) {
      patch({
        pages: data,
        selectedUrls: data.map(d => d.source_url).filter(Boolean),
      })
    }
    if (status === 'completed') {
      stopPoll()
      crawling.value = false
      ElMessage.success('爬取完成')
    }
    else if (status === 'error' || status === 'failed') {
      stopPoll()
      crawling.value = false
      ElMessage.error(res.message || '爬取失败')
    }
  }
  catch (e) {
    stopPoll()
    crawling.value = false
    ElMessage.error(e.message || '查询爬取状态失败')
  }
}

async function startCrawl() {
  const startUrl = url.value.trim()
  if (!startUrl) {
    ElMessage.warning('请输入 URL')
    return
  }
  stopPoll()
  crawling.value = true
  statusText.value = '提交任务…'
  try {
    const opts = { ...options.value }
    if (opts.max_depth === '' || opts.max_depth == null)
      delete opts.max_depth
    const res = await createWebsiteCrawl({
      provider: provider.value,
      url: startUrl,
      options: opts,
    })
    const jobId = res.job_id || res.jobId
    if (!jobId)
      throw new Error('未返回 job_id')
    patch({ jobId, pages: [], selectedUrls: [] })
    statusText.value = '爬取中…'
    await pollStatus(jobId)
    pollTimer = setInterval(() => pollStatus(jobId), 2500)
  }
  catch (e) {
    crawling.value = false
    ElMessage.error(e.message || '启动爬取失败')
  }
}

function onSelectUrls(urls) {
  patch({ selectedUrls: urls })
}

onMounted(reloadAuth)
onBeforeUnmount(stopPoll)
</script>

<style scoped>
.web-source { margin-top: 8px; }
.providers { margin-bottom: 12px; flex-wrap: wrap; }
.empty-auth {
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px dashed #d0d5dd;
}
.form { max-width: 520px; }
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
  max-height: 260px;
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
.page-name {
  font-size: 13px;
  word-break: break-all;
}
.hint { margin: 0; font-size: 12px; color: #667085; }
.hint.error { color: #b42318; }
</style>
