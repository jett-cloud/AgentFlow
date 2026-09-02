<!-- src/views/copilot/components/workflow/panel/loop/LoopPanel.vue -->
<template>
  <div class="loop-panel">
    <div class="panel-header">
      <div class="header-left">
        <BlockIcon type="loop" :size="20" />
        <input v-model="nodeTitle" class="title-input" placeholder="循环 (Loop)" :disabled="readOnly" />
      </div>
      <button class="close-btn" @click="$emit('close')"><el-icon><Close /></el-icon></button>
    </div>

    <div class="panel-body">
      <div class="form-section">
        <div class="flex items-center justify-between">
          <label class="section-label">最大循环上限次数</label>
          <span class="font-mono text-purple-600 font-bold text-xs">{{ maxIterations }}</span>
        </div>
        <el-slider v-model="maxIterations" :min="1" :max="100" :disabled="readOnly" />
      </div>

      <div class="form-section">
        <div class="section-row"><label class="section-label">循环变量</label><button type="button" :disabled="readOnly" @click="addLoopVariable">+ 添加</button></div>
        <div v-for="(variable, index) in loopVariables" :key="variable.id" class="config-card">
          <el-input :model-value="variable.label" placeholder="变量名" :disabled="readOnly" @update:model-value="updateLoopVariable(index, { label: $event })" />
          <el-select :model-value="variable.value_type" :disabled="readOnly" @change="updateLoopVariable(index, { value_type: $event, value: $event === 'variable' ? [] : '' })">
            <el-option label="常量" value="constant" /><el-option label="引用变量" value="variable" />
          </el-select>
          <VarReferencePicker v-if="variable.value_type === 'variable'" :model-value="variable.value" :node-id="nodeId" :read-only="readOnly" @update:model-value="updateLoopVariable(index, { value: $event })" />
          <el-input v-else :model-value="variable.value" placeholder="初始值" :disabled="readOnly" @update:model-value="updateLoopVariable(index, { value: $event })" />
          <button type="button" :disabled="readOnly" @click="removeLoopVariable(index)">删除</button>
        </div>
      </div>

      <div class="form-section">
        <div class="section-row">
          <label class="section-label">退出条件</label>
          <el-select v-model="logicalOperator" size="small" :disabled="readOnly"><el-option label="AND" value="and" /><el-option label="OR" value="or" /></el-select>
          <button type="button" :disabled="readOnly" @click="addBreakCondition">+ 添加</button>
        </div>
        <div v-for="(condition, index) in breakConditions" :key="condition.id" class="config-card">
          <VarReferencePicker :model-value="condition.variable_selector" :node-id="nodeId" :read-only="readOnly" placeholder="选择变量" @update:model-value="updateBreakCondition(index, { variable_selector: $event })" />
          <el-select :model-value="condition.comparison_operator" placeholder="选择操作符" :disabled="readOnly" @change="updateBreakCondition(index, { comparison_operator: $event })">
            <el-option label="等于" value="=" /><el-option label="不等于" value="≠" /><el-option label="大于" value=">" /><el-option label="小于" value="<" /><el-option label="为空" value="empty" /><el-option label="不为空" value="not empty" />
          </el-select>
          <el-input v-if="!['empty', 'not empty'].includes(condition.comparison_operator)" :model-value="condition.value" placeholder="比较值" :disabled="readOnly" @update:model-value="updateBreakCondition(index, { value: $event })" />
          <button type="button" :disabled="readOnly" @click="removeBreakCondition(index)">删除</button>
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
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import { useLoopConfig } from './useLoopConfig.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false }
})
const emit = defineEmits(['close', 'update:nodeData'])

const { readOnly, maxIterations, loopVariables, breakConditions, logicalOperator, addLoopVariable, updateLoopVariable, removeLoopVariable, addBreakCondition, updateBreakCondition, removeBreakCondition } = useLoopConfig(props, emit)

const nodeTitle = computed({
  get: () => props.nodeData?.title || '循环',
  set: (val) => emit('update:nodeData', { ...props.nodeData, title: val })
})
</script>

<style scoped>
.loop-panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: #fff; border-left: 1px solid #eaecf0; }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid #f2f4f7; background: #fafafa; }
.header-left { display: flex; align-items: center; gap: 8px; flex: 1; }
.title-input { font-size: 14px; font-weight: 600; color: #101828; border: none; background: transparent; }
.close-btn { background: transparent; border: none; cursor: pointer; color: #667085; }
.panel-body { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.form-section { display: flex; flex-direction: column; gap: 8px; }
.section-label { font-size: 12px; font-weight: 600; color: #344054; }
.section-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.section-row button, .config-card button { border: 0; background: transparent; color: #155eef; cursor: pointer; }
.config-card { display: grid; gap: 8px; padding: 10px; border: 1px solid #eaecf0; border-radius: 8px; }
</style>
