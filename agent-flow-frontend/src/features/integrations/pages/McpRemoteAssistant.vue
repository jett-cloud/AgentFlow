<template>
  <main class="remote-mcp-page">
    <header class="page-header">
      <button type="button" class="back-button" @click="router.push(mcpToolsLocation())">← 返回 MCP 工具</button>
      <div class="title-row">
        <div>
          <h1>远程 MCP 连接</h1>
          <p>填写远程服务地址和认证信息，完成握手后获取可用工具。</p>
        </div>
      </div>
    </header>

    <div class="workspace">
      <section class="assistant-card">
        <div class="connection-form-body">
          <div class="card-heading">
            <div>
              <h2>连接信息</h2>
              <p>URL 必须使用 HTTPS，连接成功后才会保存。</p>
            </div>
          </div>

          <label class="field">
            <span>远程 MCP Server URL</span>
            <input v-model.trim="form.serverUrl" type="url" placeholder="https://example.com/mcp" autocomplete="url">
          </label>
          <label class="field">
            <span>名称</span>
            <input v-model.trim="form.name" type="text" autocomplete="off" placeholder="Remote MCP">
          </label>
          <label class="field">
            <span>唯一标识</span>
            <input v-model.trim="form.serverIdentifier" type="text" pattern="[a-z0-9_-]{1,24}" autocomplete="off" placeholder="remote_mcp">
          </label>
          <label class="field">
            <span>认证方式</span>
            <select v-model="form.authMode">
              <option value="none">无需认证</option>
              <option value="bearer_token">Bearer Token</option>
              <option value="custom_headers">自定义 Headers</option>
              <option value="oauth">OAuth 2.0（自动发现）</option>
              <option value="client_credentials">Client Credentials</option>
            </select>
          </label>
          <label v-if="form.authMode === 'bearer_token'" class="field">
            <span>Bearer Token</span>
            <input v-model="form.token" type="password" autocomplete="new-password" placeholder="仅本次提交使用">
          </label>
          <p v-if="form.authMode === 'oauth'" class="security-note">无需填写 Client ID 或密钥，连接后将自动打开服务商授权页面。</p>
          <template v-if="form.authMode === 'client_credentials'">
            <label class="field"><span>Client ID</span><input v-model.trim="form.clientId" type="text" autocomplete="off"></label>
            <label class="field"><span>Client Secret</span><input v-model="form.clientSecret" type="password" autocomplete="new-password"></label>
          </template>
          <div v-if="form.authMode === 'custom_headers'" class="field">
            <span>自定义 Headers</span>
            <div v-for="(header, index) in form.headers" :key="index" class="header-row">
              <input v-model.trim="header.key" type="text" placeholder="Header 名称" autocomplete="off">
              <input v-model="header.value" type="password" placeholder="Header 值" autocomplete="new-password">
              <button type="button" class="icon-button" aria-label="删除 Header" @click="removeHeader(index)">×</button>
            </div>
            <button type="button" class="link-button" @click="addHeader">+ 添加 Header</button>
          </div>
          <div class="two-col">
            <label class="field"><span>连接超时（秒）</span><input v-model.number="form.timeout" type="number" min="1" max="120"></label>
            <label class="field"><span>SSE 读取超时（秒）</span><input v-model.number="form.sseReadTimeout" type="number" min="1" max="900"></label>
          </div>
          <p class="security-note">凭据只会提交给后端加密保存，不会写入页面历史或普通日志。</p>
        </div>
        <footer class="connection-actions">
          <p v-if="formError" class="form-error">{{ formError }}</p>
          <div class="action-buttons">
            <button type="button" class="secondary-button" :disabled="connecting" @click="resetForm">重置</button>
            <button type="button" class="primary-button" :disabled="connecting" @click="connect">
              {{ connecting ? '连接并发现工具中…' : '确认并连接' }}
            </button>
          </div>
        </footer>
      </section>

      <section class="providers-card">
        <div class="card-heading compact">
          <div>
            <span class="eyebrow">REMOTE MCP PROVIDERS</span>
            <h2>已连接的远程服务</h2>
          </div>
          <button type="button" class="icon-button refresh" :disabled="loading" aria-label="刷新列表" @click="reload">↻</button>
        </div>
        <div class="providers-workspace">
          <div class="provider-rail">
            <div v-if="loading" class="state">正在加载远程 MCP…</div>
            <div v-else-if="error" class="state error">{{ error }}</div>
            <div v-else-if="!providers.length" class="state empty">还没有远程 MCP。输入 URL 后开始连接。</div>
            <div v-else class="provider-list">
              <button v-for="provider in providers" :key="provider.id" type="button" class="provider-row" :class="{ active: selectedProvider?.id === provider.id }" @click="selectProvider(provider)">
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
                <span class="provider-copy"><strong>{{ provider.name }}</strong><small>{{ provider.authed ? '已连接' : '待授权' }} · {{ provider.tools.length }} 个工具</small></span>
                <span class="status-dot" :class="{ connected: provider.authed }"></span>
              </button>
            </div>
          </div>

          <section v-if="selectedProvider" class="provider-detail">
          <div class="detail-toolbar">
            <div class="detail-pills">
              <span class="status-pill" :class="{ connected: selectedProvider.authed }">{{ selectedProvider.authed ? '已连接' : '需要授权' }}</span>
              <span class="meta-pill">HTTP / SSE</span>
              <span class="meta-pill">{{ selectedProvider.tools.length }} tools</span>
            </div>
            <div class="detail-actions">
              <button v-if="!selectedProvider.authed" type="button" class="secondary-button small" :disabled="busy" @click="authorize">完成授权</button>
              <button type="button" class="secondary-button small" :disabled="busy" @click="refreshTools">刷新工具</button>
              <button type="button" class="danger-button small" :disabled="busy" @click="removeProvider">删除</button>
            </div>
          </div>

          <div class="server-meta">
            <div class="server-meta-row">
              <span>SERVER URL</span>
              <strong :title="selectedProvider.server_url">{{ selectedProvider.server_url || '已隐藏' }}</strong>
            </div>
            <div class="server-meta-row compact">
              <span>IDENTIFIER</span><strong>{{ selectedProvider.server_identifier }}</strong>
              <span>LAST SYNC</span><strong>{{ formatTimestamp(selectedProvider.updated_at) }}</strong>
            </div>
          </div>

          <div class="tools-heading">
            <div>
              <h3>远程工具 <span>{{ selectedProvider.tools.length }}</span></h3>
              <p>工具只注册到 Tool Catalog，需要在 Agent 编排中显式启用。</p>
            </div>
            <label class="tool-search">
              <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="m12.5 12.5 4 4" /></svg>
              <input v-model="toolQuery" type="search" placeholder="搜索工具" aria-label="搜索远程工具">
            </label>
          </div>

          <div v-if="filteredTools.length" class="tool-list">
            <details v-for="tool in filteredTools" :key="toolName(tool)" class="tool-card">
              <summary>
                <span class="tool-title">
                  <strong>{{ toolLabel(tool) }}</strong>
                  <code v-if="toolLabel(tool) !== toolName(tool)">{{ toolName(tool) }}</code>
                </span>
                <span class="tool-chevron" aria-hidden="true"></span>
              </summary>
              <p>{{ toolDescription(tool) }}</p>
              <pre>{{ JSON.stringify(tool.parameters || tool.inputSchema || {}, null, 2) }}</pre>
            </details>
          </div>
          <p v-else-if="selectedProvider.tools.length" class="muted empty-tools">没有匹配“{{ toolQuery }}”的工具。</p>
          <p v-else class="muted empty-tools">尚未发现工具。完成授权后点击刷新工具。</p>
          </section>
        </div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { authorizeMcpProvider, createMcpProvider, deleteMcpProvider, fetchMcpProvider, fetchMcpProviders, refreshMcpProviderTools } from '../api/difyToolsApi.js'
import { authorizeRemoteMcp, buildRemoteMcpPayload, openRemoteMcpOAuthWindow, validateRemoteMcpForm } from '../lib/remoteMcpConnection.js'
import { filterRemoteMcpTools, mcpToolsLocation, normalizeRemoteMcpProvider } from '../lib/remoteMcpPresentation.js'

const router = useRouter()
const providers = ref([])
const selectedProvider = ref(null)
const loading = ref(false)
const connecting = ref(false)
const busy = ref(false)
const error = ref('')
const formError = ref('')
const toolQuery = ref('')
const form = reactive({ serverUrl: '', name: '', serverIdentifier: '', authMode: 'none', token: '', clientId: '', clientSecret: '', headers: [{ key: '', value: '' }], timeout: 30, sseReadTimeout: 300 })

function normalizeList(payload) { const list = Array.isArray(payload) ? payload : (payload?.data || []); return list.map(normalizeRemoteMcpProvider).filter(item => item.id) }
function formatTimestamp(timestamp) { if (!timestamp) return '暂无记录'; const value = Number(timestamp) * (Number(timestamp) < 1e12 ? 1000 : 1); const date = new Date(value); return Number.isNaN(date.getTime()) ? '暂无记录' : date.toLocaleString('zh-CN') }
function toolName(tool) { return tool.name || tool.tool_name || '未命名工具' }
function toolLabel(tool) { return tool.label?.zh_Hans || tool.label?.en_US || toolName(tool) }
function toolDescription(tool) { return tool.description?.zh_Hans || tool.description?.en_US || tool.description || '无描述' }
const filteredTools = computed(() => filterRemoteMcpTools(selectedProvider.value?.tools || [], toolQuery.value))

async function reload() {
  loading.value = true; error.value = ''
  try { providers.value = normalizeList(await fetchMcpProviders({ silent: true })); if (selectedProvider.value) selectedProvider.value = providers.value.find(item => item.id === selectedProvider.value.id) || null } catch (e) { error.value = e.message || '远程 MCP 列表加载失败' } finally { loading.value = false }
}
async function selectProvider(provider) { toolQuery.value = ''; selectedProvider.value = provider; try { selectedProvider.value = normalizeRemoteMcpProvider(await fetchMcpProvider(provider.id)) } catch { /* list data remains useful */ } }
async function connect() {
  formError.value = validateRemoteMcpForm(form)
  if (formError.value)
    return

  const authMode = form.authMode
  const oauthPopup = authMode === 'oauth' ? openRemoteMcpOAuthWindow(window.open.bind(window)) : null
  connecting.value = true
  try {
    const created = normalizeRemoteMcpProvider(await createMcpProvider(buildRemoteMcpPayload(form)))
    providers.value = normalizeList(await fetchMcpProviders({ silent: true }))
    const id = created.id || providers.value.find(item => item.server_identifier === form.serverIdentifier)?.id
    const provider = providers.value.find(item => item.id === id)
    if (provider)
      await selectProvider(provider)
    const connectedProvider = selectedProvider.value?.id === id ? selectedProvider.value : (provider || created)
    clearSecrets()

    if (authMode === 'oauth' && !connectedProvider.authed && connectedProvider.id) {
      const outcome = await authorizeRemoteMcp({
        providerId: connectedProvider.id,
        authorizeProvider: authorizeMcpProvider,
        popup: oauthPopup,
        openWindow: window.open.bind(window),
      })
      if (outcome.opened)
        ElMessage.success('已打开 OAuth 授权页面，完成授权后返回此处刷新工具')
      else if (outcome.authorizationUrl)
        ElMessage.warning('浏览器拦截了授权窗口，请点击“完成授权”重试')
      else
        ElMessage.success('授权请求已完成')
      return
    }

    if (oauthPopup && !oauthPopup.closed)
      oauthPopup.close()
    if (connectedProvider.authed)
      ElMessage.success('远程 MCP 已完成握手，工具列表已获取')
    else
      ElMessage.warning('远程 MCP 已验证，完成授权后即可获取工具')
  }
  catch (e) {
    if (oauthPopup && !oauthPopup.closed)
      oauthPopup.close()
    formError.value = e.response?.data?.message || e.message || '远程 MCP 连接失败'
    clearSecrets()
  }
  finally {
    connecting.value = false
  }
}
async function authorize() {
  if (!selectedProvider.value)
    return
  const oauthPopup = openRemoteMcpOAuthWindow(window.open.bind(window))
  busy.value = true
  try {
    const outcome = await authorizeRemoteMcp({
      providerId: selectedProvider.value.id,
      authorizeProvider: authorizeMcpProvider,
      popup: oauthPopup,
      openWindow: window.open.bind(window),
    })
    if (outcome.opened)
      ElMessage.success('已打开 OAuth 授权页面')
    else if (outcome.authorizationUrl)
      ElMessage.warning('浏览器拦截了授权窗口，请再次点击“完成授权”')
    else
      ElMessage.success('授权请求已完成')
    await reload()
  }
  catch (e) {
    ElMessage.error(e.message || '远程 MCP 授权失败')
  }
  finally {
    busy.value = false
  }
}
function clearSecrets() { form.token = ''; form.clientSecret = ''; form.headers = form.headers.map(item => ({ ...item, value: '' })) }
function resetForm() { Object.assign(form, { serverUrl: '', name: '', serverIdentifier: '', authMode: 'none', token: '', clientId: '', clientSecret: '', headers: [{ key: '', value: '' }], timeout: 30, sseReadTimeout: 300 }); formError.value = '' }
function addHeader() { form.headers.push({ key: '', value: '' }) }
function removeHeader(index) { form.headers.splice(index, 1); if (!form.headers.length) addHeader() }
async function refreshTools() { if (!selectedProvider.value) return; busy.value = true; try { await refreshMcpProviderTools(selectedProvider.value.id); await reload(); const provider = providers.value.find(item => item.id === selectedProvider.value.id); if (provider) await selectProvider(provider); ElMessage.success('远程工具列表已刷新') } catch (e) { ElMessage.error(e.message || '工具刷新失败') } finally { busy.value = false } }
async function removeProvider() { if (!selectedProvider.value) return; try { await ElMessageBox.confirm(`确定删除远程 MCP「${selectedProvider.value.name}」？`, '删除远程 MCP', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }) } catch { return } busy.value = true; try { await deleteMcpProvider(selectedProvider.value.id); selectedProvider.value = null; await reload(); ElMessage.success('远程 MCP 已删除') } catch (e) { ElMessage.error(e.message || '删除失败') } finally { busy.value = false } }
onMounted(reload)
</script>

<style scoped>
.remote-mcp-page{box-sizing:border-box;min-height:100%;padding:28px 32px;background:#f8fafc;color:#101828}.page-header{max-width:1240px;margin:0 auto 22px}.back-button{border:0;background:transparent;color:#667085;cursor:pointer;font-size:13px}.title-row{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-top:20px}.title-row h1{margin:0;font-size:28px;letter-spacing:-.02em}.title-row p{margin:8px 0 0;color:#667085;font-size:14px}.workspace{display:grid;grid-template-columns:minmax(360px,460px) minmax(0,1fr);gap:20px;max-width:1240px;margin:0 auto}.assistant-card,.providers-card{border:1px solid #e4e7ec;border-radius:16px;background:#fff;box-shadow:0 8px 24px #1018280a}.assistant-card{display:flex;min-height:480px;max-height:calc(100vh - 238px);overflow:hidden;flex-direction:column}.connection-form-body{min-height:0;overflow:auto;padding:22px 22px 12px}.connection-actions{flex:none;border-top:1px solid #eaecf0;background:#fff;padding:14px 22px;box-shadow:0 -8px 18px #1018280a}.action-buttons{display:grid;grid-template-columns:112px 1fr;gap:10px}.providers-card{box-sizing:border-box;display:flex;min-width:0;max-height:calc(100vh - 238px);overflow:hidden;flex-direction:column;padding:22px}.card-heading{display:flex;align-items:flex-start;gap:12px;margin-bottom:20px}.card-heading.compact{align-items:center;margin-bottom:14px}.card-heading h2{margin:0;color:#101828;font-size:17px}.card-heading p{margin:5px 0 0;color:#667085;font-size:12px}.field{display:flex;flex-direction:column;gap:6px;margin-top:13px;color:#344054;font-size:12px;font-weight:600}.field input,.field textarea,.field select{box-sizing:border-box;width:100%;border:1px solid #d0d5dd;border-radius:8px;background:#fff;padding:9px 10px;color:#101828;font:inherit;font-size:13px;font-weight:400}.field textarea{resize:vertical}.secondary-button,.primary-button,.danger-button{border-radius:8px;padding:9px 12px;font:inherit;font-size:13px;font-weight:600;cursor:pointer}.secondary-button{border:1px solid #cfd8ea;background:#f8faff;color:#3157b7}.primary-button{border:0;background:#3157b7;color:#fff}.danger-button{border:1px solid #fda29b;background:#fef3f2;color:#b42318}.secondary-button:disabled,.primary-button:disabled,.danger-button:disabled{opacity:.5;cursor:not-allowed}.secondary-button.small{padding:7px 10px;font-size:12px}.detail-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.detail-heading h3{margin:4px 0 0;color:#175cd3;font-size:15px}.eyebrow{color:#98a2b3;font-size:10px;font-weight:700;letter-spacing:.09em}.muted{margin:7px 0;color:#667085;font-size:12px;line-height:1.5}.form-error{margin:0 0 10px;color:#b42318;font-size:12px}.security-note{margin:12px 0 0;color:#667085;font-size:11px;line-height:1.5}.two-col{display:grid;grid-template-columns:1fr 1fr;gap:10px}.header-row{display:grid;grid-template-columns:1fr 1fr 28px;gap:6px;margin-top:6px}.icon-button,.link-button{border:0;background:transparent;color:#667085;cursor:pointer}.link-button{align-self:flex-start;margin-top:7px;color:#3157b7;font-size:12px}.refresh{font-size:20px}.state{padding:28px 4px;color:#667085;font-size:13px}.state.empty{text-align:center}.state.error{color:#b42318}.provider-list{display:flex;max-height:160px;flex:none;overflow:auto;flex-direction:column;border-top:1px solid #eaecf0}.provider-row{display:flex;align-items:center;gap:10px;border:0;border-bottom:1px solid #f2f4f7;background:#fff;padding:12px 4px;text-align:left;cursor:pointer}.provider-row.active{background:#f8faff}.provider-icon{display:grid;place-items:center;width:34px;height:34px;border-radius:9px;background:#eef4ff;font-size:18px}.provider-copy{display:flex;min-width:0;flex:1;flex-direction:column;gap:3px}.provider-copy strong{overflow:hidden;color:#101828;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.provider-copy small{color:#667085;font-size:11px}.status-dot{width:8px;height:8px;border-radius:50%;background:#fdb022}.status-dot.connected{background:#12b76a}.provider-detail{min-height:0;flex:1;overflow:auto;margin-top:18px;padding-top:18px;padding-right:4px;border-top:1px solid #eaecf0}.detail-heading p{margin:4px 0;color:#667085;font-size:11px}.detail-actions{display:flex;gap:7px}.meta-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:16px 0;padding:12px;border:1px solid #eaecf0;border-radius:10px;background:#fcfcfd}.meta-grid div{display:flex;min-width:0;flex-direction:column;gap:4px}.meta-grid span{color:#98a2b3;font-size:11px}.meta-grid strong{overflow:hidden;color:#344054;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.meta-grid .wide{grid-column:1/-1}.success{color:#027a48!important}.warning{color:#b54708!important}.provider-detail h4{margin:0 0 9px;color:#344054;font-size:13px}.tool-list{display:flex;flex-direction:column;gap:7px}.tool-card{padding:9px 10px;border:1px solid #eaecf0;border-radius:8px}.tool-card summary{display:flex;align-items:center;justify-content:space-between;gap:10px;cursor:pointer;color:#344054;font-size:12px}.tool-card code{color:#667085;font-size:10px}.tool-card p{margin:7px 0;color:#667085;font-size:11px}.tool-card pre{max-height:160px;overflow:auto;margin:0;padding:8px;border-radius:6px;background:#f8fafc;color:#475467;font-size:10px}@media(max-width:900px){.workspace{grid-template-columns:1fr}.title-row{align-items:flex-start;flex-direction:column}.assistant-card{max-height:calc(100vh - 220px)}}@media(max-width:520px){.remote-mcp-page{padding:20px 14px}.two-col{grid-template-columns:1fr}.title-row h1{font-size:23px}.action-buttons{grid-template-columns:96px 1fr}}
.providers-card{padding:20px 22px 22px}.card-heading.compact{justify-content:space-between;padding:0 2px}.provider-list{gap:8px;padding:4px 0 12px;border-top:0}.provider-row{min-height:62px;border:1px solid transparent;border-radius:12px;padding:9px 11px;transition:border-color .16s ease,background .16s ease,box-shadow .16s ease}.provider-row:hover{border-color:#dbe3f2;background:#f8faff}.provider-row.active{border-color:#cbd8f4;background:linear-gradient(135deg,#f5f8ff 0%,#eef4ff 100%);box-shadow:0 4px 12px #3157b70d}.provider-icon{box-sizing:border-box;width:38px;height:38px;overflow:hidden;border:1px solid #dbe3f2;border-radius:11px;background:#f1f5ff;color:#3157b7}.provider-icon img{width:100%;height:100%;object-fit:cover}.provider-icon.is-generic{background:linear-gradient(145deg,#f5f7ff,#e9efff);color:#3157b7}.provider-icon svg{width:27px;height:27px;fill:none;stroke:currentColor;stroke-linecap:round;stroke-linejoin:round;stroke-width:1.65}.provider-icon svg circle{fill:#fff}.provider-copy{gap:4px}.provider-copy strong{font-size:13px;font-weight:650}.provider-copy small{font-size:11px}.status-dot{width:7px;height:7px;box-shadow:0 0 0 4px #fef0c7}.status-dot.connected{box-shadow:0 0 0 4px #d1fadf}.provider-detail{margin-top:4px;padding-top:16px;padding-right:6px}.detail-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px}.detail-pills,.detail-actions{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.status-pill,.meta-pill{display:inline-flex;align-items:center;height:25px;box-sizing:border-box;border:1px solid #fedf89;border-radius:999px;background:#fffaeb;padding:0 9px;color:#b54708;font-size:10px;font-weight:700}.status-pill.connected{border-color:#abefc6;background:#ecfdf3;color:#067647}.status-pill::before{width:5px;height:5px;margin-right:6px;border-radius:50%;background:currentColor;content:""}.meta-pill{border-color:#e4e7ec;background:#f9fafb;color:#475467;font-weight:600}.danger-button.small{padding:7px 10px;font-size:12px}.server-meta{display:flex;flex-direction:column;gap:10px;margin:14px 0 20px;padding:13px 14px;border:1px solid #e4e7ec;border-radius:12px;background:linear-gradient(180deg,#fcfcfd,#f9fafb)}.server-meta-row{display:grid;min-width:0;grid-template-columns:90px minmax(0,1fr);align-items:center;gap:10px}.server-meta-row.compact{grid-template-columns:90px minmax(80px,1fr) 72px minmax(130px,1fr);padding-top:10px;border-top:1px solid #eaecf0}.server-meta-row span{color:#98a2b3;font-size:9px;font-weight:750;letter-spacing:.08em}.server-meta-row strong{overflow:hidden;color:#344054;font-size:11px;font-weight:600;text-overflow:ellipsis;white-space:nowrap}.tools-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:12px}.tools-heading h3{display:flex;align-items:center;gap:7px;margin:0;color:#101828;font-size:14px}.tools-heading h3 span{display:grid;place-items:center;min-width:21px;height:21px;border-radius:6px;background:#eef4ff;color:#3157b7;font-size:10px}.tools-heading p{margin:4px 0 0;color:#667085;font-size:11px}.tool-search{display:flex;width:175px;flex:none;align-items:center;gap:7px;border:1px solid #d0d5dd;border-radius:9px;background:#fff;padding:7px 9px;transition:border-color .15s ease,box-shadow .15s ease}.tool-search:focus-within{border-color:#8098d9;box-shadow:0 0 0 3px #eef4ff}.tool-search svg{width:15px;height:15px;fill:none;stroke:#98a2b3;stroke-linecap:round;stroke-width:1.5}.tool-search input{min-width:0;width:100%;border:0;outline:0;background:transparent;color:#344054;font:inherit;font-size:11px}.tool-search input::placeholder{color:#98a2b3}.tool-list{gap:8px}.tool-card{overflow:hidden;padding:0;border-color:#e4e7ec;border-radius:10px;background:#fff;transition:border-color .15s ease,box-shadow .15s ease}.tool-card:hover{border-color:#cbd5e1;box-shadow:0 3px 10px #1018280a}.tool-card[open]{border-color:#cbd8f4;box-shadow:0 5px 14px #3157b70d}.tool-card summary{min-height:42px;padding:9px 12px;list-style:none}.tool-card summary::-webkit-details-marker{display:none}.tool-title{display:flex;min-width:0;flex-direction:column;gap:3px}.tool-title strong{overflow:hidden;color:#344054;font-size:12px;font-weight:650;text-overflow:ellipsis;white-space:nowrap}.tool-title code{overflow:hidden;color:#7f8a9d;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:9px;text-overflow:ellipsis;white-space:nowrap}.tool-chevron{width:7px;height:7px;flex:none;border-right:1.5px solid #98a2b3;border-bottom:1.5px solid #98a2b3;transform:rotate(45deg) translate(-2px,2px);transition:transform .16s ease}.tool-card[open] .tool-chevron{transform:rotate(225deg) translate(-2px,2px)}.tool-card p{margin:0;padding:0 12px 10px;color:#667085;font-size:11px;line-height:1.55}.tool-card pre{max-height:210px;margin:0 10px 10px;padding:10px;border:1px solid #eaecf0;background:#f8fafc;color:#475467;font-size:10px;line-height:1.5}.empty-tools{padding:24px 10px;text-align:center}@media(max-width:1100px){.detail-toolbar,.tools-heading{align-items:flex-start;flex-direction:column}.tool-search{box-sizing:border-box;width:100%}.server-meta-row.compact{grid-template-columns:76px minmax(0,1fr)}.server-meta-row.compact span:nth-of-type(2){margin-top:4px}.detail-actions{width:100%}}@media(max-width:520px){.server-meta-row,.server-meta-row.compact{grid-template-columns:1fr}.providers-card{padding:18px 16px}.detail-actions{display:grid;grid-template-columns:1fr 1fr}.detail-actions .danger-button{grid-column:1/-1}}
.provider-icon strong{font-size:11px;line-height:1}.provider-icon.is-github,.provider-icon.is-initials{border-color:#24292f;background:#24292f;color:#fff}
.providers-workspace{display:grid;min-height:0;flex:1;grid-template-columns:minmax(190px,220px) minmax(0,1fr);gap:18px;overflow:hidden}.provider-rail{display:flex;min-width:0;min-height:0;overflow:hidden;flex-direction:column;padding-right:14px;border-right:1px solid #eaecf0}.providers-workspace .provider-list{min-height:0;max-height:none;flex:1;overflow:auto;padding-right:4px}.providers-workspace .provider-detail{min-width:0;min-height:0;overflow:auto;margin-top:0;padding-top:0;padding-right:6px;border-top:0}.providers-workspace .server-meta-row.compact{grid-template-columns:76px minmax(0,1fr)}@media(max-width:1100px){.providers-workspace{grid-template-columns:1fr;grid-template-rows:minmax(120px,220px) minmax(0,1fr);gap:14px}.provider-rail{padding-right:0;padding-bottom:12px;border-right:0;border-bottom:1px solid #eaecf0}}
</style>
