<template>
  <div v-if="show" class="retry-tag nodrag">
    <span class="retry-icon">↻</span>
    <span v-if="liveRetry">重试 {{ liveRetry }}</span>
    <span v-else>失败后重试 {{ retryCount }} 次</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Object, required: true },
})

const enabled = computed(() =>
  props.data?.retry_config?.retry_enabled
  || props.data?.retry_config?.enabled
  || props.data?.retry_enabled,
)

const retryCount = computed(() =>
  props.data?.retry_config?.max_retries
  || props.data?.retry_config?.retry_times
  || props.data?.max_retries
  || 1,
)

/** Live retry from node_retry SSE (Dify retry-on-node _retryIndex). */
const liveRetry = computed(() => {
  const index = props.data?._retryIndex
  if (!index)
    return ''
  const max = retryCount.value
  return max ? `${index}/${max}` : String(index)
})

const show = computed(() => enabled.value || !!props.data?._retryIndex)
</script>

<style scoped>
.retry-tag {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 0 12px 8px;
  padding: 5px 8px;
  border-radius: 8px;
  background: var(--state-accent-active, rgba(0, 51, 255, 0.08));
  color: var(--text-accent, #0033ff);
  font-size: 11px;
  font-weight: 500;
}

.retry-icon {
  font-size: 13px;
}
</style>
