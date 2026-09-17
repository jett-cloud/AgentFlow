<template>
  <!-- Mirror: web/.../model-provider-page/install-from-marketplace.tsx -->
  <section class="marketplace">
    <div class="marketplace-head">
      <button type="button" class="collapse-btn" @click="collapsed = !collapsed">
        <span class="arrow" :class="{ closed: collapsed }">▾</span>
        <span>从市场安装模型提供商</span>
      </button>
      <div class="head-actions">
        <a
          href="https://marketplace.dify.ai/?category=model"
          target="_blank"
          rel="noopener noreferrer"
        >
          Dify 市场 ↗
        </a>
        <button
          type="button"
          class="primary"
          :disabled="!missingPlugins.length || !!installingKey"
          @click="installAllMissing"
        >
          {{ installingKey === '__all__' ? '安装中…' : '一键安装未装主流厂商' }}
        </button>
      </div>
    </div>

    <div v-if="!collapsed" class="marketplace-body">
      <p v-if="loadingPlugins" class="hint">正在从 Dify 市场加载主流模型插件…</p>
      <p v-else-if="!suggestedPlugins.length" class="hint">市场插件加载失败，请检查网络后刷新。</p>
      <p v-else-if="!missingPlugins.length" class="hint success">主流厂商插件均已安装，可在上方配置 API Key。</p>
      <div v-else class="plugin-grid">
        <div v-for="plugin in filteredPlugins" :key="plugin.key" class="plugin-card">
          <div>
            <strong>{{ plugin.label }}</strong>
            <p>{{ plugin.org }}/{{ plugin.name }}</p>
            <p v-if="plugin.brief" class="brief">{{ plugin.brief }}</p>
          </div>
          <button
            type="button"
            class="install-btn"
            :disabled="!!installingKey"
            @click="installOne(plugin)"
          >
            {{ installingKey === plugin.key ? '安装中…' : '安装' }}
          </button>
        </div>
      </div>
      <p v-if="installMessage" class="hint" :class="{ error: installError }">{{ installMessage }}</p>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  SUGGESTED_MODEL_PLUGINS,
  fetchMarketplacePlugin,
  fetchPluginInstallTask,
  installPluginsFromMarketplace,
} from '@/features/integrations/api/difyPluginsApi.js'
import { providerToPluginId } from '../lib/modelProviderHelpers.js'

const props = defineProps({
  providers: { type: Array, default: () => [] },
  searchText: { type: String, default: '' },
})

const emit = defineEmits(['installed'])

const collapsed = ref(false)
const loadingPlugins = ref(false)
const suggestedPlugins = ref([])
const installingKey = ref('')
const installMessage = ref('')
const installError = ref(false)

const installedPluginIds = computed(() => {
  const set = new Set()
  for (const item of props.providers || []) {
    const pluginId = providerToPluginId(item.provider)
    if (pluginId)
      set.add(pluginId)
    // also support short ids
    set.add(item.provider)
  }
  return set
})

function isInstalled(plugin) {
  const id = `${plugin.org}/${plugin.name}`
  if (installedPluginIds.value.has(id))
    return true
  return [...installedPluginIds.value].some(
    p => p === id || p.startsWith(`${id}/`) || p === plugin.name,
  )
}

const missingPlugins = computed(() =>
  suggestedPlugins.value.filter(plugin => !isInstalled(plugin)),
)

const filteredPlugins = computed(() => {
  const keyword = String(props.searchText || '').trim().toLowerCase()
  const list = missingPlugins.value
  if (!keyword) return list
  return list.filter(plugin =>
    plugin.label.toLowerCase().includes(keyword)
    || plugin.name.toLowerCase().includes(keyword)
    || plugin.org.toLowerCase().includes(keyword),
  )
})

async function loadSuggestedPlugins() {
  loadingPlugins.value = true
  const list = []
  for (const item of SUGGESTED_MODEL_PLUGINS) {
    try {
      const plugin = await fetchMarketplacePlugin(item.org, item.name)
      list.push({
        key: `${item.org}/${item.name}`,
        org: item.org,
        name: item.name,
        label: item.title || plugin.label,
        brief: plugin.brief,
        latest_package_identifier: plugin.latest_package_identifier,
      })
    } catch {
      // skip unavailable marketplace entries
    }
  }
  suggestedPlugins.value = list
  loadingPlugins.value = false
}

async function waitForInstallTask(taskId) {
  // API shape: { task: PluginInstallTask } — see PluginFetchInstallTaskApi
  for (let i = 0; i < 90; i += 1) {
    const payload = await fetchPluginInstallTask(taskId)
    const task = payload?.task || payload?.data?.task || payload
    const status = String(task?.status || '').toLowerCase()
    if (status === 'success')
      return task
    if (status === 'failed') {
      const failed = (task?.plugins || []).find(
        item => String(item?.status || '').toLowerCase() === 'failed',
      )
      throw new Error(failed?.message || '插件安装失败')
    }
    await new Promise(resolve => setTimeout(resolve, 2000))
  }
  throw new Error('插件安装超时，请稍后点「刷新」')
}

async function installByIdentifiers(identifiers, key) {
  installingKey.value = key
  installMessage.value = ''
  installError.value = false
  try {
    const result = await installPluginsFromMarketplace(identifiers)
    // Already present in workspace — no async task
    if (!result?.all_installed) {
      const taskId = result?.task_id || result?.data?.task_id
      if (taskId)
        await waitForInstallTask(taskId)
    }
    installMessage.value = '安装完成，正在刷新提供商列表…'
    ElMessage.success('模型插件已安装')
    // Small delay so backend invalidate-on-success settles before reload
    await new Promise(resolve => setTimeout(resolve, 500))
    emit('installed')
  } catch (e) {
    installError.value = true
    installMessage.value = e.response?.data?.message || e.message || '安装失败'
  } finally {
    installingKey.value = ''
  }
}

async function installOne(plugin) {
  await installByIdentifiers([plugin.latest_package_identifier], plugin.key)
}

async function installAllMissing() {
  const identifiers = missingPlugins.value
    .map(item => item.latest_package_identifier)
    .filter(Boolean)
  if (!identifiers.length) return
  await installByIdentifiers(identifiers, '__all__')
}

watch(
  () => props.searchText,
  (value) => {
    if (value)
      collapsed.value = false
  },
)

onMounted(loadSuggestedPlugins)
</script>

<style scoped>
.marketplace {
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid #eaecf0;
}
.marketplace-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.collapse-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 0;
  background: transparent;
  padding: 0;
  font-size: 14px;
  font-weight: 600;
  color: #101828;
  cursor: pointer;
}
.arrow {
  display: inline-block;
  transition: transform 0.15s ease;
}
.arrow.closed {
  transform: rotate(-90deg);
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.head-actions a {
  font-size: 12px;
  color: var(--af-brand-strong);
  text-decoration: none;
}
.primary,
.install-btn {
  border: 1px solid var(--af-brand);
  border-radius: 8px;
  background: var(--af-brand);
  color: #fff;
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
}
.primary:disabled,
.install-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.install-btn {
  flex-shrink: 0;
}
.plugin-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.plugin-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid #eaecf0;
  border-radius: 10px;
  background: #f8fafc;
  padding: 12px;
}
.plugin-card strong {
  display: block;
  font-size: 13px;
  color: #101828;
}
.plugin-card p {
  margin: 4px 0 0;
  font-size: 11px;
  color: #667085;
}
.brief {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: #667085;
}
.hint.success {
  color: #027a48;
}
.hint.error {
  color: #b42318;
}
</style>
