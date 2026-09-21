<!-- panel/base/ModelSelector.vue -->
<template>
  <div class="model-selector" :class="{ 'has-selection': selectedKey }">
    <div class="model-select-control">
      <el-select
        :model-value="selectedKey"
        :placeholder="placeholder"
        :disabled="disabled || readOnly || !modelStore.hasConfiguredModels"
        filterable
        clearable
        default-first-option
        :filter-method="onFilter"
        class="w-full"
        popper-class="workflow-model-select-popper"
        @change="onSelect"
        @visible-change="onVisibleChange"
      >
      <el-option-group
        v-for="provider in filteredProviders"
        :key="provider.provider"
        :label="provider.label"
      >
        <el-option
          v-for="m in provider.models"
          :key="provider.provider + '/' + m.model"
          :label="m.label || m.model"
          :value="provider.provider + '::' + m.model"
        >
          <div class="model-option">
            <ModelIcon
              :provider="provider.provider"
              :model-name="m.model"
              size="sm"
            />
            <div class="model-text">
              <span class="model-label">{{ m.label }}</span>
              <span v-if="m.label !== m.model" class="model-id">{{ m.model }}</span>
            </div>
            <el-tag v-if="hasVision(m)" size="small" type="info" class="feat-tag">Vision</el-tag>
            <el-tag v-if="hasToolCall(m)" size="small" type="success" class="feat-tag">Tool</el-tag>
          </div>
        </el-option>
      </el-option-group>
      <template v-if="!filteredProviders.length && modelStore.hasConfiguredModels" #empty>
        <div class="empty-search">无匹配模型，试试模型名如 gpt-4o</div>
      </template>
      </el-select>
      <div v-if="selectedKey && !selectOpen" class="selected-model" aria-hidden="true">
        <ModelIcon
          :provider="modelValue?.provider || ''"
          :model-name="modelValue?.name || ''"
          size="sm"
        />
        <span class="selected-model-name">{{ selectedModelLabel }}</span>
        <span v-if="selectedProviderLabel" class="selected-provider">{{ selectedProviderLabel }}</span>
      </div>
    </div>
    <p v-if="modelStore.loading" class="hint">正在加载工作区模型…</p>
    <p v-else-if="modelStore.loadError" class="hint error">{{ modelStore.loadError }}</p>
    <p v-else-if="selectedUnavailable" class="hint warn">
      已选择 {{ modelValue?.name }}，但当前工作区模型目录中不可用。
    </p>
    <p v-else-if="selectedIncompatible" class="hint warn">
      当前模型不支持函数调用，请选择带 Tool 能力的模型。
    </p>
    <p v-else-if="!modelStore.hasConfiguredModels" class="hint warn">
      工作区尚无可用模型。请先到
      <RouterLink :to="{ path: '/integrations', query: { tab: 'models' } }">工作区集成 → 模型提供商</RouterLink>
      配置 API Key。
    </p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useModelStore, ModelFeatureEnum } from '@/features/integrations/state/useModelStore.js'
import { filterFunctionCallingProviders, supportsFunctionCalling } from '@/features/integrations/tool-plugin/modelCapabilities.js'
import ModelIcon from '../base/ModelIcon.vue'

const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({ provider: '', name: '', mode: 'chat', completion_params: {} }),
  },
  placeholder: { type: String, default: '搜索并选择模型' },
  disabled: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
  requireToolCall: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'change'])

const modelStore = useModelStore()
const searchQuery = ref('')
const selectOpen = ref(false)

onMounted(() => {
  modelStore.hydrateModelWorkspace?.()
})

const selectedKey = computed(() => {
  const { provider, name } = props.modelValue || {}
  if (!provider || !name) return ''
  return `${provider}::${name}`
})

const selectedSpec = computed(() => modelStore.getModelSpec(
  props.modelValue?.name,
  props.modelValue?.provider,
))
const selectedProvider = computed(() => modelStore.getProvider?.(props.modelValue?.provider) || null)
const selectedModelLabel = computed(() => (
  selectedSpec.value?.label || props.modelValue?.name || props.placeholder
))
const selectedProviderLabel = computed(() => {
  const label = selectedProvider.value?.label
  if (typeof label === 'string') return label
  return label?.zh_Hans || label?.en_US || props.modelValue?.provider || ''
})
const selectedUnavailable = computed(() => (
  !!selectedKey.value && modelStore.loaded && !selectedSpec.value
))
const selectedIncompatible = computed(() => (
  props.requireToolCall
  && !!selectedSpec.value
  && !supportsFunctionCalling(selectedSpec.value)
))

function optionSearchLabel(provider, model) {
  const label = String(model?.label || model?.model || '')
  const id = String(model?.model || '')
  const providerLabel = String(provider?.label || provider?.provider || '')
  if (label && id && label !== id)
    return `${label} ${id} ${providerLabel}`
  return `${label || id} ${providerLabel}`.trim()
}

const filteredProviders = computed(() => {
  const list = props.requireToolCall
    ? filterFunctionCallingProviders(modelStore.providers)
    : (modelStore.providers || [])
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return list

  return list
    .map((provider) => {
      const providerHit = String(provider.label || '').toLowerCase().includes(q)
        || String(provider.provider || '').toLowerCase().includes(q)
      const models = (provider.models || []).filter((m) => {
        if (providerHit) return true
        return String(m.label || '').toLowerCase().includes(q)
          || String(m.model || '').toLowerCase().includes(q)
          || optionSearchLabel(provider, m).toLowerCase().includes(q)
      })
      return { ...provider, models }
    })
    .filter(provider => provider.models.length > 0)
})

function onFilter(query) {
  searchQuery.value = String(query || '')
}

function onVisibleChange(open) {
  selectOpen.value = open
  if (!open)
    searchQuery.value = ''
}

function hasVision(m) {
  return m.features?.includes(ModelFeatureEnum.VISION)
}
function hasToolCall(m) {
  return supportsFunctionCalling(m)
}

function onSelect(key) {
  if (!key) {
    const cleared = {
      ...props.modelValue,
      provider: '',
      name: '',
      mode: 'chat',
    }
    emit('update:modelValue', cleared)
    emit('change', cleared)
    return
  }
  const sep = key.indexOf('::')
  const provider = key.slice(0, sep)
  const name = key.slice(sep + 2)
  const spec = modelStore.getModelSpec(name, provider)
  const next = {
    ...props.modelValue,
    provider,
    name,
    mode: spec?.mode || 'chat',
    completion_params: props.modelValue?.completion_params || {
      temperature: 0.7,
      top_p: 1,
      max_tokens: 4096,
    },
  }
  emit('update:modelValue', next)
  emit('change', next)
  searchQuery.value = ''
}
</script>

<style scoped>
.model-selector { width: 100%; }
.model-select-control { position: relative; width: 100%; }
.selected-model {
  position: absolute;
  z-index: 2;
  top: 50%;
  right: 42px;
  left: 30px;
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 7px;
  pointer-events: none;
  transform: translateY(-50%);
}
.selected-model-name {
  min-width: 0;
  overflow: hidden;
  color: #344054;
  font-size: 12px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.selected-provider {
  min-width: 0;
  overflow: hidden;
  color: #98a2b3;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model-option {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.model-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 1px;
}
.model-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: #101828;
}
.model-id {
  font-size: 11px;
  color: #98a2b3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.feat-tag { margin-left: auto; flex-shrink: 0; }
.empty-search {
  padding: 10px 12px;
  color: #98a2b3;
  font-size: 12px;
  text-align: center;
}
.hint { margin: 8px 0 0; font-size: 12px; color: #667085; line-height: 1.4; }
.hint.warn { color: #b54708; }
.hint.error { color: #b42318; }
.hint a { color: #155eef; text-decoration: none; }
.hint a:hover { text-decoration: underline; }
</style>

<style>
.model-selector.has-selection .el-select__placeholder {
  visibility: hidden;
}
.workflow-model-select-popper .el-select-dropdown__item {
  height: auto;
  padding: 8px 12px;
  line-height: 1.3;
}
</style>
