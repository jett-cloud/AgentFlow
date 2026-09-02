<template>
  <div class="mcp-panel">
    <header class="embedded-header">
      <div>
        <h2>MCP 工具</h2>
        <p>连接远程 MCP Server，把已发现的工具安全加入工作流或 Agent。</p>
      </div>
      <div class="header-actions">
        <button type="button" class="primary" @click="openConnector">添加 MCP</button>
        <button type="button" class="ghost" :disabled="loading" @click="reload">刷新</button>
      </div>
    </header>

    <div v-if="loading" class="state">正在加载 MCP Server…</div>
    <div v-else-if="error" class="state error">{{ error }}</div>
    <div v-else class="body">
      <aside class="provider-list" aria-label="MCP Server 列表">
        <button
          v-for="provider in providers"
          :key="provider.id"
          type="button"
          class="provider-card"
          :class="{ active: selected?.id === provider.id }"
          @click="selectProvider(provider)"
        >
          <span class="provider-icon" :class="`is-${provider.iconMeta.variant}`">
            <img v-if="provider.iconMeta.type === 'url'" :src="provider.iconMeta.value" :alt="`${provider.name} 图标`" crossorigin="anonymous" referrerpolicy="no-referrer">
            <strong v-else-if="provider.iconMeta.type === 'letters'">{{ provider.iconMeta.value }}</strong>
            <svg v-else viewBox="0 0 32 32" aria-hidden="true">
              <path d="M9 10.5 16 6l7 4.5v11L16 26l-7-4.5z" />
              <circle cx="9" cy="10.5" r="2.2" />
              <circle cx="23" cy="10.5" r="2.2" />
              <circle cx="16" cy="26" r="2.2" />
              <path d="m11 12 4 10m6-10-4 10" />
            </svg>
          </span>
          <span class="provider-copy">
            <strong>{{ provider.name }}</strong>
            <span>{{ provider.authed ? '已连接' : '待授权' }} · {{ provider.tools.length }} 个工具</span>
          </span>
          <span class="status-dot" :class="{ connected: provider.authed }" aria-hidden="true"></span>
        </button>
        <p v-if="!providers.length" class="empty-state">还没有 MCP Server。点击“添加 MCP”连接 GitHub 官方服务或自定义服务。</p>
      </aside>

      <section v-if="selected" class="detail">
        <div class="detail-head">
          <div>
            <div class="eyebrow">MCP SERVER</div>
            <h3>{{ selected.name }}</h3>
            <p class="hint">{{ selected.server_identifier || selected.id }}</p>
          </div>
          <div class="detail-actions">
            <button type="button" class="ghost" :disabled="busy" @click="openEdit">编辑</button>
            <button type="button" class="ghost" :disabled="busy" @click="authorize">重新连接</button>
            <button type="button" class="ghost" :disabled="busy" @click="refreshTools">刷新工具</button>
            <button type="button" class="danger" :disabled="busy" @click="removeProvider">删除</button>
          </div>
        </div>
        <div class="meta-grid">
          <div><span>连接状态</span><strong :class="selected.authed ? 'success' : 'warning'">{{ selected.authed ? 'Connected' : '需要授权' }}</strong></div>
          <div><span>工具数量</span><strong>{{ selected.tools.length }}</strong></div>
          <div><span>连接地址</span><strong class="truncate" :title="selected.server_url">{{ selected.server_url || '未提供' }}</strong></div>
          <div><span>更新时间</span><strong>{{ formatTimestamp(selected.updated_at) }}</strong></div>
        </div>
        <div class="tools-section">
          <div class="section-title"><h4>已发现工具</h4><span>{{ selected.tools.length }} tools</span></div>
          <div v-if="selected.tools.length" class="tool-list">
            <details v-for="tool in selected.tools" :key="tool.name || tool.tool_name" class="tool-card">
              <summary><span>{{ tool.label?.zh_Hans || tool.label?.en_US || tool.label || tool.name || tool.tool_name }}</span><code>{{ tool.name || tool.tool_name }}</code></summary>
              <p>{{ tool.description?.zh_Hans || tool.description?.en_US || tool.description || '无描述' }}</p>
              <pre>{{ JSON.stringify(tool.parameters || tool.inputSchema || {}, null, 2) }}</pre>
            </details>
          </div>
          <p v-else class="hint">尚未发现工具。请完成授权后点击“刷新工具”。</p>
        </div>
      </section>
      <section v-else class="state detail-empty">选择一个 MCP Server 查看工具和连接状态</section>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingProvider ? '编辑 MCP' : '添加 MCP'" width="560px" @closed="resetDialog">
      <div class="dialog-body">
        <div v-if="!editingProvider" class="mode-switch" role="tablist" aria-label="MCP 类型">
          <button type="button" :class="{ active: form.mode === 'github' }" @click="useGitHubTemplate">GitHub 官方模板</button>
          <button type="button" :class="{ active: form.mode === 'custom' }" @click="useCustomTemplate">自定义 MCP</button>
        </div>
        <p v-if="form.mode === 'github'" class="security-note">默认启用只读模式，仅请求 repos、issues、pull_requests 工具集。Token 只会提交到后端加密字段，不会保存到浏览器。</p>
        <label class="field"><span>名称</span><input v-model="form.name" type="text" autocomplete="off"></label>
        <label class="field"><span>Server URL</span><input v-model="form.serverUrl" type="url" autocomplete="off"></label>
        <label class="field"><span>唯一标识</span><input v-model="form.serverIdentifier" type="text" pattern="[a-z0-9_-]{1,24}" autocomplete="off"></label>
        <div class="two-col">
          <label class="field"><span>图标</span><input v-model="form.icon" type="text" maxlength="4" autocomplete="off"></label>
          <label class="field"><span>连接超时（秒）</span><input v-model.number="form.timeout" type="number" min="1"></label>
        </div>
        <template v-if="form.mode === 'github'">
          <label class="field"><span>GitHub Token</span><input v-model="form.token" type="password" autocomplete="new-password" placeholder="仅本次提交使用"></label>
          <label class="switch-row"><input v-model="form.readonly" type="checkbox"><span>只读模式（推荐）</span></label>
          <div class="field"><span>Toolsets</span><div class="checks"><label v-for="toolset in githubToolsets" :key="toolset"><input v-model="form.toolsets" type="checkbox" :value="toolset"> {{ toolset }}</label></div></div>
        </template>
        <template v-else>
          <div class="field"><span>认证方式</span><div class="mode-switch small"><button type="button" :class="{ active: form.authMode === 'headers' }" @click="form.authMode = 'headers'">Headers</button><button type="button" :class="{ active: form.authMode === 'oauth' }" @click="form.authMode = 'oauth'">OAuth</button></div></div>
          <div v-if="form.authMode === 'headers'" class="field"><span>Headers</span><div v-for="(header, index) in form.headers" :key="index" class="header-row"><input v-model="header.key" type="text" placeholder="Header 名称" autocomplete="off"><input v-model="header.value" type="password" placeholder="Header 值" autocomplete="new-password"><button type="button" class="icon-button" aria-label="删除 Header" @click="removeHeader(index)">×</button></div><button type="button" class="link-button" @click="addHeader">+ 添加 Header</button></div>
          <div v-else class="two-col"><label class="field"><span>Client ID</span><input v-model="form.clientId" type="text" autocomplete="off"></label><label class="field"><span>Client Secret</span><input v-model="form.clientSecret" type="password" autocomplete="new-password"></label></div>
        </template>
        <label class="field"><span>SSE 读取超时（秒）</span><input v-model.number="form.sseReadTimeout" type="number" min="1"></label>
        <p v-if="formError" class="form-error">{{ formError }}</p>
      </div>
      <template #footer><button type="button" class="ghost" @click="dialogVisible = false">取消</button><button type="button" class="primary" :disabled="busy" @click="saveProvider">{{ busy ? '保存中…' : '保存并连接' }}</button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { authorizeMcpProvider, createMcpProvider, deleteMcpProvider, fetchMcpProvider, fetchMcpProviders, refreshMcpProviderTools, updateMcpProvider } from '../api/difyToolsApi.js'
import { buildMcpProviderPayload, clearMcpFormSecrets, createCustomMcpForm, createGitHubMcpForm, createMcpEditForm, GITHUB_TOOLSETS, validateMcpForm } from '../lib/mcpProviderForm.js'
import { normalizeRemoteMcpProvider } from '../lib/remoteMcpPresentation.js'

const githubToolsets = GITHUB_TOOLSETS
const router = useRouter()
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const formError = ref('')
const providers = ref([])
const selected = ref(null)
const editingProvider = ref(null)
const dialogVisible = ref(false)
const form = reactive(createCustomMcpForm())

function normalizeProviders(payload) {
  const list = Array.isArray(payload) ? payload : (payload?.data || [])
  return list.map(normalizeRemoteMcpProvider).filter(item => item.id)
}

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const next = normalizeProviders(await fetchMcpProviders({ silent: true }))
    providers.value = next
    if (selected.value) selected.value = next.find(item => item.id === selected.value.id) || null
  } catch (e) { error.value = e.message || 'MCP 列表加载失败' } finally { loading.value = false }
}

onMounted(reload)

function openConnector() { router.push('/integrations/mcp/connect') }

async function selectProvider(provider) {
  selected.value = provider
  try { selected.value = normalizeProviders([await fetchMcpProvider(provider.id)])[0] || provider } catch { /* list data remains usable */ }
}

function openEdit() { if (!selected.value) return; editingProvider.value = selected.value; Object.assign(form, createMcpEditForm(selected.value)); formError.value = ''; dialogVisible.value = true }
function useGitHubTemplate() { Object.assign(form, createGitHubMcpForm()) }
function useCustomTemplate() { Object.assign(form, createCustomMcpForm()) }
function resetDialog() { clearMcpFormSecrets(form); editingProvider.value = null; formError.value = '' }
function addHeader() { form.headers.push({ key: '', value: '' }) }
function removeHeader(index) { form.headers.splice(index, 1) }

async function saveProvider() {
  formError.value = validateMcpForm(form)
  if (formError.value) return
  busy.value = true
  try {
    const payload = buildMcpProviderPayload(form, editingProvider.value?.id || '')
    const response = editingProvider.value ? await updateMcpProvider(payload) : await createMcpProvider(payload)
    clearMcpFormSecrets(form)
    dialogVisible.value = false
    ElMessage.success(editingProvider.value ? 'MCP 配置已更新' : 'MCP 已添加')
    await reload()
    const id = response?.id || editingProvider.value?.id
    if (id) {
      const provider = providers.value.find(item => item.id === id)
      if (provider) await selectProvider(provider)
    }
  } catch (e) { formError.value = e.response?.data?.message || e.message || 'MCP 保存失败'; clearMcpFormSecrets(form) } finally { busy.value = false }
}

async function authorize() {
  if (!selected.value) return
  busy.value = true
  try { const result = await authorizeMcpProvider(selected.value.id); if (result?.authorization_url) window.open(result.authorization_url, '_blank', 'noopener,noreferrer'); else ElMessage.success('MCP 已连接'); await reload() } catch (e) { ElMessage.error(e.message || 'MCP 连接失败') } finally { busy.value = false }
}

async function refreshTools() {
  if (!selected.value) return
  busy.value = true
  try { const id = selected.value.id; await refreshMcpProviderTools(id); await reload(); const provider = providers.value.find(item => item.id === id); if (provider) await selectProvider(provider); ElMessage.success('工具列表已刷新') } catch (e) { ElMessage.error(e.message || '工具刷新失败') } finally { busy.value = false }
}

async function removeProvider() {
  if (!selected.value) return
  try { await ElMessageBox.confirm(`确定删除 MCP「${selected.value.name}」？`, '删除 MCP', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }) } catch { return }
  busy.value = true
  try { await deleteMcpProvider(selected.value.id); selected.value = null; await reload(); ElMessage.success('MCP 已删除') } catch (e) { ElMessage.error(e.message || '删除失败') } finally { busy.value = false }
}

function formatTimestamp(value) { if (!value) return '—'; const date = new Date(Number(value) * 1000); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString() }
</script>

<style scoped>
.mcp-panel{display:flex;height:100%;min-height:420px;flex-direction:column;overflow:hidden;background:#fff}.embedded-header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:18px 20px;border-bottom:1px solid #eaecf0}.embedded-header h2,.embedded-header p{margin:0}.embedded-header h2{font-size:16px;color:#101828}.embedded-header p{margin-top:5px;font-size:12px;color:#667085}.header-actions,.detail-actions{display:flex;gap:8px;flex-wrap:wrap}.primary,.ghost,.danger,.link-button,.icon-button{font:inherit;cursor:pointer}.primary{border:0;border-radius:8px;background:var(--af-brand);color:#fff;padding:8px 12px}.ghost{border:1px solid #d0d5dd;border-radius:8px;background:#fff;color:#344054;padding:7px 11px}.ghost:disabled,.primary:disabled,.danger:disabled{opacity:.5;cursor:not-allowed}.danger{border:1px solid #fda29b;border-radius:8px;background:#fef3f2;color:#b42318;padding:7px 11px}.body{display:grid;grid-template-columns:300px minmax(0,1fr);min-height:0;flex:1;overflow:hidden}.provider-list{overflow:auto;border-right:1px solid #eaecf0}.provider-card{display:flex;align-items:center;gap:10px;width:100%;padding:13px 15px;border:0;border-bottom:1px solid #f2f4f7;background:#fff;text-align:left;cursor:pointer}.provider-card:hover,.provider-card.active{background:#f8faff}.provider-icon{display:grid;place-items:center;width:34px;height:34px;border:1px solid #dbe3f2;border-radius:9px;background:#eff4ff;overflow:hidden;flex:none}.provider-icon img{width:100%;height:100%;object-fit:cover}.provider-icon.is-generic{color:#3157b7}.provider-icon svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-linecap:round;stroke-linejoin:round;stroke-width:1.65}.provider-icon svg circle{fill:#fff}.provider-copy{display:flex;min-width:0;flex:1;flex-direction:column;gap:3px}.provider-copy strong{overflow:hidden;color:#101828;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.provider-copy span{color:#667085;font-size:11px}.status-dot{width:8px;height:8px;border-radius:50%;background:#fdb022;flex:none}.status-dot.connected{background:#12b76a}.detail{min-width:0;overflow:auto;padding:22px}.detail-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.eyebrow{color:#667085;font-size:10px;font-weight:700;letter-spacing:.1em}.detail h3{margin:5px 0 4px;color:#101828;font-size:18px}.hint{margin:0;color:#667085;font-size:12px;line-height:1.5}.meta-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:20px 0;padding:14px;border:1px solid #eaecf0;border-radius:10px;background:#fcfcfd}.meta-grid div{display:flex;min-width:0;flex-direction:column;gap:4px}.meta-grid span{color:#98a2b3;font-size:11px}.meta-grid strong{overflow:hidden;color:#344054;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.success{color:#027a48!important}.warning{color:#b54708!important}.section-title{display:flex;align-items:center;justify-content:space-between}.section-title h4{margin:0 0 10px;color:#344054;font-size:14px}.section-title span{color:#98a2b3;font-size:11px}.tool-list{display:flex;flex-direction:column;gap:8px}.tool-card{padding:10px 12px;border:1px solid #eaecf0;border-radius:8px;background:#fff}.tool-card summary{display:flex;align-items:center;justify-content:space-between;gap:10px;cursor:pointer;color:#344054;font-size:13px}.tool-card code{color:#667085;font-size:11px}.tool-card p{margin:8px 0;color:#667085;font-size:12px}.tool-card pre{max-height:180px;overflow:auto;margin:0;padding:8px;border-radius:6px;background:#f8fafc;color:#475467;font-size:11px}.state{padding:28px;color:#667085;font-size:13px}.state.error,.form-error{color:#b42318}.detail-empty{text-align:center}.empty-state{padding:22px 18px;color:#98a2b3;font-size:12px;line-height:1.6}.dialog-body{display:flex;flex-direction:column;gap:12px}.mode-switch{display:flex;gap:4px;padding:3px;border-radius:8px;background:#f2f4f7}.mode-switch button{flex:1;border:0;border-radius:6px;background:transparent;padding:8px;color:#667085;cursor:pointer}.mode-switch button.active{background:#fff;color:var(--af-brand-strong);box-shadow:0 1px 3px #1018281a}.mode-switch.small{padding:2px}.mode-switch.small button{padding:6px}.security-note{margin:0;padding:10px 12px;border:1px solid #b2ddff;border-radius:8px;background:#eff8ff;color:#175cd3;font-size:12px;line-height:1.5}.field{display:flex;flex-direction:column;gap:5px;color:#344054;font-size:12px}.field input{box-sizing:border-box;width:100%;border:1px solid #d0d5dd;border-radius:7px;padding:8px 10px;color:#101828;font-size:13px}.two-col{display:grid;grid-template-columns:1fr 1fr;gap:10px}.switch-row,.checks{display:flex;align-items:center;gap:7px;color:#344054;font-size:12px}.checks{flex-wrap:wrap}.header-row{display:grid;grid-template-columns:1fr 1fr 28px;gap:6px}.header-row input{min-width:0}.icon-button{border:0;background:transparent;color:#667085;font-size:18px}.link-button{align-self:flex-start;border:0;background:transparent;color:var(--af-brand-strong);padding:0;font-size:12px}.form-error{margin:0;font-size:12px}@media(max-width:760px){.body{grid-template-columns:1fr}.provider-list{max-height:220px;border-right:0;border-bottom:1px solid #eaecf0}.embedded-header{flex-direction:column}.detail-head{flex-direction:column}.meta-grid{grid-template-columns:1fr}}
/* Match the compact action controls used by the neighboring integration tabs. */
.header-actions .primary,.header-actions .ghost,.header-actions .danger,.detail-actions .ghost,.detail-actions .danger{padding:6px 10px;border-radius:7px;font-size:13px}
.provider-icon strong{font-size:12px;line-height:1;letter-spacing:-.02em}.provider-icon.is-github{border-color:#24292f;background:#24292f;color:#fff}
</style>
