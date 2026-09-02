<!-- src/views/copilot/components/workflow/panel/base/ErrorHandleConfig.vue -->
<!--
  异常处理响应策略组件 (Error Handling)
  1:1 对齐 Dify React 官方源码 (web/app/components/workflow/nodes/_base/components/error-handle/error-handle-on-panel.tsx)
-->
<template>
  <div class="error-handle-section">
    <!-- 顶部标题与策略 Selector -->
    <div class="error-header">
      <div class="header-title">
        <span>异常处理 (ERROR HANDLING)</span>
      </div>
      <el-select
        v-model="errorStrategy"
        size="small"
        class="strategy-select"
        :disabled="readOnly"
        @change="handleStrategyChange"
      >
        <el-option label="默认终止 (Terminated)" value="none" />
        <el-option label="返回默认值 (Default Value)" value="default-value" />
        <el-option label="异常分支 (Fail Branch)" value="fail-branch" />
      </el-select>
    </div>

    <!-- 策略说明与提示 Tag -->
    <div class="strategy-desc mt-2">
      <span v-if="errorStrategy === 'none'" class="desc-text text-gray">
        节点发生报错时，整个工作流将直接中断并报错。
      </span>
      <span v-else-if="errorStrategy === 'default-value'" class="desc-text text-blue">
        节点发生报错时，忽略错误并输出设定的默认保底值继续往下执行。
      </span>
      <span v-else-if="errorStrategy === 'fail-branch'" class="desc-text text-amber">
        节点发生报错时，将从节点底部的【异常分支 (Fail Branch)】出口继续执行。
      </span>
    </div>

    <!-- 策略 2 详情：默认保底值定义表单 -->
    <div v-if="errorStrategy === 'default-value'" class="default-val-section mt-2">
      <div class="section-sub-title">保底默认值设置:</div>
      <div class="default-val-card">
        <div 
          v-for="item in defaultValues"
          :key="item.key"
          class="default-val-row"
        >
          <span class="val-key font-mono">{{ item.key }}:</span>
          <el-input 
            :model-value="item.value"
            size="small" 
            placeholder="请输入默认值"
            :disabled="readOnly"
            @change="(value) => handleDefaultValueChange(item.key, value)"
          />
        </div>
        <div v-if="!defaultValues.length" class="empty-tip">
          无需要配置的输出字段
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

const emit = defineEmits(['update:errorStrategy', 'update:defaultValue'])

const errorStrategy = ref(props.nodeData?.error_strategy || 'none')
const defaultValues = ref(Array.isArray(props.nodeData?.default_value) ? props.nodeData.default_value : [])

watch(() => props.nodeData?.error_strategy, (newVal) => {
  errorStrategy.value = newVal || 'none'
})

watch(() => props.nodeData?.default_value, (newVal) => {
  defaultValues.value = Array.isArray(newVal) ? newVal : []
}, { deep: true })

const handleStrategyChange = (val) => {
  errorStrategy.value = val
  emit('update:errorStrategy', val)
}

const handleDefaultValueChange = (key, value) => {
  emit('update:defaultValue', { key, value })
}
</script>

<style scoped>
.error-handle-section {
  padding: 12px 0;
  border-bottom: 1px solid #f2f4f7;
}

.error-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 4px;
}

.header-title {
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

.strategy-select {
  width: 170px;
}

.strategy-desc {
  padding: 6px 10px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px dashed #e2e8f0;
}

.desc-text {
  font-size: 11px;
  line-height: 1.4;
}

.desc-text.text-gray { color: #64748b; }
.desc-text.text-blue { color: #1d4ed8; }
.desc-text.text-amber { color: #b45309; }

.default-val-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.section-sub-title {
  font-size: 11px;
  font-weight: 600;
  color: #475569;
}

.default-val-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #f1f5f9;
}

.default-val-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.val-key {
  font-size: 11px;
  font-weight: 600;
  color: #334155;
  width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-tip {
  font-size: 11px;
  color: #94a3b8;
  font-style: italic;
  text-align: center;
}

.mt-2 {
  margin-top: 8px;
}
</style>
