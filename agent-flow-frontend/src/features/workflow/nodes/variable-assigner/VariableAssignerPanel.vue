<!-- src/views/copilot/components/workflow/panel/variable-assigner/VariableAssignerPanel.vue -->
<template>
  <div class="va-panel">
    <div class="panel-header">
      <div class="header-left">
        <BlockIcon type="assigner" :size="20" />
        <input v-model="nodeTitle" class="title-input" placeholder="变量赋值器" :disabled="readOnly" />
      </div>
      <button class="close-btn" @click="$emit('close')"><el-icon><Close /></el-icon></button>
    </div>

    <div class="panel-body">
      <div class="form-section">
        <div class="section-header-flex">
          <label class="section-label">赋值规则 (Assignments)</label>
          <button v-if="!readOnly" class="add-btn" @click="openAddRule"><el-icon><Plus /></el-icon></button>
        </div>

        <div class="items-list">
          <div v-for="(it, idx) in items" :key="idx" class="item-card">
            <span class="assignment-target" :title="formatTarget(it)">{{ formatTarget(it) }}</span>
            <span class="assignment-arrow" aria-hidden="true">←</span>
            <span class="assignment-source" :title="formatSource(it)">{{ formatSource(it) }}</span>
            <button
              v-if="!readOnly"
              class="del-btn"
              :aria-label="`删除赋值规则：${formatTarget(it)}`"
              @click="handleRemoveItem(idx)"
            >
              <el-icon><Delete /></el-icon>
            </button>
          </div>
        </div>
      </div>

      <NextStep :node-id="nodeId" :node-data="nodeData" :read-only="readOnly" />
    </div>

    <el-dialog v-model="modalVisible" title="添加赋值规则" width="380px" append-to-body class="workflow-dialog">
      <el-form label-position="top" size="small">
        <el-form-item label="目标对话变量" required>
          <el-select
            v-model="targetVariableName"
            class="full-width"
            placeholder="选择要写入的对话变量"
            no-data-text="暂无对话变量"
          >
            <el-option
              v-for="variable in conversationVariables"
              :key="variable.id || variable.name"
              :label="`conversation.${variable.name}`"
              :value="variable.name"
            />
          </el-select>
          <p v-if="!conversationVariables.length" class="form-tip">
            暂无对话变量，请先在画布的变量面板中创建。
          </p>
        </el-form-item>
        <el-form-item label="写入值" required>
          <VarReferencePicker
            v-model="form.sourceSelector"
            :node-id="nodeId"
            placeholder="选择上游节点输出变量"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="modalVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, Plus, Delete } from '@element-plus/icons-vue'
import { useWorkflowStore } from '../../state/useWorkflowStore.js'
import { formatValueSelector } from '../../model/variableOutputs.js'
import BlockIcon from '../base/BlockIcon.vue'
import NextStep from '../shared/NextStep.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import { useVariableAssignerConfig } from './useVariableAssignerConfig.js'
import {
  createVariableAssignment,
  getAssignmentSourceSelector,
  getAssignmentTargetSelector,
} from './variableAssigner.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false }
})
const emit = defineEmits(['close', 'update:nodeData'])

const { readOnly, items, handleAddItem, handleRemoveItem } = useVariableAssignerConfig(props, emit)
const workflowStore = useWorkflowStore()
const conversationVariables = computed(() => workflowStore.conversationVariables || [])

const nodeTitle = computed({
  get: () => props.nodeData?.title || '变量赋值器',
  set: (val) => emit('update:nodeData', { ...props.nodeData, title: val })
})

const modalVisible = ref(false)
const form = ref({ targetSelector: [], sourceSelector: [] })
const targetVariableName = computed({
  get: () => form.value.targetSelector?.[1] || '',
  set: name => { form.value.targetSelector = name ? ['conversation', name] : [] },
})

const formatTarget = item => formatValueSelector(getAssignmentTargetSelector(item))
const formatSource = item => formatValueSelector(getAssignmentSourceSelector(item))

const openAddRule = () => {
  form.value = { targetSelector: [], sourceSelector: [] }
  modalVisible.value = true
}

const saveRule = () => {
  if (!form.value.targetSelector.length) {
    ElMessage.warning('请选择目标对话变量')
    return
  }
  if (!form.value.sourceSelector.length) {
    ElMessage.warning('请选择上游变量')
    return
  }

  handleAddItem(createVariableAssignment(form.value.targetSelector, form.value.sourceSelector))
  modalVisible.value = false
}
</script>

<style scoped>
.va-panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: #fff; border-left: 1px solid #eaecf0; }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid #f2f4f7; background: #fafafa; }
.header-left { display: flex; align-items: center; gap: 8px; flex: 1; }
.title-input { font-size: 14px; font-weight: 600; color: #101828; border: none; background: transparent; }
.close-btn { background: transparent; border: none; cursor: pointer; color: #667085; }
.panel-body { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.form-section { display: flex; flex-direction: column; gap: 8px; }
.section-label { font-size: 12px; font-weight: 600; color: #344054; }
.section-header-flex { display: flex; align-items: center; justify-content: space-between; }
.add-btn { background: transparent; border: none; cursor: pointer; color: #667085; }
.items-list { display: flex; flex-direction: column; gap: 6px; }
.item-card { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 2px 6px; background: #f8fafc; border: 1px solid #f1f5f9; padding: 6px 8px; border-radius: 6px; }
.assignment-target,
.assignment-source { min-width: 0; overflow: hidden; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.assignment-target { grid-column: 1 / 3; color: #0284c7; font-weight: 700; }
.assignment-arrow { grid-column: 1; grid-row: 2; color: #98a2b3; font-size: 12px; }
.assignment-source { grid-column: 2; grid-row: 2; color: #667085; }
.del-btn { grid-column: 3; grid-row: 1 / 3; background: transparent; border: none; cursor: pointer; color: #98a2b3; }
.del-btn:hover { color: #f04438; }
.del-btn:focus-visible { outline: 2px solid #175cd3; outline-offset: 2px; }
.full-width { width: 100%; }
.form-tip { margin: 6px 0 0; color: #98a2b3; font-size: 11px; line-height: 1.4; }
</style>
