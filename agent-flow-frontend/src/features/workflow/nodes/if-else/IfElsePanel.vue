<!-- src/views/copilot/components/workflow/panel/if-else/IfElsePanel.vue -->
<!--
  IF/ELSE 条件分支节点面板组件
  放置于右侧抽屉面板，提供可视化的多分支条件组配置、运算符切换与 ELIF 分支管理。
-->
<template>
  <div class="ifelse-panel">
    <!-- 1. Panel 顶部 Header -->
    <div class="panel-header">
      <div class="header-left">
        <BlockIcon type="if-else" :size="20" />
        <input 
          v-model="nodeTitle" 
          class="title-input" 
          placeholder="IF/ELSE"
          :disabled="readOnly"
          @change="notifyChange"
        />
      </div>
      <button class="close-btn" @click="$emit('close')" aria-label="关闭面板">
        <el-icon><Close /></el-icon>
      </button>
    </div>

    <!-- 2. Panel 滚动表单主体 -->
    <div class="panel-body">
      <!-- 条件组集合 (Cases) 循环渲染 -->
      <div 
        v-for="(caseItem, cIdx) in cases" 
        :key="caseItem.case_id || cIdx"
        class="case-card"
      >
        <!-- 每一个 Case 的头部栏 (分支名称, 逻辑与/或逻辑关系切换, 删除分支按钮) -->
        <div class="case-card-header">
          <div class="flex items-center gap-2">
            <span class="case-badge">{{ cIdx === 0 ? 'IF' : `ELIF ${cIdx}` }}</span>
            <!-- 逻辑运算符 (AND / OR) -->
            <el-radio-group 
              v-model="caseItem.logical_operator" 
              size="small"
              :disabled="readOnly"
              @change="(val) => handleUpdateLogicalOperator(cIdx, val)"
            >
              <el-radio-button label="and">AND (且)</el-radio-button>
              <el-radio-button label="or">OR (或)</el-radio-button>
            </el-radio-group>
          </div>

          <div class="flex items-center gap-1">
            <!-- 添加子条件规则按钮 -->
            <button 
              v-if="!readOnly" 
              type="button" 
              class="icon-action-btn" 
              title="添加条件规则"
              @click="handleAddCondition(cIdx)"
            >
              <el-icon><Plus /></el-icon>
            </button>
            <!-- 删除 ELIF 分支按钮 (主 IF 分支不可删除) -->
            <button 
              v-if="!readOnly && cIdx > 0" 
              type="button" 
              class="icon-action-btn danger" 
              title="删除此分支"
              @click="handleRemoveElifCase(cIdx)"
            >
              <el-icon><Delete /></el-icon>
            </button>
          </div>
        </div>

        <!-- 条件组内部的条件表达式规则列表 -->
        <div class="conditions-list">
          <div 
            v-for="(cond, condIdx) in caseItem.conditions" 
            :key="condIdx"
            class="condition-row-card"
          >
            <!-- (1) 变量输入路径 (Variable Selector) -->
            <div class="form-row">
              <span class="row-label">变量</span>
              <VarReferencePicker
                :model-value="cond.variable_selector"
                :node-id="nodeId"
                :read-only="readOnly"
                placeholder="选择上游变量"
                @update:model-value="handleSelectVariable(cIdx, condIdx, $event)"
              />
            </div>

            <!-- (2) 比较运算符与值行 (Operator & Value) -->
            <div class="form-row-flex">
              <el-select 
                :model-value="cond.comparison_operator" 
                placeholder="比较运算符" 
                size="small"
                class="op-select"
                :disabled="readOnly"
                @change="(val) => handleUpdateCondition(cIdx, condIdx, 'comparison_operator', val)"
              >
                <el-option 
                  v-for="op in operatorsForCondition(cond)" 
                  :key="op.value" 
                  :label="op.name" 
                  :value="op.value" 
                />
              </el-select>

              <!-- 如果该比较符需要填比较值，展示值输入框 -->
              <el-input 
                v-if="checkNeedValue(cond.comparison_operator)" 
                :model-value="cond.value" 
                placeholder="比较目标值" 
                size="small"
                class="val-input"
                :disabled="readOnly"
                @input="(val) => handleUpdateCondition(cIdx, condIdx, 'value', val)"
              />

              <!-- 删除此规则按钮 -->
              <button 
                v-if="!readOnly && caseItem.conditions.length > 1" 
                type="button" 
                class="remove-cond-btn" 
                title="删除条件"
                @click="handleRemoveCondition(cIdx, condIdx)"
              >
                <el-icon><Delete /></el-icon>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- ELSE 兜底分支展示说明 -->
      <div class="else-card">
        <div class="case-badge else-badge">ELSE</div>
        <span class="else-desc">当以上所有 IF / ELIF 条件均不满足时，执行此分支</span>
      </div>

      <!-- 快捷添加 ELIF 分支按钮 -->
      <button 
        v-if="!readOnly" 
        type="button" 
        class="add-elif-btn"
        @click="handleAddElifCase"
      >
        <el-icon><Plus /></el-icon> 添加 ELIF 分支
      </button>

      <!-- 下一步关联节点组件 -->
      <NextStep 
        :node-id="nodeId"
        :node-data="nodeData"
        :read-only="readOnly"
        @add-next-node="handleSelectNextNode"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, Plus, Delete } from '@element-plus/icons-vue'
import BlockIcon from '../base/BlockIcon.vue'
import NextStep from '../shared/NextStep.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import { useIfElseConfig } from './useIfElseConfig.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false }
})

const emit = defineEmits(['close', 'update:nodeData'])

const {
  readOnly,
  cases,
  handleUpdateLogicalOperator,
  handleAddCondition,
  handleRemoveCondition,
  handleUpdateCondition,
  handleSelectVariable,
  operatorsForCondition,
  handleAddElifCase,
  handleRemoveElifCase
} = useIfElseConfig(props, emit)

const nodeTitle = computed({
  get: () => props.nodeData?.title || 'IF/ELSE',
  set: (val) => {
    emit('update:nodeData', { ...props.nodeData, title: val })
  }
})

const notifyChange = () => {
  emit('update:nodeData', { ...props.nodeData })
}

// 判断比较运算符是否需要输入值
const checkNeedValue = (opValue) => {
  return !['empty', 'not empty', 'is null', 'is not null'].includes(opValue)
}

const handleSelectNextNode = () => {
  ElMessage.info('触发添加下一个节点操作')
}
</script>

<style scoped>
.ifelse-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-height: 100%;
  overflow: hidden;
  background: #ffffff;
  border-left: 1px solid #eaecf0;
}

.panel-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #f2f4f7;
  background-color: #fafafa;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}

.title-input {
  font-size: 14px;
  font-weight: 600;
  color: #101828;
  border: 1px solid transparent;
  border-radius: 4px;
  padding: 2px 6px;
  background: transparent;
  outline: none;
  width: 100%;
}

.title-input:hover:not(:disabled) {
  border-color: #d0d5dd;
  background: #fff;
}

.close-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #667085;
  padding: 4px;
  border-radius: 4px;
}

.close-btn:hover {
  background: #f2f4f7;
  color: #101828;
}

.panel-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.case-card {
  background: #fafafa;
  border: 1px solid #eaecf0;
  border-radius: 8px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.case-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.case-badge {
  font-size: 11px;
  font-weight: 700;
  color: #155eef;
  background: #eff4ff;
  border: 1px solid #d1e9ff;
  padding: 2px 6px;
  border-radius: 4px;
}

.icon-action-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #667085;
  padding: 2px 4px;
  border-radius: 4px;
}

.icon-action-btn:hover {
  background: #f2f4f7;
  color: #101828;
}

.icon-action-btn.danger:hover {
  background: #fef2f2;
  color: #f04438;
}

.conditions-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.condition-row-card {
  background: #ffffff;
  border: 1px solid #eaecf0;
  border-radius: 6px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.row-label {
  font-size: 11px;
  color: #475569;
  font-weight: 500;
  width: 32px;
}

.form-row-flex {
  display: flex;
  align-items: center;
  gap: 6px;
}

.op-select {
  flex: 1.2;
}

.val-input {
  flex: 1;
}

.remove-cond-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #98a2b3;
  padding: 2px;
}

.remove-cond-btn:hover {
  color: #f04438;
}

.else-card {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  padding: 8px 10px;
}

.else-badge {
  color: #475569;
  background: #f1f5f9;
  border-color: #e2e8f0;
}

.else-desc {
  font-size: 11px;
  color: #64748b;
}

.add-elif-btn {
  background: #ffffff;
  border: 1px dashed #d0d5dd;
  cursor: pointer;
  color: #344054;
  padding: 8px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: all 0.15s ease;
}

.add-elif-btn:hover {
  border-color: #155eef;
  color: #155eef;
  background: #f8fafc;
}
</style>
