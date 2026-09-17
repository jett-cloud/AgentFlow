<template>
  <PanelSection label="工具（Soul Tools）">
    <p class="hint">配置 Agent 可自主调用的 Dify 工具，写入 Composer Soul，不是画布上的 tool 节点。知识库请在下方「知识库」添加，不要在这里搜索。</p>
    <el-select
      v-if="!readOnly"
      :model-value="''"
      filterable
      default-first-option
      :filter-method="onFilter"
      class="w-full"
      popper-class="agent-tool-select-popper"
      placeholder="搜索并添加工具…"
      :disabled="toolStore.loading"
      @change="onAddTool"
      @visible-change="onVisibleChange"
    >
      <el-option-group
        v-for="group in filteredGroups"
        :key="group.type"
        :label="group.label"
      >
        <el-option
          v-for="tool in group.tools"
          :key="toolKey(tool)"
          :label="toolSearchLabel(tool)"
          :value="toolKey(tool)"
          :disabled="isSelected(tool)"
        >
          <div class="tool-option">
            <span class="tool-icon" :style="iconStyle(tool)">
              <img
                v-if="iconMeta(tool)?.type === 'url'"
                :src="iconMeta(tool).value"
                alt=""
                class="tool-icon-img"
              >
              <span v-else>{{ iconMeta(tool)?.value || '?' }}</span>
            </span>
            <div class="tool-text">
              <span class="tool-option-label">{{ tool.tool_label || tool.tool_name }}</span>
              <span class="tool-option-sub">{{ tool.provider_name }} · {{ tool.tool_name || '全部工具' }}</span>
            </div>
          </div>
        </el-option>
      </el-option-group>
      <template v-if="!filteredGroups.length && !toolStore.loading" #empty>
        <div class="empty-search">无匹配工具</div>
      </template>
    </el-select>
    <p v-if="toolStore.loadError" class="hint error">{{ toolStore.loadError }}</p>

    <div v-if="tools.length" class="tool-list">
      <div v-for="tool in tools" :key="toolKey(tool)" class="tool-row">
        <div class="tool-main">
          <el-switch
            :model-value="tool.enabled !== false"
            size="small"
            :disabled="readOnly"
            @change="(val) => onToggle(tool, val)"
          />
          <span class="tool-icon sm" :style="iconStyle(resolveCatalog(tool) || tool)">
            <img
              v-if="iconMeta(resolveCatalog(tool) || tool)?.type === 'url'"
              :src="iconMeta(resolveCatalog(tool) || tool).value"
              alt=""
              class="tool-icon-img"
            >
            <span v-else>{{ iconMeta(resolveCatalog(tool) || tool)?.value || '?' }}</span>
          </span>
          <span class="tool-label">{{ labelFor(tool) }}</span>
        </div>
        <div class="tool-actions">
          <el-select
            v-if="supportsCredentials(tool)"
            :model-value="tool.credential_ref?.id || ''"
            clearable
            size="small"
            placeholder="凭证"
            style="width: 140px"
            :disabled="readOnly"
            @change="(val) => onCredential(tool, val)"
            @visible-change="(open) => open && loadCredentials(tool)"
          >
            <el-option
              v-for="cred in credentialsByProvider[tool.provider_id] || []"
              :key="cred.id"
              :label="cred.is_default ? `${cred.name || cred.id}（默认）` : (cred.name || cred.id)"
              :value="cred.id"
            />
          </el-select>
          <el-button
            v-if="supportsCredentials(tool) && !readOnly"
            size="small"
            text
            @click="openCredentialDialog(tool)"
          >
            新建凭证
          </el-button>
          <el-button
            v-if="!readOnly"
            size="small"
            text
            type="danger"
            @click="onRemove(tool)"
          >
            删除
          </el-button>
        </div>
      </div>
    </div>
    <p v-else class="hint">尚未配置工具。Agent 运行时将无法调用 Dify Tools。</p>
    <BuiltinToolCredentialDialog
      v-model:visible="credentialDialog.visible"
      :provider="credentialDialog.provider"
      :provider-label="credentialDialog.label"
      @saved="onCredentialCreated"
    />
  </PanelSection>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import PanelSection from '../shared/PanelSection.vue'
import BuiltinToolCredentialDialog from '../tool/BuiltinToolCredentialDialog.vue'
import { useToolStore } from '@/features/integrations/state/useToolStore.js'
import { groupSelectableTools } from '@/features/integrations/state/toolCatalog.js'
import {
  fetchBuiltinCredentials,
  unwrapCredentialList,
} from '@/features/integrations/api/difyToolsApi.js'
import { toolProviderIcon } from '@/features/integrations/lib/toolProviderHelpers.js'
import {
  addDifyTool,
  difyToolKey,
  difyToolLabel,
  isCatalogToolSelected,
  removeDifyTool,
  setDifyToolCredential,
  setDifyToolEnabled,
} from './agentTools.js'

const props = defineProps({
  tools: { type: Array, default: () => [] },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['update:tools'])

const toolStore = useToolStore()
const credentialsByProvider = reactive({})
const searchQuery = ref('')
const credentialDialog = reactive({ visible: false, provider: '', label: '', tool: null })

const groupedOptions = computed(() => {
  return groupSelectableTools(toolStore.allTools)
})

const filteredGroups = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return groupedOptions.value
  return groupedOptions.value
    .map((group) => ({
      ...group,
      tools: group.tools.filter((tool) => {
        return toolSearchLabel(tool).toLowerCase().includes(q)
          || String(tool.provider_id || '').toLowerCase().includes(q)
      }),
    }))
    .filter(group => group.tools.length)
})

onMounted(() => {
  toolStore.fetchTools()
})

function toolSearchLabel(tool) {
  return [
    tool.provider_name,
    tool.tool_label,
    tool.tool_name,
    tool.description,
  ].filter(Boolean).join(' ')
}

function toolKey(tool) {
  return difyToolKey(tool)
}

function labelFor(tool) {
  return difyToolLabel(tool, query => toolStore.findTool(query))
}

function resolveCatalog(tool) {
  return toolStore.findTool({
    provider_type: tool?.provider_type,
    provider_id: tool?.provider_id,
    tool_name: tool?.tool_name,
  })
}

function iconMeta(tool) {
  return toolProviderIcon({
    icon: tool?.icon ?? tool?.icon_small,
    icon_small: tool?.icon_small,
    label: tool?.tool_label || tool?.provider_name || tool?.tool_name || '?',
    provider: tool?.provider_name || tool?.provider_id,
  })
}

function iconStyle(tool) {
  const meta = iconMeta(tool)
  if (meta?.type === 'emoji' || meta?.type === 'letter') {
    return {
      background: meta.background || '#eff4ff',
    }
  }
  return {}
}

function isSelected(catalogTool) {
  return isCatalogToolSelected(props.tools, catalogTool)
}

function supportsCredentials(tool) {
  return (tool.provider_type || 'builtin') === 'builtin' && !!tool.provider_id
}

async function loadCredentials(tool) {
  const providerId = tool?.provider_id
  if (!providerId || !supportsCredentials(tool))
    return
  if (credentialsByProvider[providerId])
    return
  try {
    const payload = await fetchBuiltinCredentials(providerId)
    credentialsByProvider[providerId] = unwrapCredentialList(payload)
  }
  catch {
    credentialsByProvider[providerId] = []
  }
}

function onFilter(query) {
  searchQuery.value = String(query || '')
}

function onVisibleChange(open) {
  if (!open)
    searchQuery.value = ''
}

function onAddTool(key) {
  const parts = String(key).split('::')
  const provider_type = parts.length >= 3 ? parts.shift() : 'builtin'
  const rawName = parts.pop()
  const tool_name = rawName === '*' || rawName === '' ? null : rawName
  const provider_id = parts.join('::')
  const catalog = toolStore.findTool({ provider_type, provider_id, tool_name })
  emit('update:tools', addDifyTool(props.tools, catalog))
  searchQuery.value = ''
}

function onRemove(tool) {
  emit('update:tools', removeDifyTool(props.tools, difyToolKey(tool)))
}

function onToggle(tool, enabled) {
  emit('update:tools', setDifyToolEnabled(props.tools, difyToolKey(tool), enabled))
}

function onCredential(tool, credentialId) {
  emit('update:tools', setDifyToolCredential(props.tools, difyToolKey(tool), credentialId))
}

function openCredentialDialog(tool) {
  credentialDialog.visible = true
  credentialDialog.provider = tool.provider_id
  credentialDialog.label = labelFor(tool)
  credentialDialog.tool = tool
}

function onCredentialCreated({ credentialId, credentials }) {
  if (!credentialDialog.provider || !credentialDialog.tool)
    return
  credentialsByProvider[credentialDialog.provider] = credentials
  onCredential(credentialDialog.tool, credentialId)
  credentialDialog.tool = null
}
</script>

<style scoped>
.w-full { width: 100%; }
.hint { margin: 0 0 8px; font-size: 12px; color: #667085; }
.hint.error { color: #b42318; }
.tool-list { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.tool-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid #eaecf0;
  border-radius: 6px;
}
.tool-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.tool-label { font-size: 12px; color: #344054; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tool-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.tool-option {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.tool-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 1px;
}
.tool-option-label {
  font-size: 13px;
  color: #101828;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-option-sub {
  font-size: 11px;
  color: #98a2b3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-icon {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 12px;
  background: #eff4ff;
  overflow: hidden;
}
.tool-icon.sm {
  width: 18px;
  height: 18px;
  font-size: 10px;
}
.tool-icon-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.empty-search {
  padding: 10px 12px;
  color: #98a2b3;
  font-size: 12px;
  text-align: center;
}
</style>

<style>
.agent-tool-select-popper .el-select-dropdown__item {
  height: auto;
  padding: 8px 12px;
  line-height: 1.3;
}
</style>
