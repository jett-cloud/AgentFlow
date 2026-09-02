<template>
  <div class="detail-page">
    <header class="page-header">
      <RouterLink class="back-link" :to="listPath">← 返回市场列表</RouterLink>
    </header>

    <div v-if="loading" class="state">正在加载插件详情…</div>
    <div v-else-if="error" class="state error">{{ error }}</div>
    <article v-else-if="plugin" class="detail-card">
      <div class="hero">
        <img
          v-if="plugin.icon"
          :src="plugin.icon"
          alt=""
          class="icon"
          @error="iconFailed = true"
        >
        <div v-if="!plugin.icon || iconFailed" class="icon placeholder">{{ (plugin.label || '?').slice(0, 1) }}</div>
        <div class="hero-text">
          <h1>{{ plugin.label || plugin.name }}</h1>
          <p class="meta">{{ plugin.org }}/{{ plugin.name }}
            <template v-if="plugin.latest_version"> · v{{ plugin.latest_version }}</template>
            <template v-if="plugin.category"> · {{ plugin.category }}</template>
          </p>
          <p class="brief">{{ plugin.brief || '暂无简介' }}</p>
        </div>
        <div class="actions">
          <button
            type="button"
            class="primary"
            :disabled="installing || isInstalled"
            @click="handleInstall"
          >
            {{ isInstalled ? '已安装' : (installing ? '安装中…' : '安装到工作区') }}
          </button>
          <RouterLink class="ghost" :to="integrationsPath">管理已安装</RouterLink>
        </div>
      </div>

      <section class="section">
        <h2>详细说明</h2>
        <div class="description">{{ plugin.description || plugin.brief || '暂无详细描述。' }}</div>
      </section>
    </article>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchInstalledPlugins,
  fetchMarketplacePlugin,
  findInstallationForPluginId,
  unwrapPluginList,
} from '@/features/integrations/api/difyPluginsApi.js'
import { installMarketplacePackage } from './marketplaceInstall.js'
import { integrationsTabPath, MARKETPLACE_ROUTES } from './marketplaceRoutes.js'

const props = defineProps({
  category: { type: String, required: true },
})

const route = useRoute()
const loading = ref(false)
const installing = ref(false)
const error = ref('')
const plugin = ref(null)
const installedPlugins = ref([])
const iconFailed = ref(false)

const org = computed(() => String(route.params.org || ''))
const name = computed(() => String(route.params.name || ''))
const listPath = computed(() => (
  props.category === 'model' ? MARKETPLACE_ROUTES.models : MARKETPLACE_ROUTES.tools
))
const integrationsPath = computed(() => (
  integrationsTabPath(props.category === 'model' ? 'models' : 'tools')
))
const isInstalled = computed(() => {
  if (!plugin.value) return false
  return !!findInstallationForPluginId(installedPlugins.value, plugin.value.plugin_id)
})

async function loadInstalled() {
  try {
    const payload = await fetchInstalledPlugins({ page_size: 100 })
    installedPlugins.value = unwrapPluginList(payload)
  }
  catch {
    installedPlugins.value = []
  }
}

async function reload() {
  loading.value = true
  error.value = ''
  iconFailed.value = false
  try {
    plugin.value = await fetchMarketplacePlugin(org.value, name.value)
    await loadInstalled()
  }
  catch (e) {
    error.value = e.message || '加载详情失败'
    plugin.value = null
  }
  finally {
    loading.value = false
  }
}

async function handleInstall() {
  if (!plugin.value?.latest_package_identifier) return
  installing.value = true
  try {
    await installMarketplacePackage(plugin.value.latest_package_identifier)
    await loadInstalled()
    ElMessage.success('插件已安装')
  }
  catch (e) {
    ElMessage.error(e.response?.data?.message || e.message || '安装失败')
  }
  finally {
    installing.value = false
  }
}

watch(() => [org.value, name.value, props.category], reload)
onMounted(reload)
</script>

<style scoped>
.detail-page {
  box-sizing: border-box;
  min-height: 100%;
  padding: 20px 24px 32px;
  background: var(--af-page);
  color: var(--af-text-primary);
  font-family: var(--font-sans);
}
.back-link { color: var(--af-brand-strong); font-size: 12px; font-weight: 550; text-decoration: none; }
.detail-card {
  margin-top: 12px;
  border: 1px solid #eaecf0;
  border-radius: 14px;
  background: #fff;
  padding: 20px;
  box-shadow: 0 4px 16px rgb(16 24 40 / 4%);
}
.hero {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr) auto;
  gap: 16px;
  align-items: start;
}
.icon {
  width: 64px;
  height: 64px;
  border-radius: 12px;
  object-fit: cover;
  background: #f2f4f7;
}
.icon.placeholder {
  display: grid;
  place-items: center;
  color: var(--af-brand-strong);
  font-size: 22px;
  font-weight: 700;
  background: var(--af-brand-soft);
}
.hero-text h1 { margin: 0; font-size: 22px; }
.meta { margin: 6px 0 0; color: #98a2b3; font-size: 12px; }
.brief { margin: 10px 0 0; color: #475467; font-size: 14px; line-height: 1.55; }
.actions { display: flex; flex-direction: column; gap: 8px; }
.primary, .ghost {
  border-radius: 8px;
  padding: 9px 14px;
  font-size: 13px;
  cursor: pointer;
  text-align: center;
  text-decoration: none;
  font-family: var(--font-sans);
  font-weight: 550;
  transition: background-color var(--af-transition), border-color var(--af-transition), transform 90ms ease;
}
.primary { border: 1px solid var(--af-brand); background: var(--af-brand); color: #fff; }
.primary:hover:not(:disabled) { border-color: var(--af-brand-strong); background: var(--af-brand-strong); }
.primary:active:not(:disabled), .ghost:active:not(:disabled) { transform: scale(.98); }
.primary:focus-visible, .ghost:focus-visible { outline: 3px solid var(--af-focus-ring); outline-offset: 1px; }
.primary:disabled { opacity: .55; cursor: not-allowed; }
.ghost { border: 1px solid var(--af-border-strong); background: #fff; color: var(--af-text-secondary); }
.section { margin-top: 24px; padding-top: 18px; border-top: 1px solid #eaecf0; }
.section h2 { margin: 0 0 10px; font-size: 15px; }
.description {
  white-space: pre-wrap;
  color: #344054;
  font-size: 13px;
  line-height: 1.65;
}
.state { padding: 24px; color: #667085; }
.state.error { color: #b42318; }
@media (max-width: 800px) {
  .hero { grid-template-columns: 48px minmax(0, 1fr); }
  .actions { grid-column: 1 / -1; flex-direction: row; }
}
</style>
