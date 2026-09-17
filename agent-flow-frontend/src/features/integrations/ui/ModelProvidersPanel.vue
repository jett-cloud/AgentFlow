<template>
  <div class="model-providers-panel" :class="{ embedded }">
    <header class="toolbar">
      <div class="toolbar-left">
        <h2 v-if="!embedded">模型提供商</h2>
        <input
          v-model.trim="searchText"
          type="search"
          class="search-input"
          placeholder="搜索模型"
        >
      </div>
      <div class="toolbar-right">
        <RouterLink class="ghost link-btn" to="/integrations/marketplace/models">浏览市场</RouterLink>
        <button type="button" class="ghost" :disabled="loading" @click="reload">刷新</button>
        <button v-if="!embedded" type="button" aria-label="关闭" @click="$emit('close')">×</button>
      </div>
    </header>

    <div v-if="loading" class="state">正在加载模型提供商…</div>
    <div v-else-if="error" class="state error">{{ error }}</div>
    <div v-else class="body">
      <div v-if="showEmptyProvider" class="empty-box">
        <strong>还没有已配置的模型提供商</strong>
        <p>
          请先
          <RouterLink to="/integrations/marketplace/models">前往模型市场</RouterLink>
          安装主流厂商，再配置 API Key。
        </p>
      </div>

      <section v-if="showConfiguredProviders" class="section">
        <div class="card-list">
          <ProviderAddedCard
            v-for="item in filteredConfiguredProviders"
            :key="item.provider"
            ref="configuredCardRefs"
            :provider="item"
            :can-uninstall="!!installationIdFor(item)"
            :uninstalling="uninstallingProvider === item.provider"
            @configure="openCredentialModal"
            @uninstall="handleUninstall"
          />
        </div>
      </section>

      <section v-if="showNotConfiguredProviders" class="section">
        <h3 class="section-title">待配置</h3>
        <div class="card-list">
          <ProviderAddedCard
            v-for="item in filteredNotConfiguredProviders"
            :key="item.provider"
            ref="notConfiguredCardRefs"
            :provider="item"
            not-configured
            :can-uninstall="!!installationIdFor(item)"
            :uninstalling="uninstallingProvider === item.provider"
            @configure="openCredentialModal"
            @uninstall="handleUninstall"
          />
        </div>
      </section>

      <div
        v-if="!showConfiguredProviders && !showNotConfiguredProviders"
        class="state compact"
      >
        未找到匹配的模型提供商（可先浏览市场安装）
      </div>
    </div>

    <ProviderCredentialModal
      :visible="credentialModalVisible"
      :provider="credentialProvider"
      @close="closeCredentialModal"
      @saved="handleCredentialSaved"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchInstalledPlugins,
  findInstallationForPluginId,
  uninstallPlugin,
  unwrapPluginList,
} from '@/features/integrations/api/difyPluginsApi.js'
import { useModelStore } from '@/features/integrations/state/useModelStore.js'
import ProviderAddedCard from './ProviderAddedCard.vue'
import ProviderCredentialModal from './ProviderCredentialModal.vue'
import {
  filterProvidersBySearch,
  isProviderConfigured,
  providerToPluginId,
  sortConfiguredProviders,
} from '../lib/modelProviderHelpers.js'

defineProps({
  embedded: { type: Boolean, default: false },
})
defineEmits(['close'])

const modelStore = useModelStore()
const loading = ref(false)
const error = ref('')
const searchText = ref('')
const installedPlugins = ref([])
const uninstallingProvider = ref('')

const credentialModalVisible = ref(false)
const credentialProvider = ref(null)

const configuredCardRefs = ref([])
const notConfiguredCardRefs = ref([])

const catalog = computed(() => modelStore.providerCatalog || [])

const configuredProviders = computed(() => {
  const list = catalog.value.filter(isProviderConfigured)
  return sortConfiguredProviders(list)
})

const notConfiguredProviders = computed(() =>
  catalog.value.filter(item => !isProviderConfigured(item)),
)

const filteredConfiguredProviders = computed(() =>
  filterProvidersBySearch(configuredProviders.value, searchText.value),
)

const filteredNotConfiguredProviders = computed(() =>
  filterProvidersBySearch(notConfiguredProviders.value, searchText.value),
)

const showEmptyProvider = computed(() => !configuredProviders.value.length)
const showConfiguredProviders = computed(() => !!filteredConfiguredProviders.value.length)
const showNotConfiguredProviders = computed(() => !!filteredNotConfiguredProviders.value.length)

function installationIdFor(provider) {
  const pluginId = providerToPluginId(provider?.provider)
  const installation = findInstallationForPluginId(installedPlugins.value, pluginId)
    || findInstallationForPluginId(installedPlugins.value, provider?.provider)
  return installation?.installation_id || installation?.id || ''
}

async function loadInstalledPlugins() {
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
  try {
    await Promise.all([
      modelStore.fetchProviderCatalog(true),
      modelStore.fetchModelList(true),
      loadInstalledPlugins(),
    ])
  }
  catch (e) {
    error.value = e.message || '加载失败'
  }
  finally {
    loading.value = false
  }
}

function openCredentialModal(provider) {
  credentialProvider.value = provider
  credentialModalVisible.value = true
}

function closeCredentialModal() {
  credentialModalVisible.value = false
  credentialProvider.value = null
}

async function handleCredentialSaved() {
  await reload()
  const cards = [
    ...(configuredCardRefs.value || []),
    ...(notConfiguredCardRefs.value || []),
  ].flat()
  await Promise.all(
    cards
      .filter(card => typeof card?.refresh === 'function')
      .map(card => card.refresh()),
  )
}

async function handleUninstall(provider) {
  const installationId = installationIdFor(provider)
  if (!installationId) {
    ElMessage.warning('未找到可卸载的插件安装记录')
    return
  }
  try {
    await ElMessageBox.confirm(`确定卸载模型提供商「${provider.provider}」？`, '卸载插件', {
      type: 'warning',
      confirmButtonText: '确定卸载',
      cancelButtonText: '取消',
    })
  }
  catch {
    return
  }
  uninstallingProvider.value = provider.provider
  try {
    await uninstallPlugin(installationId)
    ElMessage.success('模型插件已卸载')
    await reload()
  }
  catch (e) {
    ElMessage.error(e.response?.data?.message || e.message || '卸载失败')
  }
  finally {
    uninstallingProvider.value = ''
  }
}

onMounted(reload)
</script>

<style scoped>
.model-providers-panel {
  display: flex;
  height: 100%;
  min-height: 420px;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid #eaecf0;
}
.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.toolbar h2 {
  margin: 0;
  font-size: 15px;
  color: #101828;
}
.search-input {
  width: 200px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 12px;
}
.ghost,
.link-btn,
button[aria-label='关闭'] {
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #fff;
  padding: 6px 10px;
  cursor: pointer;
  text-decoration: none;
  color: #344054;
  font-size: 12px;
}
.link-btn { color: var(--af-brand-strong); font-weight: 550; }
button[aria-label='关闭'] {
  border: 0;
  background: transparent;
  font-size: 18px;
}
.body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 16px 16px;
}
.section { margin-bottom: 16px; }
.section-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: #101828;
}
.card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.empty-box {
  margin-bottom: 16px;
  border-radius: 10px;
  background: #f2f4f7;
  padding: 16px;
}
.empty-box strong {
  display: block;
  font-size: 13px;
  color: #344054;
}
.empty-box p {
  margin: 6px 0 0;
  font-size: 12px;
  color: #667085;
}
.state {
  padding: 24px;
  color: #667085;
  font-size: 13px;
}
.state.error { color: #b42318; }
.state.compact { padding: 12px 0; }
</style>
