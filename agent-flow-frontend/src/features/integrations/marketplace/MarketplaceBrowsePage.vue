<template>
  <div class="marketplace-page">
    <header class="page-header">
      <div>
        <RouterLink class="back-link" :to="backTo">← 返回工作区集成</RouterLink>
        <h1>{{ title }}</h1>
        <p>{{ subtitle }}</p>
      </div>
      <div class="search-row">
        <input
          v-model.trim="query"
          type="search"
          placeholder="搜索插件名称或关键词"
          @keydown.enter.prevent="reload"
        >
        <button type="button" class="primary" :disabled="loading" @click="reload">搜索</button>
      </div>
    </header>

    <div v-if="total > 0" class="result-meta">
      <span>共 {{ total }} 个插件 · 第 {{ page }} / {{ totalPages }} 页</span>
      <nav class="pager" aria-label="分页">
        <button type="button" class="ghost" :disabled="loading || page <= 1" @click="goPrev">
          上一页
        </button>
        <button type="button" class="ghost" :disabled="loading || page >= totalPages" @click="goNext">
          下一页
        </button>
      </nav>
    </div>

    <div v-if="loading" class="state">正在加载市场插件…</div>
    <div v-else-if="error" class="state error">{{ error }}</div>
    <div v-else class="grid">
      <button
        v-for="item in plugins"
        :key="item.key || `${item.org}/${item.name}`"
        type="button"
        class="card"
        @click="openDetail(item)"
      >
        <div class="card-top">
          <img
            v-if="item.icon && !brokenIcons[item.key]"
            :src="item.icon"
            alt=""
            class="icon"
            @error="brokenIcons[item.key] = true"
          >
          <div v-else class="icon placeholder">{{ (item.label || item.name || '?').slice(0, 1) }}</div>
          <div>
            <strong>{{ item.label || item.name }}</strong>
            <span>{{ item.org }}/{{ item.name }}</span>
          </div>
        </div>
        <p>{{ item.brief || '暂无简介' }}</p>
        <footer>
          <em v-if="item.latest_version">v{{ item.latest_version }}</em>
          <em v-if="item.install_count != null">安装 {{ item.install_count }}</em>
          <span class="link">查看详情</span>
        </footer>
      </button>
      <p v-if="!plugins.length" class="state">未找到匹配插件</p>
    </div>

    <div v-if="totalPages > 1" class="pager-bottom">
      <button type="button" class="ghost" :disabled="loading || page <= 1" @click="goPrev">
        上一页
      </button>
      <span>第 {{ page }} / {{ totalPages }} 页</span>
      <button type="button" class="ghost" :disabled="loading || page >= totalPages" @click="goNext">
        下一页
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { searchMarketplacePlugins } from '@/features/integrations/api/difyPluginsApi.js'
import { integrationsTabPath, marketplaceDetailPath } from './marketplaceRoutes.js'

const props = defineProps({
  category: { type: String, required: true },
})

const PAGE_SIZE = 40
const router = useRouter()
const query = ref('')
const loading = ref(false)
const error = ref('')
const plugins = ref([])
const page = ref(1)
const total = ref(0)
const brokenIcons = reactive({})

const title = computed(() => (props.category === 'model' ? '模型提供商市场' : '工具插件市场'))
const subtitle = computed(() => (
  props.category === 'model'
    ? '浏览官方市场全部模型供应商插件（含图标与说明），安装后回到集成页配置 API Key。'
    : '浏览官方市场全部工具插件（含图标与说明），安装后回到集成页授权与管理。'
))
const backTo = computed(() => integrationsTabPath(props.category === 'model' ? 'models' : 'tools'))
const totalPages = computed(() => Math.max(1, Math.ceil((total.value || 0) / PAGE_SIZE)))

async function fetchPage(nextPage) {
  const result = await searchMarketplacePlugins({
    category: props.category === 'model' ? 'model' : 'tool',
    query: query.value,
    page: nextPage,
    page_size: PAGE_SIZE,
  })
  plugins.value = Array.isArray(result?.plugins) ? result.plugins : []
  page.value = result.page || nextPage
  total.value = Number(result.total || plugins.value.length) || 0
}

async function loadPage(nextPage) {
  if (nextPage < 1 || (totalPages.value && nextPage > totalPages.value && total.value > 0))
    return
  loading.value = true
  error.value = ''
  Object.keys(brokenIcons).forEach(key => delete brokenIcons[key])
  try {
    await fetchPage(nextPage)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  catch (e) {
    error.value = e.message || '加载市场失败'
    plugins.value = []
    if (nextPage === 1)
      total.value = 0
  }
  finally {
    loading.value = false
  }
}

function reload() {
  return loadPage(1)
}

function goPrev() {
  if (page.value > 1)
    return loadPage(page.value - 1)
}

function goNext() {
  if (page.value < totalPages.value)
    return loadPage(page.value + 1)
}

function openDetail(item) {
  router.push(marketplaceDetailPath(props.category === 'model' ? 'model' : 'tool', item.org, item.name))
}

watch(() => props.category, reload)
onMounted(reload)
</script>

<style scoped>
.marketplace-page {
  box-sizing: border-box;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 20px 24px 32px;
  background: var(--af-page);
  color: var(--af-text-primary);
  font-family: var(--font-sans);
}
.page-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.page-header h1 { margin: 6px 0 0; font-size: 20px; }
.page-header p { margin: 6px 0 0; color: var(--af-text-muted); font-size: 13px; }
.back-link { color: var(--af-brand-strong); font-size: 12px; font-weight: 550; text-decoration: none; }
.search-row { display: flex; gap: 8px; }
.search-row input {
  width: 260px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  padding: 8px 10px;
}
.primary, .ghost {
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  font-family: var(--font-sans);
  font-weight: 550;
  transition: background-color var(--af-transition), border-color var(--af-transition), color var(--af-transition), box-shadow var(--af-transition), transform 90ms ease;
}
.primary {
  border: 1px solid var(--af-brand);
  background: var(--af-brand);
  color: #fff;
}
.ghost {
  border: 1px solid var(--af-border-strong);
  background: #fff;
  color: #344054;
}
.primary:hover:not(:disabled) { border-color: var(--af-brand-strong); background: var(--af-brand-strong); }
.ghost:hover:not(:disabled) { background: var(--af-surface-subtle); }
.primary:active:not(:disabled), .ghost:active:not(:disabled) { transform: scale(.98); }
.primary:focus-visible, .ghost:focus-visible, .search-row input:focus-visible { outline: 3px solid var(--af-focus-ring); outline-offset: 1px; }
.primary:disabled, .ghost:disabled { opacity: .45; cursor: not-allowed; }
.result-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0 0 12px;
  color: #98a2b3;
  font-size: 12px;
}
.pager, .pager-bottom {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pager-bottom {
  justify-content: center;
  margin-top: 20px;
  color: #667085;
  font-size: 13px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  background: #fff;
  padding: 14px;
  text-align: left;
  cursor: pointer;
  font-family: var(--font-sans);
  transition: border-color var(--af-transition), box-shadow var(--af-transition), transform var(--af-transition);
}
.card:hover { border-color: var(--af-brand-border); box-shadow: 0 6px 18px rgb(24 30 42 / 8%); transform: translateY(-2px); }
.card:active { transform: translateY(0) scale(.99); }
.card-top { display: flex; gap: 10px; align-items: center; }
.card-top strong { display: block; font-size: 14px; }
.card-top span { color: #98a2b3; font-size: 11px; }
.icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  object-fit: cover;
  background: #f2f4f7;
  flex-shrink: 0;
}
.icon.placeholder {
  display: grid;
  place-items: center;
  color: var(--af-brand-strong);
  font-weight: 700;
  background: var(--af-brand-soft);
}
.card p {
  margin: 0;
  flex: 1;
  color: #475467;
  font-size: 12px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card footer {
  display: flex;
  gap: 10px;
  align-items: center;
  color: #98a2b3;
  font-size: 11px;
}
.card footer .link { margin-left: auto; color: var(--af-brand-strong); font-weight: 550; }
.state { padding: 24px; color: #667085; }
.state.error { color: #b42318; }
</style>
