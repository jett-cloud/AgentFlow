<!-- Mirror: web/.../model-provider-page/model-icon/index.tsx -->
<template>
  <span class="model-icon-wrapper" :class="sizeClass">
    <img
      v-if="iconUrl && !imgFailed"
      :src="iconUrl"
      alt=""
      class="model-img"
      @error="imgFailed = true"
    >
    <span v-else class="model-fallback" aria-hidden="true">{{ fallbackLetter }}</span>
  </span>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import {
  i18nText,
  providerIconUrl,
  resolveConsoleAssetUrl,
} from '@/features/integrations/lib/modelProviderHelpers.js'
import { useModelStore } from '@/features/integrations/state/useModelStore.js'

const props = defineProps({
  modelName: { type: String, default: '' },
  provider: { type: String, default: '' },
  icon: { type: [String, Object], default: null },
  /** sm = 16px (select options), md = 20px (node badge) */
  size: { type: String, default: 'sm' },
})

const modelStore = useModelStore()
const imgFailed = ref(false)

watch(
  () => [props.provider, props.modelName],
  () => { imgFailed.value = false },
)

const providerRow = computed(() => {
  if (props.provider)
    return modelStore.getProvider?.(props.provider) || null
  // Fallback: infer provider from selected model name
  if (!props.modelName) return null
  const hit = modelStore.allModels.find(item => item.model === props.modelName)
  return hit ? modelStore.getProvider?.(hit.provider) : null
})

const iconUrl = computed(() => (
  resolveConsoleAssetUrl(i18nText(props.icon, ''))
  || providerIconUrl(providerRow.value)
))

const fallbackLetter = computed(() => {
  const raw = props.modelName || props.provider || '?'
  const part = String(raw).split('/').pop() || raw
  return part.slice(0, 1).toUpperCase()
})

const sizeClass = computed(() => (props.size === 'md' ? 'size-md' : 'size-sm'))
</script>

<style scoped>
.model-icon-wrapper {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
  border-radius: 4px;
  background: #f2f4f7;
}
.size-sm {
  width: 16px;
  height: 16px;
}
.size-md {
  width: 20px;
  height: 20px;
  border-radius: 5px;
}
.model-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
.model-fallback {
  color: #667085;
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
}
.size-md .model-fallback {
  font-size: 11px;
}
</style>
