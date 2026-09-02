<template>
  <!-- Tool plugin marketplace install — mirrors InstallFromMarketplace for models -->
  <section class="marketplace">
    <div class="marketplace-head">
      <button type="button" class="collapse-btn" @click="collapsed = !collapsed">
        <span class="arrow" :class="{ closed: collapsed }">▾</span>
        <span>从市场安装工具插件</span>
      </button>
      <div class="head-actions">
        <a
          href="https://marketplace.dify.ai/?category=tool"
          target="_blank"
          rel="noopener noreferrer"
        >
          Dify 工具市场 ↗
        </a>
        <button
          type="button"
          class="primary"
          :disabled="!missingSuggested.length || !!installingKey"
          @click="installAllMissing"
        >
          {{ installingKey === '__all__' ? '安装中…' : '一键安装常用工具' }}
        </button>
      </div>
    </div>

    <div v-if="!collapsed" class="marketplace-body">
      <div class="search-row">
        <input
          v-model="searchText"
          type="search"
          placeholder="搜索市场工具插件…"
          @keydown.enter.prevent="runSearch"
        />
        <button type="button" class="ghost" :disabled="searching" @click="runSearch">
          {{ searching ? '搜索中…' : '搜索' }}
        </button>
      </div>

      <p v-if="loadingSuggested" class="hint">正在加载常用工具插件…</p>
      <p v-else-if="!displayPlugins.length" class="hint">
        {{ searchText.trim() ? '未找到匹配插件，可换关键词或打开官方市场。' : '常用插件均已安装，可在上方授权后使用。' }}
      </p>
      <div v-else class="plugin-grid">
        <div v-for="plugin in displayPlugins" :key="plugin.key" class="plugin-card">
          <div>
            <strong>{{ plugin.label }}</strong>
            <p>{{ plugin.org }}/{{ plugin.name }}</p>
            <p v-if="plugin.brief" class="brief">{{ plugin.brief }}</p>
          </div>
          <button
            type="button"
            class="install-btn"
            :disabled="!!installingKey || isInstalled(plugin)"
            @click="installOne(plugin)"
          >
            {{ isInstalled(plugin) ? '已安装' : (installingKey === plugin.key ? '安装中…' : '安装') }}
          </button>
        </div>
      </div>
      <p v-if="installMessage" class="hint" :class="{ error: installError }">{{ installMessage }}</p>
      <p class="hint tip">
        安装完成后请点上方「刷新」，再选择提供商填写 API Key（如需要），然后在工具节点中选用。
      </p>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  SUGGESTED_TOOL_PLUGINS,
  fetchMarketplacePlugin,
  fetchPluginInstallTask,
  installPluginsFromMarketplace,
  searchMarketplacePlugins,
} from '@/features/integrations/api/difyPluginsApi.js'

const props = defineProps({
  /** Already-installed builtin provider ids / plugin ids */
  installedIds: { type: Array, default: () => [] },
})

const emit = defineEmits(['installed'])

const collapsed = ref(false)
const loadingSuggested = ref(false)
const suggestedPlugins = ref([])
const searchText = ref('')
const searching = ref(false)
const searchResults = ref([])
const searchActive = ref(false)
const installingKey = ref('')
const installMessage = ref('')
const installError = ref(false)

const installedSet = computed(() => new Set((props.installedIds || []).filter(Boolean)))

function isInstalled(plugin) {
  const id = `${plugin.org}/${plugin.name}`
  if (installedSet.value.has(id) || installedSet.value.has(plugin.name))
    return true
  return [...installedSet.value].some(
    p => p === id || p.startsWith(`${id}/`) || p === plugin.name || String(p).includes(id),
  )
}

const missingSuggested = computed(() =>
  suggestedPlugins.value.filter(plugin => !isInstalled(plugin)),
)

const displayPlugins = computed(() => {
  if (searchActive.value)
    return searchResults.value
  return missingSuggested.value
})

async function loadSuggestedPlugins() {
  loadingSuggested.value = true
  const list = []
  for (const item of SUGGESTED_TOOL_PLUGINS) {
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
    }
    catch {
      // skip unavailable
    }
  }
  suggestedPlugins.value = list
  loadingSuggested.value = false
}

async function runSearch() {
  const q = searchText.value.trim()
  if (!q) {
    searchActive.value = false
    searchResults.value = []
    return
  }
  searching.value = true
  searchActive.value = true
  try {
    const result = await searchMarketplacePlugins({
      category: 'tool',
      query: q,
      page: 1,
      page_size: 24,
    })
    searchResults.value = result?.plugins || []
  }
  catch (e) {
    searchResults.value = []
    ElMessage.error(e.message || '搜索失败')
  }
  finally {
    searching.value = false
  }
}

async function waitForInstallTask(taskId) {
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
    if (!result?.all_installed) {
      const taskId = result?.task_id || result?.data?.task_id
      if (taskId)
        await waitForInstallTask(taskId)
    }
    installMessage.value = '安装完成，正在刷新工具列表…'
    ElMessage.success('工具插件已安装')
    await new Promise(resolve => setTimeout(resolve, 500))
    emit('installed')
  }
  catch (e) {
    installError.value = true
    installMessage.value = e.response?.data?.message || e.message || '安装失败'
  }
  finally {
    installingKey.value = ''
  }
}

async function installOne(plugin) {
  if (isInstalled(plugin) || !plugin.latest_package_identifier)
    return
  await installByIdentifiers([plugin.latest_package_identifier], plugin.key)
}

async function installAllMissing() {
  const identifiers = missingSuggested.value
    .map(item => item.latest_package_identifier)
    .filter(Boolean)
  if (!identifiers.length) return
  await installByIdentifiers(identifiers, '__all__')
}

onMounted(loadSuggestedPlugins)
</script>

<style scoped>
.marketplace {
  margin-top: 8px;
  padding: 12px 16px 16px;
  border-top: 1px solid #eaecf0;
  background: #fbfcfe;
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
.arrow.closed { transform: rotate(-90deg); }
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
.search-row {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.search-row input {
  flex: 1;
  height: 34px;
  padding: 0 10px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  font-size: 13px;
}
.ghost {
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #fff;
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
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
.install-btn { flex-shrink: 0; }
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
  background: #fff;
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
.hint.error { color: #b42318; }
.hint.tip { margin-top: 10px; }
</style>
