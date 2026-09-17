<template>
  <div class="tool-panel">
    <div class="panel-header">
      <div class="header-left">
        <BlockIcon type="tool" :size="20" :tool-icon="panelToolIcon" />
        <input v-model="nodeTitle" class="title-input" placeholder="工具调用" :disabled="readOnly" />
      </div>
      <button type="button" class="close-btn" aria-label="关闭工具节点设置" @click="$emit('close')"><el-icon><Close /></el-icon></button>
    </div>

    <div class="panel-body">
      <div class="form-section">
        <label class="section-label">选择工具</label>
        <el-select
          :model-value="selectedKey"
          filterable
          class="w-full"
          placeholder="从工作区工具目录选择"
          :disabled="readOnly || toolStore.loading"
          @change="onSelectTool"
        >
          <el-option-group
            v-for="group in groupedOptions"
            :key="group.type"
            :label="group.label"
          >
            <el-option
              v-for="tool in group.tools"
              :key="tool.provider_type + '::' + tool.provider_id + '::' + tool.tool_name"
              :label="`${tool.provider_name} / ${tool.tool_label}`"
              :value="tool.provider_type + '::' + tool.provider_id + '::' + tool.tool_name"
            />
          </el-option-group>
        </el-select>
        <p v-if="toolStore.loadError" class="hint error">{{ toolStore.loadError }}</p>
        <p v-else-if="!groupedOptions.length && !toolStore.loading" class="hint">
          工作区暂无可用工具。请先到
          <RouterLink :to="{ path: '/integrations', query: { tab: 'tools' } }">工作区集成 → 工具授权</RouterLink>
          完成安装/授权。
        </p>
      </div>

      <div v-if="parameterSchemas.length" class="form-section">
        <label class="section-label">工具参数</label>
        <div class="params-list">
          <label
            v-for="param in parameterSchemas"
            :key="param.name"
            class="param-row stacked"
          >
            <span>
              {{ paramLabel(param) }}
              <em v-if="param.required" class="required">*</em>
            </span>
            <p v-if="paramDescription(param)" class="param-desc">{{ paramDescription(param) }}</p>
            <PromptVariableTextarea
              v-if="paramKind(param) === 'llm' || paramKind(param) === 'secret'"
              :model-value="parameterDisplayValue(param.name)"
              :node-id="nodeId"
              :rows="2"
              :disabled="readOnly"
              :read-only="readOnly"
              :placeholder="paramKind(param) === 'secret' ? paramLabel(param) : paramPlaceholder(param)"
              @update:model-value="setParameter(param.name, $event)"
            />
            <VarReferencePicker
              v-else-if="paramKind(param) === 'file'"
              :model-value="fileSelector(param.name)"
              :node-id="nodeId"
              :read-only="readOnly"
              :filter-var="isToolFileVariable"
              placeholder="选择文件变量"
              @update:model-value="setParameterEnvelope(param.name, { type: 'variable', value: $event || [] })"
            />
            <el-switch
              v-else-if="paramKind(param) === 'boolean'"
              :model-value="Boolean(parameterValue(param.name))"
              :disabled="readOnly"
              @change="setParameterEnvelope(param.name, { type: 'constant', value: $event })"
            />
            <el-input-number
              v-else-if="paramKind(param) === 'number'"
              :model-value="Number(parameterValue(param.name) || 0)"
              class="w-full"
              size="small"
              :disabled="readOnly"
              @change="setParameterEnvelope(param.name, { type: 'constant', value: $event })"
            />
            <el-select
              v-else-if="paramKind(param) === 'select'"
              :model-value="parameterValue(param.name)"
              class="w-full"
              size="small"
              :disabled="readOnly"
              @change="setParameterEnvelope(param.name, { type: 'constant', value: $event })"
            >
              <el-option
                v-for="option in paramOptions(param)"
                :key="String(option.value)"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-input
              v-else
              :model-value="parameterDisplayValue(param.name)"
              size="small"
              :disabled="readOnly"
              :placeholder="paramPlaceholder(param)"
              @update:model-value="setParameterEnvelope(param.name, { type: 'constant', value: $event })"
            />
          </label>
        </div>
      </div>

      <div v-if="supportsCredentials" class="form-section">
        <label class="section-label">凭证</label>
        <el-select
          v-model="credentialId"
          clearable
          filterable
          class="w-full"
          placeholder="使用默认凭证"
          :disabled="readOnly || credentialsLoading"
          :loading="credentialsLoading"
        >
          <el-option
            v-for="cred in credentials"
            :key="cred.id"
            :label="credentialLabel(cred)"
            :value="cred.id"
          />
        </el-select>
        <div class="credential-actions">
          <button type="button" :disabled="readOnly" @click="credentialDialogOpen = true">
            新建凭证
          </button>
          <RouterLink :to="{ path: '/integrations', query: { tab: 'tools' } }">管理凭证</RouterLink>
        </div>
        <p v-if="credentialsError" class="hint error">{{ credentialsError }}</p>
        <p v-else-if="!credentials.length && !credentialsLoading" class="hint">
          该工具尚无凭证。新建后会自动绑定到当前节点。
        </p>
      </div>

      <RetryConfig
        :node-data="nodeData"
        :read-only="readOnly"
        @update:retry-config="handleRetryConfigUpdate"
      />
      <ErrorHandleConfig
        :node-data="nodeData"
        :read-only="readOnly"
        @update:error-strategy="handleErrorStrategyUpdate"
        @update:default-value="handleDefaultValueUpdate"
      />

      <NextStep :node-id="nodeId" :node-data="nodeData" :read-only="readOnly" />
    </div>
    <BuiltinToolCredentialDialog
      v-model:visible="credentialDialogOpen"
      :provider="providerId"
      :provider-label="selectedToolMeta?.provider_name || providerId"
      @saved="onCredentialCreated"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { Close } from '@element-plus/icons-vue'
import BlockIcon from '../base/BlockIcon.vue'
import NextStep from '../shared/NextStep.vue'
import PromptVariableTextarea from '../shared/PromptVariableTextarea.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import RetryConfig from '../shared/RetryConfig.vue'
import ErrorHandleConfig from '../shared/ErrorHandleConfig.vue'
import BuiltinToolCredentialDialog from './BuiltinToolCredentialDialog.vue'
import { useToolConfig } from './useToolConfig.js'
import { getToolParamEditorKind, isSecretToolParam, isToolFileVariable } from '../../model/toolParamInputs.js'
import { useToolStore } from '@/features/integrations/state/useToolStore.js'
import { groupSelectableTools } from '@/features/integrations/state/toolCatalog.js'
import {
  fetchBuiltinCredentials,
  unwrapCredentialList,
} from '@/features/integrations/api/difyToolsApi.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:nodeData'])

const toolStore = useToolStore()
const {
  readOnly,
  providerId,
  catalogueProviderType,
  toolName,
  credentialId,
  applyToolSelection,
  setParameter,
  setParameterEnvelope,
  parameterDisplayValue,
  parameterValue,
  handleRetryConfigUpdate,
  handleErrorStrategyUpdate,
  handleDefaultValueUpdate,
} = useToolConfig(props, emit)

const panelToolIcon = computed(() => {
  if (props.nodeData?.provider_icon != null && props.nodeData.provider_icon !== '')
    return props.nodeData.provider_icon
  const matched = toolStore.findTool({
    provider_type: props.nodeData?.provider_type,
    provider_id: props.nodeData?.provider_id,
    tool_name: props.nodeData?.tool_name,
  })
  return matched?.icon ?? matched?.icon_small ?? null
})

const credentials = ref([])
const credentialsLoading = ref(false)
const credentialsError = ref('')
const credentialDialogOpen = ref(false)

const supportsCredentials = computed(() => {
  if (!providerId.value) return false
  return catalogueProviderType.value === 'builtin'
})

onMounted(() => {
  toolStore.fetchTools()
})

watch(
  [providerId, catalogueProviderType],
  () => {
    loadCredentials()
  },
  { immediate: true },
)

async function loadCredentials() {
  credentials.value = []
  credentialsError.value = ''
  if (!supportsCredentials.value || !providerId.value) return
  credentialsLoading.value = true
  try {
    const payload = await fetchBuiltinCredentials(providerId.value)
    credentials.value = unwrapCredentialList(payload)
  } catch (e) {
    credentialsError.value = e.message || '加载凭证失败'
    credentials.value = []
  } finally {
    credentialsLoading.value = false
  }
}

function credentialLabel(cred) {
  const name = cred.name || cred.id
  return cred.is_default ? `${name}（默认）` : name
}

function onCredentialCreated({ credentialId: createdCredentialId, credentials: nextCredentials }) {
  credentials.value = nextCredentials
  credentialId.value = createdCredentialId
}

const nodeTitle = computed({
  get: () => props.nodeData?.title || '工具调用',
  set: (val) => emit('update:nodeData', { ...props.nodeData, title: val }),
})

const selectedKey = computed(() => {
  if (!providerId.value || !toolName.value) return ''
  return `${catalogueProviderType.value}::${providerId.value}::${toolName.value}`
})

const selectedToolMeta = computed(() =>
  toolStore.findTool({
    provider_type: props.nodeData?.provider_type,
    provider_id: providerId.value,
    tool_name: toolName.value,
  }),
)

const parameterSchemas = computed(() =>
  selectedToolMeta.value?.parameters?.length
    ? selectedToolMeta.value.parameters
    : (Array.isArray(props.nodeData?.parameters) ? props.nodeData.parameters : []),
)

const groupedOptions = computed(() => {
  return groupSelectableTools(toolStore.allTools)
})

function paramKind(param) {
  return getToolParamEditorKind(param)
}

function paramLabel(param) {
  return param.label?.zh_Hans || param.label?.en_US || param.label || param.name
}

function paramDescription(param) {
  return param.human_description?.zh_Hans
    || param.human_description?.en_US
    || param.llm_description
    || ''
}

function paramPlaceholder(param) {
  if (isSecretToolParam(param))
    return paramLabel(param)
  return paramDescription(param) || param.name
}

function paramOptions(param) {
  return (param.options || []).map((option) => {
    if (option && typeof option === 'object') {
      return {
        value: option.value,
        label: option.label?.zh_Hans || option.label?.en_US || option.label || option.value,
      }
    }
    return { value: option, label: String(option) }
  })
}

function fileSelector(name) {
  const value = parameterValue(name)
  return Array.isArray(value) ? value : []
}

function onSelectTool(key) {
  const parts = String(key).split('::')
  const provider_type = parts.length >= 3 ? parts.shift() : 'builtin'
  const tool_name = parts.pop()
  const provider_id = parts.join('::')
  const tool = toolStore.findTool({ provider_type, provider_id, tool_name })
  applyToolSelection(tool)
}
</script>

<style scoped>
.tool-panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: #fff; border-left: 1px solid #eaecf0; }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid #f2f4f7; background: #fafafa; }
.header-left { display: flex; align-items: center; gap: 8px; flex: 1; }
.title-input { font-size: 14px; font-weight: 600; color: #101828; border: none; background: transparent; }
.close-btn { background: transparent; border: none; cursor: pointer; color: #667085; }
.panel-body { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.form-section { display: flex; flex-direction: column; gap: 8px; }
.section-label { font-size: 12px; font-weight: 600; color: #344054; }
.params-list { display: flex; flex-direction: column; gap: 10px; }
.param-row { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #475467; }
.param-desc { margin: 0; font-size: 11px; color: #667085; }
.required { color: #d92d20; font-style: normal; }
.hint { margin: 0; font-size: 12px; color: #667085; }
.hint.error { color: #b42318; }
.hint a { color: #155eef; text-decoration: none; }
.hint a:hover { text-decoration: underline; }
.credential-actions { display: flex; align-items: center; gap: 10px; }
.credential-actions button, .credential-actions a { border: 0; background: transparent; color: #155eef; font-size: 12px; cursor: pointer; text-decoration: none; }
.credential-actions button:disabled { color: #98a2b3; cursor: not-allowed; }
.w-full { width: 100%; }
</style>
