<template>
  <NodePanelShell v-bind="shellProps" block-type="datasource" @close="$emit('close')" @update:node-data="emitUpdate">
    <PanelSection label="数据源" required>
      <el-select
        :model-value="selectedKey"
        filterable
        class="w-full"
        placeholder="从已安装的数据源中选择"
        :loading="loading"
        :disabled="readOnly || loading"
        @change="selectDataSource"
      >
        <el-option-group
          v-for="group in catalogGroups"
          :key="group.provider"
          :label="group.label"
        >
          <el-option
            v-for="option in group.options"
            :key="option.key"
            :label="option.datasource_label"
            :value="option.key"
            :disabled="!option.is_authorized"
          />
        </el-option-group>
      </el-select>
      <p v-if="loadError" class="hint error">{{ loadError }}</p>
      <p v-else-if="!loading && !catalog.length" class="hint">
        工作区没有可用的数据源，请先安装并授权数据源插件。
      </p>
      <p v-if="currentOption && !currentOption.is_authorized" class="hint error">
        该数据源尚未授权，请先在工作区集成中完成授权。
      </p>
    </PanelSection>

    <PanelSection v-if="isLocalFile" label="支持的文件格式">
      <el-select
        :model-value="nodeData.fileExtensions || []"
        multiple
        filterable
        allow-create
        default-first-option
        class="w-full"
        placeholder="输入扩展名后回车"
        :disabled="readOnly"
        @update:model-value="updateField('fileExtensions', $event)"
      />
    </PanelSection>

    <PanelSection v-if="parameterSchemas.length" label="数据源参数" required>
      <div class="parameter-list">
        <div v-for="parameter in parameterSchemas" :key="parameter.name" class="parameter-row">
          <div class="parameter-heading">
            <span>{{ parameterLabel(parameter) }}</span>
            <span v-if="parameter.required" class="required">*</span>
            <span class="parameter-type">{{ parameter.type }}</span>
          </div>
          <el-radio-group
            v-if="supportsConstant(parameter)"
            :model-value="parameterKind(parameter.name)"
            size="small"
            :disabled="readOnly"
            @change="setParameterKind(parameter, $event)"
          >
            <el-radio-button value="constant">常量</el-radio-button>
            <el-radio-button value="variable">变量</el-radio-button>
          </el-radio-group>

          <VarReferencePicker
            v-if="!supportsConstant(parameter) || parameterKind(parameter.name) === 'variable'"
            :model-value="parameterSelector(parameter.name)"
            :node-id="nodeId"
            :filter-var="variableFilter(parameter)"
            :read-only="readOnly"
            :placeholder="`选择 ${parameterLabel(parameter)} 变量`"
            @update:model-value="setParameterVariable(parameter.name, $event)"
          />

          <el-switch
            v-else-if="parameter.type === 'boolean'"
            :model-value="Boolean(parameterConstant(parameter.name))"
            :disabled="readOnly"
            @change="setParameterConstant(parameter.name, $event)"
          />
          <el-input-number
            v-else-if="parameter.type === 'number'"
            :model-value="numberValue(parameter.name)"
            :disabled="readOnly"
            @change="setParameterConstant(parameter.name, $event)"
          />
          <el-select
            v-else-if="parameter.type === 'select'"
            :model-value="parameterConstant(parameter.name)"
            class="w-full"
            :disabled="readOnly"
            @change="setParameterConstant(parameter.name, $event)"
          >
            <el-option
              v-for="option in parameter.options || []"
              :key="option.value"
              :label="localized(option.label, option.value)"
              :value="option.value"
            />
          </el-select>
          <el-input
            v-else
            :model-value="parameterConstant(parameter.name)"
            :type="parameter.type === 'secret_input' ? 'password' : 'text'"
            :show-password="parameter.type === 'secret_input'"
            :placeholder="localized(parameter.placeholder, '')"
            :disabled="readOnly"
            @input="setParameterConstant(parameter.name, $event)"
          />
          <p v-if="localized(parameter.description, '')" class="hint">
            {{ localized(parameter.description, '') }}
          </p>
        </div>
      </div>
    </PanelSection>

    <PanelSection v-if="outputVariables.length" label="输出变量">
      <div class="output-list">
        <div v-for="output in outputVariables" :key="output.name" class="output-row">
          <code>{{ output.name }}</code>
          <span>{{ output.type }}</span>
        </div>
      </div>
    </PanelSection>
  </NodePanelShell>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import NodePanelShell from '../shared/NodePanelShell.vue'
import PanelSection from '../shared/PanelSection.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import { fetchRagPipelineDatasourcePlugins } from '@/features/datasets/api/difyDatasourceAuthApi.js'
import {
  applyDataSourceSelection,
  flattenDataSourceCatalog,
  isDataSourceParameterVariable,
  localizeDataSourceLabel,
  normalizeDataSourceData,
} from './dataSourceNode.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:nodeData'])
const catalog = ref([])
const loading = ref(false)
const loadError = ref('')
const shellProps = computed(() => ({ nodeId: props.nodeId, nodeData: props.nodeData, readOnly: props.readOnly }))
const emitUpdate = data => emit('update:nodeData', normalizeDataSourceData(data))
const updateField = (field, value) => emitUpdate({ ...props.nodeData, [field]: value })

const selectedKey = computed(() => {
  if (!props.nodeData.plugin_id || !props.nodeData.provider_name || !props.nodeData.datasource_name)
    return ''
  return `${props.nodeData.plugin_id}::${props.nodeData.provider_name}::${props.nodeData.datasource_name}`
})
const currentOption = computed(() => catalog.value.find(option => option.key === selectedKey.value) || null)
const parameterSchemas = computed(() => currentOption.value?.parameters || props.nodeData._datasourceParameterSchemas || [])
const isLocalFile = computed(() => props.nodeData.provider_type === 'local_file')
const catalogGroups = computed(() => {
  const groups = new Map()
  for (const option of catalog.value) {
    if (!groups.has(option.provider_name)) {
      groups.set(option.provider_name, {
        provider: option.provider_name,
        label: option.provider_label,
        options: [],
      })
    }
    groups.get(option.provider_name).options.push(option)
  }
  return [...groups.values()]
})
const outputVariables = computed(() => {
  const schema = currentOption.value?.output_schema || props.nodeData._datasourceOutputSchema
  const dynamic = Object.entries(schema?.properties || {}).map(([name, value]) => ({
    name,
    type: value.type === 'array' ? `array[${value.items?.type || 'any'}]` : value.type,
  }))
  return [
    { name: 'datasource_type', type: 'string' },
    ...(isLocalFile.value ? [{ name: 'file', type: 'file' }] : []),
    ...dynamic,
  ]
})

const localized = (value, fallback = '') => localizeDataSourceLabel(value, fallback)
const parameterLabel = parameter => localized(parameter.label, parameter.name)
const parameterInput = name => props.nodeData.datasource_parameters?.[name] || { type: 'mixed', value: '' }
const parameterKind = name => parameterInput(name).type === 'variable' ? 'variable' : 'constant'
const parameterConstant = name => parameterInput(name).value ?? ''
const parameterSelector = name => Array.isArray(parameterInput(name).value) ? parameterInput(name).value : []
const numberValue = name => {
  const value = Number(parameterConstant(name))
  return Number.isFinite(value) ? value : undefined
}
const supportsConstant = parameter => !['file', 'files', 'system_files'].includes(parameter.type)
const variableFilter = parameter => variable => isDataSourceParameterVariable(variable, parameter.type)

function updateParameter(name, input) {
  updateField('datasource_parameters', {
    ...(props.nodeData.datasource_parameters || {}),
    [name]: input,
  })
}

function setParameterKind(parameter, kind) {
  updateParameter(parameter.name, {
    type: kind,
    value: kind === 'variable' ? [] : (parameter.default ?? ''),
  })
}

function setParameterConstant(name, value) {
  updateParameter(name, { type: 'constant', value: value ?? '' })
}

function setParameterVariable(name, value) {
  updateParameter(name, { type: 'variable', value })
}

function selectDataSource(key) {
  const option = catalog.value.find(item => item.key === key)
  if (!option) return
  emitUpdate({
    ...applyDataSourceSelection(props.nodeData, option),
    title: option.datasource_label || props.nodeData.title,
  })
}

function hydrateCatalogMetadata(option) {
  if (!option) return
  emitUpdate({
    ...props.nodeData,
    _datasourceAuthorized: option.is_authorized,
    _datasourceParameterSchemas: option.parameters,
    _datasourceOutputSchema: option.output_schema,
  })
}

onMounted(async () => {
  loading.value = true
  loadError.value = ''
  try {
    catalog.value = flattenDataSourceCatalog(await fetchRagPipelineDatasourcePlugins())
    hydrateCatalogMetadata(catalog.value.find(option => option.key === selectedKey.value))
  }
  catch (error) {
    catalog.value = []
    loadError.value = error?.message || '加载数据源目录失败'
  }
  finally {
    loading.value = false
  }
})
</script>

<style scoped>
.w-full { width: 100%; }
.hint { margin: 0; color: #667085; font-size: 11px; line-height: 1.5; }
.hint.error { color: #b42318; }
.parameter-list { display: flex; flex-direction: column; gap: 14px; }
.parameter-row { display: flex; flex-direction: column; gap: 7px; padding: 10px; border: 1px solid #eaecf0; border-radius: 8px; }
.parameter-heading { display: flex; align-items: center; gap: 4px; color: #344054; font-size: 12px; font-weight: 600; }
.required { color: #f04438; }
.parameter-type { margin-left: auto; color: #98a2b3; font-size: 10px; font-weight: 400; }
.output-list { display: flex; flex-direction: column; gap: 6px; }
.output-row { display: flex; align-items: center; justify-content: space-between; padding: 6px 8px; border-radius: 6px; background: #f9fafb; font-size: 11px; }
.output-row code { color: #155eef; }
.output-row span { color: #667085; }
</style>
