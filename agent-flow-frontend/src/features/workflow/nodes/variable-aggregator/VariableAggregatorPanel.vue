<!-- src/views/copilot/components/workflow/panel/variable-aggregator/VariableAggregatorPanel.vue -->
<template>
  <div class="vag-panel">
    <div class="panel-header">
      <div class="header-left">
        <BlockIcon type="variable-assigner" :size="20" />
        <input v-model="nodeTitle" class="title-input" placeholder="变量聚合器" :disabled="readOnly" />
      </div>
      <button class="close-btn" @click="$emit('close')"><el-icon><Close /></el-icon></button>
    </div>

    <div class="panel-body">
      <div class="form-section">
        <label class="section-label">聚合目标数据类型</label>
        <el-select v-model="outputType" size="small" class="w-full" :disabled="readOnly">
          <el-option label="Any (自动)" value="any" />
          <el-option label="String (字符串)" value="string" />
          <el-option label="Array (数组)" value="array" />
          <el-option label="Object (对象)" value="object" />
        </el-select>
      </div>

      <div class="form-section">
        <label class="section-label">聚合的变量来源分支</label>
        <div class="vars-list">
          <div v-for="(v, idx) in variables" :key="idx" class="v-card font-mono text-xs text-purple-700">
            {{ Array.isArray(v) ? v.join('.') : v }}
          </div>
        </div>
      </div>

      <NextStep :node-id="nodeId" :node-data="nodeData" :read-only="readOnly" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Close } from '@element-plus/icons-vue'
import BlockIcon from '../base/BlockIcon.vue'
import NextStep from '../shared/NextStep.vue'
import { useVariableAggregatorConfig } from './useVariableAggregatorConfig.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false }
})
const emit = defineEmits(['close', 'update:nodeData'])

const { readOnly, variables, outputType } = useVariableAggregatorConfig(props, emit)

const nodeTitle = computed({
  get: () => props.nodeData?.title || '变量聚合器',
  set: (val) => emit('update:nodeData', { ...props.nodeData, title: val })
})
</script>

<style scoped>
.vag-panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: #fff; border-left: 1px solid #eaecf0; }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid #f2f4f7; background: #fafafa; }
.header-left { display: flex; align-items: center; gap: 8px; flex: 1; }
.title-input { font-size: 14px; font-weight: 600; color: #101828; border: none; background: transparent; }
.close-btn { background: transparent; border: none; cursor: pointer; color: #667085; }
.panel-body { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.form-section { display: flex; flex-direction: column; gap: 8px; }
.section-label { font-size: 12px; font-weight: 600; color: #344054; }
.vars-list { display: flex; flex-direction: column; gap: 6px; }
.v-card { background: #faf5ff; border: 1px solid #f3e8ff; padding: 4px 8px; border-radius: 6px; }
</style>
