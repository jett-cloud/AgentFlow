<template>
  <div class="tools-auth-panel">
    <header class="embedded-header">
      <div>
        <h2>工具授权</h2>
        <p>管理已安装工具插件、凭证与卸载。从市场安装请进入独立市场页。</p>
      </div>
      <div class="header-actions">
        <RouterLink class="ghost studio-link" to="/integrations/marketplace/tools">浏览市场</RouterLink>
        <RouterLink class="ghost studio-link" to="/integrations/tools/ai-create">AI 创建插件</RouterLink>
        <button type="button" class="ghost" :disabled="loading" @click="reload">刷新</button>
      </div>
    </header>

    <div v-if="loading" class="state">正在加载工具提供商…</div>
    <div v-else-if="error" class="state error">{{ error }}</div>
    <div v-else class="body">
      <div class="provider-list">
        <button
          v-for="item in providers"
          :key="item.provider + ':' + item.providerType"
          type="button"
          class="provider-card"
          :class="{ active: selected?.provider === item.provider && selected?.providerType === item.providerType }"
          @click="selectProvider(item)"
        >
          <div class="card-row">
            <img
              v-if="item.iconMeta.type === 'url'"
              :src="item.iconMeta.value"
              alt=""
              class="tool-icon"
            >
            <div
              v-else
              class="tool-icon placeholder"
              :style="item.iconMeta.type === 'emoji' ? { background: item.iconMeta.background } : undefined"
            >
              {{ item.iconMeta.value }}
            </div>
            <div class="card-text">
              <strong>{{ item.label }}</strong>
              <span>
                工具插件
                ·
                {{ item.authorized ? `已授权 · ${item.toolCount} 个工具` : `未授权 · ${item.toolCount} 个工具` }}
              </span>
            </div>
          </div>
        </button>
        <p v-if="!providers.length" class="state compact">
          暂无工具插件。请
          <RouterLink to="/integrations/marketplace/tools">前往市场安装</RouterLink>
          。
        </p>
      </div>

      <div v-if="selected" class="detail">
        <div class="detail-head">
          <div>
            <h3>{{ selected.label }}</h3>
            <p class="hint">提供商 ID：{{ selected.provider }} · 工具插件</p>
          </div>
          <div class="detail-actions">
            <template v-if="selected.installationId">
              <RouterLink
                v-if="latestStudioSessionId"
                class="ghost studio-link"
                :to="{ path: '/integrations/tools/ai-create', query: { session: latestStudioSessionId } }"
              >
                打开对话
              </RouterLink>
              <RouterLink
                v-if="forkSourceSessionId"
                class="ghost studio-link primary-link"
                :to="{ path: '/integrations/tools/ai-create', query: { fork: forkSourceSessionId, intent: 'add_tool' } }"
              >
                新增工具
              </RouterLink>
              <RouterLink
                class="ghost studio-link"
                :to="blankSamePluginLink"
              >
                空白新建同名
              </RouterLink>
              <button
                type="button"
                class="danger"
                :disabled="uninstalling"
                @click="handleUninstall"
              >
                {{ uninstalling ? '卸载中…' : '卸载插件' }}
              </button>
            </template>
          </div>
        </div>
        <p
          v-if="selected.installationId && !studioSessionsLoading && !forkSourceSessionId"
          class="hint studio-hint"
        >
          尚无 Studio 草稿源码。「空白新建同名」仅预填身份，不会载入已装包文件。
        </p>

        <template>
          <div class="cred-list">
            <h4>已有凭证</h4>
            <div v-if="credentialsLoading" class="state compact">加载凭证…</div>
            <ul v-else-if="credentials.length">
              <li v-for="cred in credentials" :key="cred.id">
                <div>
                  <strong>{{ cred.name || cred.id }}</strong>
                  <span v-if="cred.is_default" class="badge">默认</span>
                </div>
                <div class="cred-actions">
                  <button type="button" class="link" :disabled="saving" @click="startEditCredential(cred)">编辑</button>
                  <button
                    v-if="!cred.is_default"
                    type="button"
                    class="link"
                    :disabled="saving"
                    @click="makeDefault(cred.id)"
                  >
                    设为默认
                  </button>
                  <button type="button" class="link danger-link" :disabled="saving" @click="handleDeleteCredential(cred)">
                    删除
                  </button>
                </div>
              </li>
            </ul>
            <p v-else class="hint">尚未配置凭证</p>
          </div>

          <div v-if="schemaFields.length" class="credential-form">
            <h4>{{ editingCredentialId ? '修改授权' : '添加授权' }}</h4>
            <CredentialSchemaFields
              :fields="schemaFields"
              :model-value="formValues"
              :disabled="saving"
              @update:model-value="onCredentialFormUpdate"
            />
            <label class="field">
              <span>凭证名称（可选）</span>
              <input v-model="credentialName" type="text" placeholder="团队默认" autocomplete="off">
            </label>
            <div class="actions">
              <button type="button" class="primary" :disabled="saving" @click="handleSave">
                {{ saving ? '保存中…' : (editingCredentialId ? '更新授权' : '保存授权') }}
              </button>
              <button
                v-if="editingCredentialId"
                type="button"
                class="ghost"
                :disabled="saving"
                @click="resetCredentialForm"
              >
                取消编辑
              </button>
            </div>
            <p v-if="formMessage" class="form-msg" :class="{ error: formError }">{{ formMessage }}</p>
          </div>
          <p v-else class="hint">该提供商无需额外 API Key，或仅支持 OAuth。</p>
        </template>

        <div class="tool-names">
          <h4>包含工具</h4>
          <ul>
            <li v-for="tool in selected.toolDetails" :key="tool.key">
              <details class="tool-detail">
                <summary>
                  <span>{{ tool.name }}</span>
                  <span class="tool-detail-chevron" aria-hidden="true">›</span>
                </summary>
                <p>{{ tool.description }}</p>
              </details>
            </li>
          </ul>
          <p v-if="!selected.toolDetails.length" class="hint">暂无工具明细</p>
        </div>
      </div>
      <div v-else class="state">选择左侧工具提供商以授权或查看详情</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addBuiltinCredential,
  deleteBuiltinCredential,
  fetchAllTools,
  fetchBuiltinCredentialInfo,
  fetchBuiltinCredentialSchema,
  fetchBuiltinCredentials,
  setDefaultBuiltinCredential,
  updateBuiltinCredential,
  unwrapCredentialList,
} from '@/features/integrations/api/difyToolsApi.js'
import {
  fetchInstalledPlugins,
  fetchStudioSessionsByInstallation,
  findInstallationForPluginId,
  uninstallToolPluginWithSessions,
  unwrapPluginList,
} from '@/features/integrations/api/difyPluginsApi.js'
import { useToolStore } from '@/features/integrations/state/useToolStore.js'
import { localizeToolText, toolProviderIcon } from '../lib/toolProviderHelpers.js'
import { buildToolDetails } from '../lib/toolDetails.js'
import {
  buildCredentialsPayload,
  buildInitialCredentialFormValues,
  normalizeCredentialFormFields,
} from '../lib/credentialFormHelpers.js'
import CredentialSchemaFields from './CredentialSchemaFields.vue'

const toolStore = useToolStore()
const loading = ref(false)
const error = ref('')
const providers = ref([])
const selected = ref(null)
const credentials = ref([])
const credentialsLoading = ref(false)
const schemaFields = ref([])
const formValues = reactive({})
const credentialName = ref('')
const editingCredentialId = ref('')
const saving = ref(false)
const uninstalling = ref(false)
const formMessage = ref('')
const formError = ref(false)
const installedPlugins = ref([])
const studioSessions = ref([])
const studioSessionsLoading = ref(false)

const latestStudioSessionId = computed(() => studioSessions.value[0]?.id || '')
const forkSourceSessionId = computed(() => {
  const withFiles = studioSessions.value.find(item => item.has_files)
  return withFiles?.id || studioSessions.value[0]?.id || ''
})
const blankSamePluginLink = computed(() => {
  const pluginId = selected.value?.pluginId || selected.value?.provider || ''
  const parts = String(pluginId).split('/').filter(Boolean)
  const query = {}
  if (parts.length >= 2) {
    query.author = parts[0]
    query.plugin = parts[1]
  }
  else if (parts.length === 1) {
    query.plugin = parts[0]
  }
  return { path: '/integrations/tools/ai-create', query }
})

function buildProviders(groups) {
  const list = []
  for (const item of groups?.builtin || []) {
    const provider = item.id || item.provider || item.name || item.plugin_id || ''
    if (!provider) continue
    const tools = item.tools || []
    const pluginId = item.plugin_id || provider
    const installation = findInstallationForPluginId(installedPlugins.value, pluginId)
      || findInstallationForPluginId(installedPlugins.value, provider)
    const card = {
      provider,
      providerType: 'builtin',
      pluginId,
      pluginUniqueIdentifier: item.plugin_unique_identifier || installation?.plugin_unique_identifier || '',
      installationId: installation?.installation_id || installation?.id || '',
      label: localizeToolText(item.label, item.name || provider),
      authorized: !!(item.is_team_authorization),
      toolCount: tools.length,
      toolDetails: buildToolDetails(tools),
      icon: item.icon,
      icon_small: item.icon_small,
      raw: item,
    }
    card.iconMeta = toolProviderIcon(card)
    list.push(card)
  }
  return list.sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans'))
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
    await loadInstalledPlugins()
    const groups = await fetchAllTools()
    providers.value = buildProviders(groups)
    await toolStore.fetchTools(true)
    if (selected.value) {
      const next = providers.value.find(
        item => item.provider === selected.value.provider && item.providerType === selected.value.providerType,
      )
      selected.value = next || null
      const tasks = [
        loadCredentials(selected.value.provider),
        loadSchema(selected.value.provider),
      ]
      if (selected.value.installationId)
        tasks.push(loadStudioSessions(selected.value))
      await Promise.all(tasks)
    }
  }
  catch (e) {
    error.value = e.message || '加载失败'
    providers.value = []
  }
  finally {
    loading.value = false
  }
}

onMounted(reload)

async function selectProvider(item) {
  selected.value = item
  resetCredentialForm()
  formMessage.value = ''
  formError.value = false
  schemaFields.value = []
  credentials.value = []
  studioSessions.value = []
  const tasks = [loadCredentials(item.provider), loadSchema(item.provider)]
  if (item.installationId)
    tasks.push(loadStudioSessions(item))
  await Promise.all(tasks)
}

async function loadStudioSessions(item) {
  studioSessionsLoading.value = true
  try {
    const payload = await fetchStudioSessionsByInstallation({
      installation_id: item.installationId,
      plugin_unique_identifier: item.pluginUniqueIdentifier || undefined,
    })
    const list = payload?.sessions || []
    studioSessions.value = [...list].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
  }
  catch {
    studioSessions.value = []
  }
  finally {
    studioSessionsLoading.value = false
  }
}

async function loadCredentials(provider) {
  credentialsLoading.value = true
  try {
    const payload = await fetchBuiltinCredentials(provider)
    credentials.value = unwrapCredentialList(payload)
    if (credentials.value.length && selected.value)
      selected.value = { ...selected.value, authorized: true }
  }
  catch {
    credentials.value = []
  }
  finally {
    credentialsLoading.value = false
  }
}

function normalizeSchemaFields(schema) {
  return normalizeCredentialFormFields(schema)
}

function onCredentialFormUpdate(next) {
  Object.keys(formValues).forEach(key => delete formValues[key])
  Object.assign(formValues, next || {})
}

function applyCredentialInitialValues() {
  Object.keys(formValues).forEach(key => delete formValues[key])
  Object.assign(formValues, buildInitialCredentialFormValues(schemaFields.value))
}

async function resolveCredentialType(provider) {
  try {
    const info = await fetchBuiltinCredentialInfo(provider, { silent: true })
    const supported = info?.supported_credential_types || info?.data?.supported_credential_types || []
    if (supported.includes('api-key'))
      return 'api-key'
    if (supported.includes('oauth2'))
      return 'oauth2'
    return supported[0] || 'api-key'
  }
  catch {
    return 'api-key'
  }
}

async function loadSchema(provider) {
  try {
    const credentialType = await resolveCredentialType(provider)
    const schema = await fetchBuiltinCredentialSchema(provider, credentialType)
    schemaFields.value = normalizeSchemaFields(schema)
    applyCredentialInitialValues()
  }
  catch (e) {
    schemaFields.value = []
    formError.value = true
    formMessage.value = e.message || '加载凭证表单失败'
  }
}

function buildCredentials() {
  return buildCredentialsPayload(schemaFields.value, formValues, {
    editing: !!editingCredentialId.value,
  })
}

function resetCredentialForm() {
  editingCredentialId.value = ''
  credentialName.value = ''
  applyCredentialInitialValues()
}

function startEditCredential(cred) {
  editingCredentialId.value = cred.id
  credentialName.value = cred.name || ''
  formMessage.value = '编辑时请重新填写密钥字段后保存'
  formError.value = false
  applyCredentialInitialValues()
}

async function handleSave() {
  if (!selected.value) return
  saving.value = true
  formMessage.value = ''
  formError.value = false
  try {
    const credentialsPayload = buildCredentials()
    if (editingCredentialId.value) {
      await updateBuiltinCredential(selected.value.provider, {
        credential_id: editingCredentialId.value,
        credentials: credentialsPayload,
        name: credentialName.value || undefined,
      })
      formMessage.value = '授权已更新'
    }
    else {
      await addBuiltinCredential(selected.value.provider, {
        credentials: credentialsPayload,
        name: credentialName.value || undefined,
        type: 'api-key',
      })
      formMessage.value = '授权已保存'
    }
    resetCredentialForm()
    await loadCredentials(selected.value.provider)
    await toolStore.fetchTools(true)
    ElMessage.success(formMessage.value)
  }
  catch (e) {
    formError.value = true
    formMessage.value = e.response?.data?.message || e.message || '保存失败'
  }
  finally {
    saving.value = false
  }
}

async function makeDefault(id) {
  if (!selected.value) return
  saving.value = true
  try {
    await setDefaultBuiltinCredential(selected.value.provider, { id })
    await loadCredentials(selected.value.provider)
    ElMessage.success('已设为默认凭证')
  }
  catch (e) {
    ElMessage.error(e.response?.data?.message || e.message || '设置失败')
  }
  finally {
    saving.value = false
  }
}

async function handleDeleteCredential(cred) {
  if (!selected.value) return
  try {
    await ElMessageBox.confirm(`确定删除凭证「${cred.name || cred.id}」？`, '删除凭证', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  }
  catch {
    return
  }
  saving.value = true
  try {
    await deleteBuiltinCredential(selected.value.provider, { credential_id: cred.id })
    if (editingCredentialId.value === cred.id)
      resetCredentialForm()
    await loadCredentials(selected.value.provider)
    await toolStore.fetchTools(true)
    ElMessage.success('凭证已删除')
  }
  catch (e) {
    ElMessage.error(e.response?.data?.message || e.message || '删除失败')
  }
  finally {
    saving.value = false
  }
}

async function handleUninstall() {
  if (!selected.value?.installationId) {
    ElMessage.warning('未找到可卸载的插件安装记录')
    return
  }
  let sessions = []
  try {
    const payload = await fetchStudioSessionsByInstallation({
      installation_id: selected.value.installationId,
      plugin_unique_identifier: selected.value.pluginUniqueIdentifier || undefined,
    })
    sessions = payload?.sessions || []
  }
  catch {
    sessions = []
  }
  const hasChat = sessions.some(item => (item.message_count || 0) > 0 || item.last_message_preview)
  const message = hasChat
    ? '该插件由 AI 生成器创建，卸载将同时删除 Agent 对话与草稿，不可恢复。确定继续？'
    : sessions.length
      ? '卸载将同时删除关联的 AI 工作室会话草稿。确定继续？'
      : `确定卸载插件「${selected.value.label}」？`
  try {
    await ElMessageBox.confirm(message, '卸载插件', {
      type: 'warning',
      confirmButtonText: '确定卸载',
      cancelButtonText: '取消',
    })
  }
  catch {
    return
  }
  uninstalling.value = true
  try {
    await uninstallToolPluginWithSessions({
      plugin_installation_id: selected.value.installationId,
      delete_studio_sessions: true,
      plugin_unique_identifier: selected.value.pluginUniqueIdentifier || undefined,
    })
    selected.value = null
    ElMessage.success('插件已卸载')
    await reload()
  }
  catch (e) {
    ElMessage.error(e.response?.data?.message || e.message || '卸载失败')
  }
  finally {
    uninstalling.value = false
  }
}
</script>

<style scoped>
.tools-auth-panel {
  display: flex;
  height: 100%;
  min-height: 420px;
  flex-direction: column;
  overflow: auto;
  background: #fff;
}
.embedded-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid #eaecf0;
}
.embedded-header h2, .embedded-header p { margin: 0; }
.embedded-header h2 { font-size: 15px; color: #101828; }
.embedded-header p { margin-top: 4px; font-size: 12px; color: #667085; line-height: 1.5; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.ghost {
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #fff;
  padding: 6px 10px;
  cursor: pointer;
}
.studio-link {
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #fff;
  color: #344054;
  font-size: 13px;
  text-decoration: none;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
}
.body {
  display: grid;
  grid-template-columns: 300px 1fr;
  min-height: 280px;
  overflow: hidden;
}
.provider-list {
  overflow: auto;
  border-right: 1px solid #eaecf0;
  max-height: 480px;
}
.provider-card {
  display: flex;
  width: 100%;
  padding: 12px 14px;
  border: 0;
  border-bottom: 1px solid #f2f4f7;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.card-row { display: flex; gap: 10px; align-items: center; width: 100%; }
.tool-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  object-fit: cover;
  flex-shrink: 0;
  background: #f2f4f7;
}
.tool-icon.placeholder {
  display: grid;
  place-items: center;
  color: var(--af-brand-strong);
  font-size: 13px;
  font-weight: 700;
  background: var(--af-brand-soft);
}
.card-text { min-width: 0; }
.card-text strong { display: block; font-size: 13px; color: #101828; }
.card-text span { font-size: 11px; color: #667085; }
.provider-card.active, .provider-card:hover { background: #f8faff; }
.detail { overflow: auto; padding: 16px; max-height: 480px; }
.detail-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}
.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}
.studio-link.primary-link {
  border-color: var(--af-brand-border);
  color: var(--af-brand-strong);
}
.studio-hint {
  margin: 8px 0 12px;
}
.detail h3 { margin: 0 0 4px; font-size: 14px; }
.detail h4 { margin: 16px 0 8px; font-size: 13px; color: #344054; }
.hint { margin: 0 0 8px; font-size: 12px; color: #667085; }
.cred-list ul, .tool-names ul {
  margin: 0;
  padding: 0;
  list-style: none;
}
.cred-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid #f2f4f7;
  font-size: 13px;
}
.tool-names li {
  border-bottom: 1px solid #f2f4f7;
  font-size: 13px;
}
.tool-detail summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 2px;
  color: #101828;
  cursor: pointer;
  list-style: none;
}
.tool-detail summary::-webkit-details-marker { display: none; }
.tool-detail summary:hover { color: var(--af-brand-strong); }
.tool-detail summary:focus-visible {
  border-radius: 6px;
  outline: 2px solid var(--af-brand-border);
  outline-offset: 2px;
}
.tool-detail-chevron {
  color: #98a2b3;
  font-size: 18px;
  line-height: 1;
  transition: transform 0.15s ease;
}
.tool-detail[open] .tool-detail-chevron { transform: rotate(90deg); }
.tool-detail p {
  margin: -2px 24px 10px 2px;
  color: #667085;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
}
.cred-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.badge {
  margin-left: 6px;
  border-radius: 999px;
  background: #eff8ff;
  color: var(--af-brand-strong);
  padding: 1px 6px;
  font-size: 10px;
}
.link {
  border: 0;
  background: transparent;
  color: var(--af-brand-strong);
  cursor: pointer;
  font-size: 12px;
}
.danger-link { color: #b42318; }
.danger {
  border: 1px solid #fda29b;
  border-radius: 8px;
  background: #fef3f2;
  color: #b42318;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
  font-size: 12px;
  color: #344054;
}
.field input {
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
}
.actions { display: flex; gap: 8px; }
.actions .primary {
  border: 0;
  border-radius: 8px;
  background: var(--af-brand);
  color: #fff;
  padding: 8px 12px;
  cursor: pointer;
}
.form-msg { margin-top: 10px; font-size: 12px; color: #027a48; }
.form-msg.error { color: #b42318; }
.state { padding: 24px; color: #667085; font-size: 13px; }
.state.compact { padding: 12px 14px; }
.state.error { color: #b42318; }
</style>
