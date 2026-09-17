<template>
  <!-- Aligns with Dify variable-inspect: left groups + right value + CRUD (Phase 13). -->
  <section class="variable-inspect" aria-label="变量检查">
    <header class="inspect-header">
      <div>
        <h2>变量检查</h2>
        <p>环境只读；会话 / 系统 / 节点草稿变量可编辑、重置、删除</p>
      </div>
      <div class="actions">
        <button type="button" :disabled="loading || mutating" @click="reload">刷新</button>
        <button
          type="button"
          :disabled="loading || mutating || !appId"
          title="清空全部草稿检查变量"
          @click="onClearAll"
        >
          清空全部
        </button>
        <button type="button" aria-label="关闭变量检查" @click="$emit('close')">×</button>
      </div>
    </header>

    <div class="inspect-body">
      <aside class="left">
        <button
          v-for="group in groups"
          :key="group.id"
          type="button"
          class="group-btn"
          :class="{ active: activeGroupId === group.id }"
          @click="activeGroupId = group.id"
        >
          <strong>{{ group.label }}</strong>
          <span>{{ group.count }}</span>
        </button>
      </aside>

      <div class="right">
        <div v-if="activeNodeId" class="group-actions">
          <button type="button" :disabled="mutating" @click="onClearNode(activeNodeId)">
            清空此节点
          </button>
        </div>
        <div v-if="loading" class="state">加载中…</div>
        <div v-else-if="!activeItems.length" class="state">暂无变量。运行工作流或单节点后会写入检查值。</div>
        <ul v-else class="var-list">
          <li v-for="item in activeItems" :key="item.key">
            <button type="button" class="var-row" @click="selectItem(item)">
              <span class="name">
                {{ item.label }}
                <em v-if="item.edited" class="edited">已编辑</em>
              </span>
              <span class="type">{{ item.type || '' }}</span>
            </button>
            <div v-if="selectedKey === item.key" class="detail">
              <template v-if="item.mutable">
                <textarea
                  v-if="item.valueType !== 'boolean'"
                  v-model="editText"
                  class="editor"
                  rows="6"
                  :disabled="mutating"
                />
                <select v-else v-model="editText" class="editor-select" :disabled="mutating">
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
                <p v-if="editError" class="error">{{ editError }}</p>
                <div class="detail-actions">
                  <button type="button" :disabled="mutating" @click="onSave(item)">保存</button>
                  <button
                    v-if="item.edited"
                    type="button"
                    :disabled="mutating"
                    @click="onReset(item)"
                  >
                    重置
                  </button>
                  <button type="button" class="danger" :disabled="mutating" @click="onDelete(item)">
                    删除
                  </button>
                </div>
              </template>
              <pre v-else class="value">{{ formatValue(item.value) }}</pre>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import {
  deleteAllInspectVars,
  deleteInspectVar,
  deleteNodeInspectVars,
  fetchAllInspectVars,
  fetchConversationInspectVars,
  fetchNodeInspectVars,
  fetchSystemInspectVars,
  patchInspectVar,
  resetInspectVar,
} from '@/features/workflow/api/difyWorkflowApi.js'
import {
  groupInspectVarsByNode,
  serializeInspectEditText,
  parseInspectEditValue,
  toInspectPanelItem,
} from '../../model/inspectVars.js'

const props = defineProps({
  appId: { type: String, default: '' },
  environmentVariables: { type: Array, default: () => [] },
  /** Live SSE tracing fallback / titles */
  tracing: { type: Array, default: () => [] },
  /** Bump to force reload after run finish */
  refreshToken: { type: [Number, String], default: 0 },
})

defineEmits(['close'])

const loading = ref(false)
const mutating = ref(false)
const inspectVars = ref([])
const conversationVars = ref([])
const systemVars = ref([])
const nodeVarCache = ref({})
const activeGroupId = ref('env')
const selectedKey = ref('')
const editText = ref('')
const editError = ref('')

const nodeTitleMap = computed(() => {
  const map = {}
  for (const item of props.tracing || []) {
    if (item?.nodeId)
      map[item.nodeId] = item.title || item.nodeId
  }
  return map
})

const nodeGroups = computed(() => {
  const grouped = groupInspectVarsByNode(inspectVars.value)
  for (const item of props.tracing || []) {
    if (item?.nodeId && !grouped.has(item.nodeId))
      grouped.set(item.nodeId, [])
  }
  return [...grouped.entries()].map(([nodeId, vars]) => ({
    id: `node:${nodeId}`,
    nodeId,
    label: nodeTitleMap.value[nodeId] || nodeId,
    count: vars.length || (props.tracing.find(t => t.nodeId === nodeId) ? 1 : 0),
    vars,
  }))
})

const groups = computed(() => ([
  { id: 'env', label: 'ENV', count: props.environmentVariables.length },
  { id: 'conversation', label: 'CONVERSATION', count: conversationVars.value.length },
  { id: 'system', label: 'SYSTEM', count: systemVars.value.length },
  ...nodeGroups.value,
]))

const activeNodeId = computed(() => (
  activeGroupId.value.startsWith('node:') ? activeGroupId.value.slice(5) : ''
))

const activeItems = computed(() => {
  if (activeGroupId.value === 'env') {
    return props.environmentVariables.map((item, index) => toInspectPanelItem({
      ...item,
      value_type: item.value_type || item.type || 'env',
      value: item.value_type === 'secret' ? '****' : item.value,
    }, 'env', index))
  }
  if (activeGroupId.value === 'conversation')
    return normalizeApiItems(conversationVars.value, 'conversation')
  if (activeGroupId.value === 'system')
    return normalizeApiItems(systemVars.value, 'system')
  if (activeGroupId.value.startsWith('node:')) {
    const nodeId = activeGroupId.value.slice(5)
    const cached = nodeVarCache.value[nodeId]
    if (cached?.length)
      return normalizeApiItems(cached, `node-${nodeId}`)
    const fromList = nodeGroups.value.find(g => g.nodeId === nodeId)?.vars || []
    if (fromList.length)
      return normalizeApiItems(fromList, `node-${nodeId}`)
    const live = props.tracing.find(t => t.nodeId === nodeId)
    if (!live)
      return []
    return [
      toInspectPanelItem({ name: 'inputs (live)', type: 'tracing', value: live.inputs }, `trace-${nodeId}`, 0),
      toInspectPanelItem({ name: 'outputs (live)', type: 'tracing', value: live.outputs }, `trace-${nodeId}`, 1),
    ]
  }
  return []
})

const selectedItem = computed(() => activeItems.value.find(i => i.key === selectedKey.value) || null)

function normalizeApiItems(list, prefix) {
  const arr = Array.isArray(list) ? list : (list?.items || [])
  return arr.map((item, index) => toInspectPanelItem(item, prefix, index))
}

function formatValue(value) {
  if (value === undefined || value === null)
    return '—'
  if (typeof value === 'string')
    return value
  try {
    return JSON.stringify(value, null, 2)
  }
  catch {
    return String(value)
  }
}

function selectItem(item) {
  selectedKey.value = item.key
  editError.value = ''
  editText.value = serializeInspectEditText(item.rawValue, item.valueType)
}

async function reload() {
  if (!props.appId)
    return
  loading.value = true
  try {
    const [all, conversation, system] = await Promise.all([
      fetchAllInspectVars(props.appId).catch(() => []),
      fetchConversationInspectVars(props.appId).catch(() => ({ items: [] })),
      fetchSystemInspectVars(props.appId).catch(() => ({ items: [] })),
    ])
    inspectVars.value = Array.isArray(all) ? all : []
    conversationVars.value = conversation.items || conversation.data || (Array.isArray(conversation) ? conversation : [])
    systemVars.value = system.items || system.data || (Array.isArray(system) ? system : [])
    nodeVarCache.value = {}
    if (activeNodeId.value)
      await ensureNodeVars(activeNodeId.value, true)
  }
  finally {
    loading.value = false
  }
}

async function ensureNodeVars(nodeId, force = false) {
  if (!props.appId || !nodeId)
    return
  if (!force && nodeVarCache.value[nodeId])
    return
  try {
    const items = await fetchNodeInspectVars(props.appId, nodeId)
    nodeVarCache.value = {
      ...nodeVarCache.value,
      [nodeId]: Array.isArray(items) ? items : (items.items || []),
    }
  }
  catch {
    nodeVarCache.value = { ...nodeVarCache.value, [nodeId]: [] }
  }
}

async function withMutation(fn) {
  if (!props.appId || mutating.value)
    return
  mutating.value = true
  editError.value = ''
  try {
    await fn()
    await reload()
  }
  catch (err) {
    editError.value = err?.response?.data?.message || err?.message || '操作失败'
  }
  finally {
    mutating.value = false
  }
}

async function onSave(item) {
  const parsed = parseInspectEditValue(editText.value, item.valueType)
  if (!parsed.ok) {
    editError.value = parsed.error
    return
  }
  await withMutation(async () => {
    await patchInspectVar(props.appId, item.id, { value: parsed.value })
  })
}

async function onReset(item) {
  await withMutation(async () => {
    await resetInspectVar(props.appId, item.id)
  })
}

async function onDelete(item) {
  await withMutation(async () => {
    await deleteInspectVar(props.appId, item.id)
    selectedKey.value = ''
  })
}

async function onClearAll() {
  await withMutation(async () => {
    await deleteAllInspectVars(props.appId)
    selectedKey.value = ''
  })
}

async function onClearNode(nodeId) {
  await withMutation(async () => {
    await deleteNodeInspectVars(props.appId, nodeId)
    selectedKey.value = ''
  })
}

watch(activeGroupId, (id) => {
  selectedKey.value = ''
  editText.value = ''
  editError.value = ''
  if (id.startsWith('node:'))
    ensureNodeVars(id.slice(5))
})

watch(selectedItem, (item) => {
  if (!item)
    return
  editError.value = ''
  editText.value = serializeInspectEditText(item.rawValue, item.valueType)
})

watch(
  () => [props.appId, props.refreshToken],
  () => {
    nodeVarCache.value = {}
    reload()
  },
  { immediate: true },
)
</script>

<style scoped>
.variable-inspect {
  position: absolute;
  left: 16px;
  right: 16px;
  bottom: 72px;
  z-index: 46;
  display: flex;
  max-height: min(360px, calc(100% - 140px));
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #eaecf0;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 8px 24px rgb(16 24 40 / 10%);
}
.inspect-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid #f2f4f7;
}
.inspect-header h2,
.inspect-header p { margin: 0; }
.inspect-header h2 { font-size: 14px; color: #101828; }
.inspect-header p { margin-top: 2px; font-size: 11px; color: #667085; }
.actions { display: flex; gap: 6px; }
.actions button,
.group-actions button,
.detail-actions button {
  padding: 5px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #344054;
  cursor: pointer;
}
.actions button:hover,
.group-actions button:hover,
.detail-actions button:hover { background: #f2f4f7; }
.actions button:disabled,
.group-actions button:disabled,
.detail-actions button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.inspect-body {
  display: grid;
  grid-template-columns: 180px 1fr;
  min-height: 0;
  flex: 1;
}
.left {
  overflow: auto;
  border-right: 1px solid #f2f4f7;
  padding: 8px;
}
.group-btn {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #344054;
  cursor: pointer;
  text-align: left;
}
.group-btn.active { background: #f5f8ff; color: #0033ff; }
.group-btn strong { font-size: 12px; }
.group-btn span { color: #98a2b3; font-size: 11px; }
.right {
  overflow: auto;
  padding: 8px 12px;
}
.group-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 4px;
}
.state {
  padding: 24px 12px;
  color: #98a2b3;
  font-size: 12px;
  text-align: center;
}
.var-list { list-style: none; margin: 0; padding: 0; }
.var-row {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  padding: 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
}
.var-row:hover { background: #f9fafb; }
.name { font-size: 12px; font-weight: 600; color: #101828; }
.edited {
  margin-left: 6px;
  font-style: normal;
  font-size: 10px;
  font-weight: 600;
  color: #6938ef;
}
.type { font-size: 10px; color: #98a2b3; }
.detail { margin: 0 0 8px; }
.editor,
.editor-select {
  display: block;
  width: 100%;
  box-sizing: border-box;
  padding: 8px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #f9fafb;
  font: 11px/1.5 ui-monospace, Consolas, monospace;
  resize: vertical;
}
.editor-select { font-size: 12px; }
.error {
  margin: 6px 0 0;
  color: #d92d20;
  font-size: 11px;
}
.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.detail-actions .danger { color: #d92d20; }
.value {
  margin: 0;
  max-height: 160px;
  overflow: auto;
  padding: 8px;
  border-radius: 8px;
  background: #f2f4f7;
  font: 11px/1.5 ui-monospace, Consolas, monospace;
  white-space: pre-wrap;
}
@media (max-width: 720px) {
  .inspect-body { grid-template-columns: 1fr; }
  .left { border-right: 0; border-bottom: 1px solid #f2f4f7; max-height: 120px; }
}
</style>
