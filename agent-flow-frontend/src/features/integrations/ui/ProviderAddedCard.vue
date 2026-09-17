<template>
  <!-- Mirror: web/.../provider-added-card/index.tsx (list layout) -->
  <div
    class="provider-card"
    :class="{
      openai: provider.provider === 'langgenius/openai/openai',
      anthropic: provider.provider === 'langgenius/anthropic/anthropic',
    }"
  >
    <div class="card-top">
      <div class="card-main">
        <div class="provider-title">
          <img
            v-if="iconUrl"
            :src="iconUrl"
            alt=""
            class="provider-icon"
          >
          <div v-else class="provider-icon placeholder">{{ label.slice(0, 1) }}</div>
          <strong>{{ label }}</strong>
        </div>
        <div class="badges">
          <span
            v-for="type in provider.supported_model_types || []"
            :key="type"
            class="badge"
          >
            {{ modelTypeFormat(type) }}
          </span>
        </div>
      </div>

      <div class="card-actions">
        <button
          v-if="showCredential"
          type="button"
          class="credential-btn"
          :class="{ configured: credentialConfigured }"
          @click="emit('configure', provider)"
        >
          {{ credentialConfigured ? '管理密钥' : '设置' }}
        </button>
        <button
          v-if="canUninstall"
          type="button"
          class="uninstall-btn"
          :disabled="uninstalling"
          @click="emit('uninstall', provider)"
        >
          {{ uninstalling ? '卸载中…' : '卸载' }}
        </button>
      </div>
    </div>

    <div v-if="showCollapsedSection" class="card-bottom">
      <template v-if="!notConfigured">
        <button
          type="button"
          class="show-models-btn"
          :disabled="loading"
          @click="handleOpenModelList"
        >
          <span>{{ hasModelList ? `${models.length} 个模型` : '显示模型' }}</span>
          <span v-if="loading" class="spinner" />
          <span v-else class="chevron">›</span>
        </button>
      </template>
      <div v-else class="configure-tip">
        <span class="info">i</span>
        <span>请先配置 API Key</span>
      </div>
    </div>

    <div v-else class="model-list-wrap">
      <div class="model-list-head">
        <button type="button" class="collapse-btn" @click="collapse">
          {{ models.length }} 个模型
          <span class="chevron down">›</span>
        </button>
      </div>
      <div v-if="error" class="model-error">{{ error }}</div>
      <div v-else-if="!models.length" class="model-empty">暂无模型</div>
      <div
        v-for="model in models"
        :key="`${model.model_type}:${model.model}:${model.fetch_from}`"
        class="model-row"
      >
        <div class="model-info">
          <strong>{{ model.label }}</strong>
          <span class="meta">
            {{ model.model_type }}
            <template v-if="model.mode"> · {{ model.mode }}</template>
          </span>
        </div>
        <span class="status" :class="model.status">{{ model.status }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { fetchProviderModels } from '@/features/integrations/api/difyModelsApi.js'
import {
  ConfigurationMethodEnum,
  modelTypeFormat,
  normalizeProviderModels,
  providerIconUrl,
  providerLabel,
} from '../lib/modelProviderHelpers.js'

const props = defineProps({
  provider: { type: Object, required: true },
  notConfigured: { type: Boolean, default: false },
  canUninstall: { type: Boolean, default: false },
  uninstalling: { type: Boolean, default: false },
})

const emit = defineEmits(['configure', 'uninstall', 'refreshed'])

const expanded = ref(false)
const loading = ref(false)
const fetched = ref(false)
const error = ref('')
const models = ref([])

const label = computed(() => providerLabel(props.provider))
const iconUrl = computed(() => providerIconUrl(props.provider))
const methods = computed(() => props.provider.configurate_methods || [])
const showCredential = computed(() =>
  methods.value.includes(ConfigurationMethodEnum.predefinedModel),
)
const credentialConfigured = computed(() =>
  props.provider.custom_configuration?.status === 'active'
  || !!props.provider.custom_configuration?.current_credential_id,
)
const hasModelList = computed(() => fetched.value && models.value.length > 0)
const showCollapsedSection = computed(() => !expanded.value || !fetched.value)

async function loadModels() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetchProviderModels(props.provider.provider)
    models.value = normalizeProviderModels(response)
    fetched.value = true
  } catch (e) {
    error.value = e.message || '加载模型失败'
    models.value = []
    fetched.value = true
  } finally {
    loading.value = false
  }
}

async function handleOpenModelList() {
  if (loading.value) return
  if (!expanded.value) {
    expanded.value = true
    if (!fetched.value)
      await loadModels()
    return
  }
  await loadModels()
}

function collapse() {
  expanded.value = false
}

async function refresh() {
  if (expanded.value)
    await loadModels()
}

watch(
  () => props.provider.provider,
  () => {
    expanded.value = false
    fetched.value = false
    models.value = []
    error.value = ''
  },
)

defineExpose({ refresh })
</script>

<style scoped>
.provider-card {
  border: 0.5px solid #e4e7ec;
  border-radius: 12px;
  background: #f8fafc;
  box-shadow: 0 1px 2px rgb(16 24 40 / 4%);
  overflow: hidden;
}
.provider-card.openai {
  background: linear-gradient(180deg, #f3f4f6 0%, #f8fafc 100%);
}
.provider-card.anthropic {
  background: linear-gradient(180deg, #fff7ed 0%, #f8fafc 100%);
}
.card-top {
  display: flex;
  gap: 12px;
  padding: 10px 8px 8px 12px;
}
.card-main {
  flex: 1;
  min-width: 0;
}
.provider-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.provider-title strong {
  font-size: 14px;
  color: #101828;
}
.provider-icon {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  object-fit: contain;
}
.provider-icon.placeholder {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #eef2ff;
  color: #3538cd;
  font-size: 12px;
  font-weight: 600;
}
.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.badge {
  border: 1px solid #e4e7ec;
  border-radius: 6px;
  padding: 1px 6px;
  font-size: 10px;
  color: #667085;
  background: #fff;
}
.card-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
  justify-content: flex-start;
  margin-left: auto;
}
.credential-btn,
.uninstall-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 28px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 550;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease-in-out;
  outline: none;
  box-sizing: border-box;
}
.credential-btn {
  border: 1px solid #d0d5dd;
  background: #ffffff;
  color: #344054;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
}
.credential-btn:hover {
  background: #f8fafc;
  border-color: #98a2b3;
  color: #1d2939;
}
.credential-btn.configured {
  border: 1px solid #abefc6;
  background: #ecfdf3;
  color: #027a48;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
}
.credential-btn.configured:hover {
  background: #d1fadf;
  border-color: #6ce9a6;
  color: #05603a;
  box-shadow: 0 1px 3px rgba(16, 24, 40, 0.08);
}
.uninstall-btn {
  border: 1px solid #fee4e2;
  background: #fffbfa;
  color: #d92d20;
}
.uninstall-btn:hover {
  background: #fef3f2;
  border-color: #fda29b;
  color: #b42318;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
}
.uninstall-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
  box-shadow: none;
}
.card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid #eaecf0;
  padding: 6px 10px;
  color: #667085;
  font-size: 12px;
}
.show-models-btn,
.collapse-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 0;
  background: transparent;
  color: #667085;
  font-size: 12px;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 8px;
}
.show-models-btn:hover,
.collapse-btn:hover {
  background: #f2f4f7;
}
.chevron {
  font-size: 14px;
  line-height: 1;
}
.chevron.down {
  transform: rotate(90deg);
  display: inline-block;
}
.spinner {
  width: 12px;
  height: 12px;
  border: 2px solid #d0d5dd;
  border-top-color: #667085;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.configure-tip {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #344054;
  font-size: 12px;
}
.info {
  display: inline-flex;
  width: 16px;
  height: 16px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--af-brand-soft);
  color: var(--af-brand-strong);
  font-size: 10px;
  font-weight: 700;
}
.model-list-wrap {
  padding: 0 8px 8px;
}
.model-list-head {
  border-radius: 8px 8px 0 0;
  background: #fff;
  padding: 4px 4px 0;
}
.model-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  background: #fff;
  padding: 8px 10px;
  border-top: 1px solid #f2f4f7;
}
.model-row:last-child {
  border-radius: 0 0 8px 8px;
}
.model-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.model-info strong {
  font-size: 13px;
  color: #344054;
}
.meta {
  font-size: 11px;
  color: #98a2b3;
}
.status {
  font-size: 11px;
  color: #667085;
  border: 1px solid #e4e7ec;
  border-radius: 999px;
  padding: 2px 8px;
}
.status.active {
  color: #027a48;
  border-color: #abefc6;
  background: #ecfdf3;
}
.model-error,
.model-empty {
  background: #fff;
  padding: 10px;
  font-size: 12px;
  color: #667085;
  border-radius: 0 0 8px 8px;
}
.model-error {
  color: #b42318;
}
</style>
