<!-- src/views/copilot/components/workflow/panel/base/RetryConfig.vue -->
<!--
  失败重试配置组件 (Retry on Failure)
  1:1 对齐 Dify React 官方源码 (web/app/components/workflow/nodes/_base/components/retry/retry-on-panel.tsx)
-->
<template>
  <div class="retry-config-section">
    <!-- 顶部标题与 Switch 开关 -->
    <div class="retry-header">
      <div class="header-title">
        <span>失败时重试 (RETRY ON FAILURE)</span>
      </div>
      <el-switch
        v-model="retryEnabled"
        size="small"
        :disabled="readOnly"
        @change="handleEnabledChange"
      />
    </div>

    <!-- 展开项：最大重试次数 & 重试间隔 -->
    <div v-if="retryEnabled" class="retry-body">
      <!-- 1. 最大重试次数 -->
      <div class="config-row">
        <span class="row-label">最大重试次数</span>
        <div class="row-controls">
          <el-slider
            v-model="maxRetries"
            :min="1"
            :max="10"
            :disabled="readOnly"
            class="config-slider"
            @change="handleMaxRetriesChange"
          />
          <el-input-number
            v-model="maxRetries"
            :min="1"
            :max="10"
            size="small"
            controls-position="right"
            :disabled="readOnly"
            class="config-number"
            @change="handleMaxRetriesChange"
          />
          <span class="unit-text">次</span>
        </div>
      </div>

      <!-- 2. 重试间隔时间 -->
      <div class="config-row mt-2">
        <span class="row-label">重试间隔时间</span>
        <div class="row-controls">
          <el-slider
            v-model="retryInterval"
            :min="100"
            :max="5000"
            :step="100"
            :disabled="readOnly"
            class="config-slider"
            @change="handleIntervalChange"
          />
          <el-input-number
            v-model="retryInterval"
            :min="100"
            :max="5000"
            :step="100"
            size="small"
            controls-position="right"
            :disabled="readOnly"
            class="config-number"
            @change="handleIntervalChange"
          />
          <span class="unit-text">ms</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false }
})

const emit = defineEmits(['update:retryConfig'])

// 响应式数据
const retryEnabled = ref(props.nodeData?.retry_config?.retry_enabled ?? false)
const maxRetries = ref(props.nodeData?.retry_config?.max_retries ?? 3)
const retryInterval = ref(props.nodeData?.retry_config?.retry_interval ?? 1000)

// 监听外部 nodeData 数据更新
watch(() => props.nodeData?.retry_config, (newVal) => {
  if (newVal) {
    retryEnabled.value = newVal.retry_enabled ?? false
    maxRetries.value = newVal.max_retries ?? 3
    retryInterval.value = newVal.retry_interval ?? 1000
  }
}, { deep: true })

const notifyChange = () => {
  const retryConfig = {
    retry_enabled: retryEnabled.value,
    max_retries: maxRetries.value,
    retry_interval: retryInterval.value
  }
  emit('update:retryConfig', retryConfig)
}

const handleEnabledChange = (val) => {
  retryEnabled.value = val
  notifyChange()
}

const handleMaxRetriesChange = (val) => {
  maxRetries.value = val || 3
  notifyChange()
}

const handleIntervalChange = (val) => {
  retryInterval.value = val || 1000
  notifyChange()
}
</script>

<style scoped>
.retry-config-section {
  padding: 12px 0;
  border-top: 1px solid #f2f4f7;
  border-bottom: 1px solid #f2f4f7;
}

.retry-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px;
}

.header-title {
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

.retry-body {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 10px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #f1f5f9;
}

.config-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.row-label {
  font-size: 11px;
  color: #64748b;
  font-weight: 500;
  white-space: nowrap;
}

.row-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  justify-content: flex-end;
}

.config-slider {
  width: 90px;
}

.config-number {
  width: 80px;
}

.unit-text {
  font-size: 11px;
  color: #94a3b8;
  width: 18px;
}

.mt-2 {
  margin-top: 6px;
}
</style>
