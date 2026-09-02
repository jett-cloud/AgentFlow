<!-- src/views/copilot/components/workflow/panel/iteration/IterationPanel.vue -->
<template>
  <div class="iter-panel">
    <!-- Header 头部 -->
    <div class="panel-header">
      <div class="header-left">
        <BlockIcon type="iteration" :size="20" />
        <input v-model="nodeTitle" class="title-input" placeholder="迭代 (Iteration)" :disabled="readOnly" />
      </div>
      <button class="close-btn" @click="$emit('close')"><el-icon><Close /></el-icon></button>
    </div>

    <!-- Body 面板主体 -->
    <div class="panel-body">
      <!-- 1. 迭代输入数组 -->
      <div class="form-section">
        <div class="section-header">
          <label class="section-label">迭代输入数组 (INPUT ARRAY)</label>
        </div>
        <el-input 
          :model-value="formatSelectorStr(iteratorSelector)" 
          placeholder="选择或输入数组路径 (如: sys.files 或 start.items)" 
          size="small" 
          :disabled="readOnly"
          @input="(val) => iteratorSelector = val"
        />
        <span class="tip-text">节点将针对该数组中的每一个元素依次进行循环迭代处理。</span>
      </div>

      <!-- 2. 并行控制 (Parallel Execution) -->
      <div class="form-section">
        <div class="section-header">
          <label class="section-label">并行执行 (PARALLEL EXECUTION)</label>
          <el-switch v-model="isParallel" size="small" :disabled="readOnly" />
        </div>
        <div v-if="isParallel" class="parallel-config-box">
          <span class="parallel-text">最大并发数 (1 ~ 10):</span>
          <el-input-number 
            v-model="parallelNums" 
            :min="1" 
            :max="10" 
            size="small" 
            :disabled="readOnly" 
            style="width: 100px;"
          />
        </div>
        <span class="tip-text">开启并行后将同时并发处理多个数组元素，提升运行速度。</span>
      </div>

      <!-- 3. 错误响应策略 (Error Strategy) -->
      <div class="form-section">
        <label class="section-label">容错处理策略 (ERROR STRATEGY)</label>
        <el-select v-model="errorStrategy" size="small" class="w-full" :disabled="readOnly">
          <el-option label="终止运行 (遇错即停止)" value="terminated" />
          <el-option label="继续运行 (保留异常结果)" value="continue-on-error" />
          <el-option label="过滤异常 (仅输出正常结果)" value="remove-abnormal-output" />
        </el-select>
      </div>

      <!-- 4. 节点输出变量 (Output Vars) -->
      <div class="form-section output-vars-section">
        <label class="section-label">输出变量 (OUTPUT VARIABLES)</label>
        <div class="var-tag">
          <span class="var-name">result</span> 
          <span class="var-type">Array[Object/String]</span>
        </div>
        <span class="tip-text">整个迭代循环完成后生成的聚合结果数组。</span>
      </div>

      <!-- 5. 下游串联提示 -->
      <NextStep :node-id="nodeId" :node-data="nodeData" :read-only="readOnly" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Close } from '@element-plus/icons-vue'
import BlockIcon from '../base/BlockIcon.vue'
import NextStep from '../shared/NextStep.vue'
import { useIterationConfig } from './useIterationConfig.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false }
})

const emit = defineEmits(['close', 'update:nodeData'])

const { 
  readOnly, 
  iteratorSelector, 
  isParallel, 
  parallelNums, 
  errorStrategy 
} = useIterationConfig(props, (event, val) => {
  emit(event, val)
})

const nodeTitle = computed({
  get: () => props.nodeData?.title || '迭代',
  set: (val) => emit('update:nodeData', { ...props.nodeData, title: val })
})

const formatSelectorStr = (sel) => {
  if (!sel) return ''
  if (Array.isArray(sel)) return sel.join('.')
  return String(sel)
}
</script>

<style scoped>
.iter-panel { 
  display: flex; 
  flex-direction: column; 
  height: 100%; 
  overflow: hidden; 
  background: #fff; 
  border-left: 1px solid #eaecf0; 
}

.panel-header { 
  display: flex; 
  align-items: center; 
  justify-content: space-between; 
  padding: 12px 16px; 
  border-bottom: 1px solid #f2f4f7; 
  background: #fafafa; 
}
.header-left { display: flex; align-items: center; gap: 8px; flex: 1; }
.title-input { font-size: 14px; font-weight: 600; color: #101828; border: none; background: transparent; }
.close-btn { background: transparent; border: none; cursor: pointer; color: #667085; }

.panel-body { 
  flex: 1; 
  overflow-y: auto; 
  padding: 16px; 
  display: flex; 
  flex-direction: column; 
  gap: 20px; 
}

.form-section { display: flex; flex-direction: column; gap: 8px; }
.section-header { display: flex; align-items: center; justify-content: space-between; }
.section-label { font-size: 11px; font-weight: 700; color: #64748b; letter-spacing: 0.5px; }
.tip-text { font-size: 11px; color: #98a2b3; }

.parallel-config-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f8fafc;
  padding: 8px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}
.parallel-text { font-size: 12px; color: #344054; }

.output-vars-section {
  background: #f8fafc;
  border-radius: 8px;
  padding: 10px;
  border: 1px solid #f1f5f9;
}

.var-tag {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  font-family: ui-monospace, monospace;
  background: #ffffff;
  padding: 6px 10px;
  border-radius: 4px;
  border: 1px solid #e2e8f0;
}
.var-name { color: #0f172a; font-weight: 600; }
.var-type { color: #64748b; font-size: 10px; }
</style>
