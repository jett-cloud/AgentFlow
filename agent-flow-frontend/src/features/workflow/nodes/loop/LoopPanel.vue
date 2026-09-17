<template>
  <div class="loop-panel">
    <div class="panel-header">
      <div class="header-left">
        <BlockIcon type="loop" :size="20" />
        <input v-model="nodeTitle" class="title-input" placeholder="循环 (Loop)" aria-label="循环节点标题" :disabled="readOnly" />
      </div>
      <button type="button" class="close-btn" aria-label="关闭循环配置面板" @click="$emit('close')"><el-icon><Close /></el-icon></button>
    </div>

    <div class="panel-body">
      <div class="form-section">
        <div class="flex items-center justify-between">
          <label class="section-label">最大循环上限次数</label>
          <span class="font-mono text-purple-600 font-bold text-xs">{{ maxIterations }}</span>
        </div>
        <el-input-number v-model="maxIterations" :min="1" :max="100" :step="1" step-strictly :disabled="readOnly" aria-label="最大循环上限次数" />
      </div>

      <div class="form-section">
        <div class="section-row">
          <label class="section-label">循环变量</label>
          <button type="button" aria-label="添加循环变量" :disabled="readOnly" @click="addLoopVariable">+ 添加</button>
        </div>
        <div v-for="(variable, index) in loopVariables" :key="variable.id" class="config-card">
          <el-input :model-value="variable.label" placeholder="变量名" :disabled="readOnly" :aria-label="`循环变量 ${variableName(variable, index)} 的名称`" @update:model-value="updateLoopVariable(index, { label: $event })" />
          <el-select :model-value="variable.var_type" placeholder="变量类型" :disabled="readOnly" :aria-label="`循环变量 ${variableName(variable, index)} 的类型`" @change="changeVariableType(index, $event)">
            <el-option v-for="type in LOOP_VARIABLE_TYPES" :key="type" :label="type" :value="type" />
          </el-select>
          <el-select :model-value="variable.value_type" :disabled="readOnly" :aria-label="`循环变量 ${variableName(variable, index)} 的值来源`" @change="changeVariableValueType(index, $event)">
            <el-option label="常量" value="constant" /><el-option label="引用变量" value="variable" />
          </el-select>
          <VarReferencePicker
            v-if="variable.value_type === 'variable'"
            :model-value="variable.value"
            :node-id="nodeId"
            :read-only="readOnly"
            :filter-var="sourceFilter(variable.var_type)"
            :aria-label="`循环变量 ${variableName(variable, index)} 的来源`"
            placeholder="选择同类型变量"
            @change="(selector, meta) => changeLoopVariableSource(index, selector, meta)"
          />
          <el-input-number v-else-if="variable.var_type === 'number'" :model-value="variable.value" :disabled="readOnly" :aria-label="`循环变量 ${variableName(variable, index)} 的初始值`" @update:model-value="updateLoopConstant(index, $event)" />
          <el-switch v-else-if="variable.var_type === 'boolean'" :model-value="variable.value" :disabled="readOnly" :aria-label="`循环变量 ${variableName(variable, index)} 的初始值`" @update:model-value="updateLoopConstant(index, $event)" />
          <div v-else-if="isJsonType(variable.var_type)" class="json-editor">
            <el-input :model-value="jsonDraft(variable)" type="textarea" :rows="3" :disabled="readOnly" :aria-label="`循环变量 ${variableName(variable, index)} 的初始值`" @update:model-value="updateVariableJson(index, variable, $event)" />
            <span v-if="jsonErrors[variable.id]" class="field-error">{{ jsonErrors[variable.id] }}</span>
          </div>
          <el-input v-else :model-value="variable.value" placeholder="初始值" :disabled="readOnly" :aria-label="`循环变量 ${variableName(variable, index)} 的初始值`" @update:model-value="updateLoopConstant(index, $event)" />
          <button type="button" :aria-label="`删除循环变量 ${variable.label || index + 1}`" :disabled="readOnly" @click="removeLoopVariable(index)">删除</button>
        </div>
      </div>

      <div class="form-section">
        <div class="section-row">
          <label class="section-label">退出条件</label>
          <el-select v-model="logicalOperator" size="small" :disabled="readOnly" aria-label="退出条件逻辑"><el-option label="AND" value="and" /><el-option label="OR" value="or" /></el-select>
          <button type="button" aria-label="添加退出条件" :disabled="readOnly" @click="addBreakCondition">+ 添加</button>
        </div>
        <div v-for="(condition, index) in breakConditions" :key="condition.id" class="config-card">
          <VarReferencePicker
            :model-value="condition.variable_selector"
            :node-id="nodeId"
            :read-only="readOnly"
            :aria-label="`退出条件 ${index + 1} 的变量`"
            placeholder="选择变量"
            @change="(selector, meta) => changeBreakConditionSource(index, selector, meta)"
          />
          <span class="derived-type">{{ condition.varType || 'string' }}</span>
          <el-select :model-value="condition.comparison_operator" placeholder="选择操作符" :disabled="readOnly" :aria-label="`退出条件 ${index + 1} 的运算符`" @change="updateBreakCondition(index, { comparison_operator: $event })">
            <el-option v-for="operator in getLoopOperators(condition.varType)" :key="operator" :label="operator" :value="operator" />
          </el-select>
          <template v-if="!isValuelessLoopOperator(condition.comparison_operator)">
            <el-input-number v-if="condition.varType === 'number'" :model-value="condition.value" :disabled="readOnly" :aria-label="`退出条件 ${index + 1} 的比较值`" @update:model-value="updateBreakCondition(index, { value: $event })" />
            <el-switch v-else-if="condition.varType === 'boolean'" :model-value="condition.value" :disabled="readOnly" :aria-label="`退出条件 ${index + 1} 的比较值`" @update:model-value="updateBreakCondition(index, { value: $event })" />
            <el-input v-else :model-value="condition.value" placeholder="比较值" :disabled="readOnly" :aria-label="`退出条件 ${index + 1} 的比较值`" @update:model-value="updateBreakCondition(index, { value: $event })" />
          </template>
          <button type="button" :aria-label="`删除退出条件 ${index + 1}`" :disabled="readOnly" @click="removeBreakCondition(index)">删除</button>
        </div>
      </div>

      <div class="form-section">
        <label class="section-label">输出变量</label>
        <div v-for="variable in loopVariables" :key="`out-${variable.id}`" class="var-tag">
          <span class="var-name">{{ variable.label || '(unnamed)' }}</span>
          <span class="var-type">{{ variable.var_type }}</span>
        </div>
      </div>

      <NextStep :node-id="nodeId" :node-data="nodeData" :read-only="readOnly" />
    </div>
  </div>
</template>

<script setup>
import { computed, reactive } from 'vue'
import { Close } from '@element-plus/icons-vue'
import BlockIcon from '../base/BlockIcon.vue'
import NextStep from '../shared/NextStep.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import { useLoopConfig } from './useLoopConfig.js'
import {
  LOOP_VARIABLE_TYPES,
  getLoopOperators,
  isLoopVariableSource,
  isValuelessLoopOperator,
} from './loopNode.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:nodeData'])

const {
  readOnly,
  maxIterations,
  loopVariables,
  breakConditions,
  logicalOperator,
  addLoopVariable,
  updateLoopVariable,
  updateLoopVariableType,
  updateLoopVariableValueType,
  updateLoopConstant,
  changeLoopVariableSource,
  removeLoopVariable,
  addBreakCondition,
  updateBreakCondition,
  changeBreakConditionSource,
  removeBreakCondition,
} = useLoopConfig(props, emit)
const jsonDrafts = reactive({})
const jsonErrors = reactive({})

const nodeTitle = computed({
  get: () => props.nodeData?.title || '循环',
  set: val => emit('update:nodeData', { ...props.nodeData, title: val }),
})

const isJsonType = type => type === 'object' || type?.startsWith('array')
const sourceFilter = varType => variable => isLoopVariableSource(variable, varType)
const variableName = (variable, index) => variable.label || index + 1

function jsonDraft(variable) {
  return jsonDrafts[variable.id] ?? JSON.stringify(variable.value, null, 2)
}

function changeVariableType(index, type) {
  const id = loopVariables.value[index]?.id
  delete jsonDrafts[id]
  delete jsonErrors[id]
  updateLoopVariableType(index, type)
}

function changeVariableValueType(index, type) {
  const id = loopVariables.value[index]?.id
  delete jsonDrafts[id]
  delete jsonErrors[id]
  updateLoopVariableValueType(index, type)
}

function updateVariableJson(index, variable, value) {
  jsonDrafts[variable.id] = value
  try {
    const parsed = JSON.parse(value)
    const expectsArray = variable.var_type?.startsWith('array')
    if ((expectsArray && !Array.isArray(parsed)) || (!expectsArray && (parsed == null || Array.isArray(parsed) || typeof parsed !== 'object')))
      throw new TypeError(expectsArray ? '必须输入 JSON 数组' : '必须输入 JSON 对象')
    jsonErrors[variable.id] = ''
    updateLoopConstant(index, parsed)
  }
  catch (error) {
    jsonErrors[variable.id] = error instanceof SyntaxError ? 'JSON 格式无效' : error.message
  }
}
</script>

<style scoped>
.loop-panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: #fff; border-left: 1px solid #eaecf0; }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid #f2f4f7; background: #fafafa; }
.header-left { display: flex; align-items: center; gap: 8px; flex: 1; }
.title-input { font-size: 14px; font-weight: 600; color: #101828; border: none; background: transparent; }
.close-btn, .section-row button, .config-card button { background: transparent; border: none; cursor: pointer; color: #155eef; }
.close-btn { color: #667085; }
.close-btn:focus-visible, .section-row button:focus-visible, .config-card button:focus-visible {
  outline: 2px solid #155eef;
  outline-offset: 2px;
}
.panel-body { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.form-section { display: flex; flex-direction: column; gap: 8px; }
.section-label { font-size: 12px; font-weight: 600; color: #344054; }
.section-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.config-card { display: grid; gap: 8px; padding: 10px; border: 1px solid #eaecf0; border-radius: 8px; }
.json-editor { display: flex; flex-direction: column; gap: 4px; }
.field-error { color: #d92d20; font-size: 10px; }
.derived-type, .var-type { font-size: 10px; color: #98a2b3; }
.var-tag { display: flex; gap: 8px; align-items: center; }
.var-name { font-family: ui-monospace, monospace; font-size: 12px; color: #155eef; }
</style>
