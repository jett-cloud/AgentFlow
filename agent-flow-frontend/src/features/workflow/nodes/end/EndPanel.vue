<!-- src/views/copilot/components/workflow/panel/end/EndPanel.vue -->
<!--
  结束节点 (End Node) 面板组件
  放置于右侧抽屉，提供对工作流最终输出变量 (outputs) 的添加、修改、删除和变量选择器引用配置。
-->
<template>
  <div class="end-panel">
    <PanelHeader
      block-type="end"
      :title="nodeTitle"
      :description="nodeData.desc"
      :legacy-description="nodeData.description"
      placeholder="结束"
      :read-only="readOnly"
      @update:title="onTitleChange"
      @update:description="onDescriptionChange"
      @close="$emit('close')"
    />

    <!-- 2. Panel 动态滚动配置主体 -->
    <div class="panel-body">
      <!-- (1) 输出变量管理区域 -->
      <div class="form-section">
        <div class="section-header-flex">
          <label class="section-label">输出变量</label>
          <!-- 添加输出变量按钮 (仅非只读模式下展示) -->
          <button
            v-if="!readOnly"
            type="button"
            class="add-var-btn"
            title="添加输出变量"
            @click="openAddOutputDialog"
          >
            <el-icon><Plus /></el-icon>
          </button>
        </div>

        <!-- 输出变量列表项展示卡片 -->
        <div class="output-list">
          <div 
            v-for="(item, index) in outputs" 
            :key="item.variable + index"
            class="output-item-card"
          >
            <!-- 左侧：变量名与引用的上游节点路径 -->
            <div class="output-left-box">
              <svg class="var-icon-svg" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M4.5 3.5L3 8L4.5 12.5" stroke="#10B981" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M11.5 3.5L13 8L11.5 12.5" stroke="#10B981" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M9 5.5L7 10.5" stroke="#10B981" stroke-width="1.25" stroke-linecap="round"/>
              </svg>
              <span class="output-key" :title="item.variable">{{ item.variable }}</span>
              <span class="dot-separator">←</span>
              <span class="output-selector" :title="formatSelectorText(item.value_selector)">
                {{ formatSelectorText(item.value_selector) }}
              </span>
              <span v-if="item.value_type" class="output-type">{{ item.value_type }}</span>
            </div>

            <!-- 右侧：Hover 时操作按钮 (编辑、删除) -->
            <div v-if="!readOnly" class="action-btn-group">
              <button class="hover-icon-btn" title="编辑" @click="openEditOutputDialog(index)">
                <el-icon><Edit /></el-icon>
              </button>
              <button class="hover-icon-btn hover-danger" title="删除" @click="handleRemoveOutput(index)">
                <el-icon><Delete /></el-icon>
              </button>
            </div>
          </div>

          <!-- 列表为空时的占位提示 -->
          <div v-if="!outputs.length" class="empty-state">
            暂无输出变量，点击右上角 “+” 添加
          </div>
        </div>
      </div>

    </div>

    <!-- 3. 添加/编辑输出变量映射的高级 Dialog 弹框 -->
    <el-dialog 
      v-model="outputDialogVisible" 
      :title="isEditMode ? '编辑输出变量' : '添加输出变量'" 
      width="420px"
      append-to-body
      class="dify-var-modal workflow-dialog"
    >
      <el-form :model="outputForm" label-position="top" size="small">
        <!-- 变量 Key 输入 -->
        <el-form-item label="输出变量名 (Variable)" required>
          <el-input v-model="outputForm.variable" placeholder="例如: result, text, status" />
        </el-form-item>
        
        <el-form-item label="变量绑定 (Selector)" required>
          <VarReferencePicker
            v-model="outputForm.selector"
            :node-id="nodeId"
            placeholder="选择上游节点输出变量"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button size="small" @click="outputDialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="saveOutputForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Edit, Delete } from '@element-plus/icons-vue'
import PanelHeader from '../shared/PanelHeader.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import { useEndConfig } from './useEndConfig.js'
import { isValidEndOutputName } from './endNode.js'
import { formatValueSelector } from '../../model/variableOutputs.js'

// 接收父组件 (WorkflowCanvas / NodePanel) 传入的属性
const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false }
})

// 定义需要发出的事件 (如关闭面板、更新节点配置)
const emit = defineEmits(['close', 'update:nodeData'])

// 引入结束节点专用配置 logic hook
const {
  readOnly,
  outputs,
  handleAddOutput,
  handleRemoveOutput,
  handleUpdateOutput,
} = useEndConfig(props, emit)

// 节点标题双向绑定
const nodeTitle = computed({
  get: () => props.nodeData?.title || '结束',
  set: (val) => {
    emit('update:nodeData', { ...props.nodeData, title: val })
  }
})

// 变量添加/修改对话框状态控制
const outputDialogVisible = ref(false)
const isEditMode = ref(false)
const editingIndex = ref(-1)

// 对话框内部表单模型
function onTitleChange(val) {
  emit('update:nodeData', { ...props.nodeData, title: val })
}

function onDescriptionChange(val) {
  const { description: _legacyDescription, ...nodeData } = props.nodeData
  emit('update:nodeData', { ...nodeData, desc: val })
}

const outputForm = ref({
  variable: '',
  selector: [],
})

const formatSelectorText = formatValueSelector

const openAddOutputDialog = () => {
  isEditMode.value = false
  editingIndex.value = -1
  outputForm.value = { variable: '', selector: [] }
  outputDialogVisible.value = true
}

const openEditOutputDialog = (index) => {
  isEditMode.value = true
  editingIndex.value = index
  const item = outputs.value[index]
  outputForm.value = {
    variable: item.variable || '',
    selector: Array.isArray(item.value_selector) ? [...item.value_selector] : [],
  }
  outputDialogVisible.value = true
}

const saveOutputForm = () => {
  const varName = outputForm.value.variable.trim()
  const selector = outputForm.value.selector || []

  if (!varName) {
    ElMessage.warning('请输入输出变量名')
    return
  }
  if (!isValidEndOutputName(varName)) {
    ElMessage.warning('输出变量名只能包含字母、数字和下划线，且不能以数字开头')
    return
  }
  if (selector.length < 2) {
    ElMessage.warning('请选择上游变量')
    return
  }

  const payload = {
    variable: varName,
    value_selector: selector
  }

  const ok = isEditMode.value
    ? handleUpdateOutput(editingIndex.value, payload)
    : handleAddOutput(payload)
  if (ok)
    outputDialogVisible.value = false
  else
    ElMessage.warning('该变量名已存在')
}
</script>

<style scoped>
.end-panel {
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
  gap: 16px;
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-label {
  font-size: 12px;
  font-weight: 600;
  color: #344054;
}

.section-header-flex {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.add-var-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #667085;
  padding: 2px 4px;
  border-radius: 4px;
}

.add-var-btn:hover {
  background-color: #f2f4f7;
  color: #101828;
}

.output-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.output-item-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 34px;
  background: #f0fdf4;
  border: 1px solid #dcfce7;
  border-radius: 8px;
  padding: 0 10px;
  transition: all 0.15s ease;
}

.output-item-card:hover {
  border-color: #a7f3d0;
}

.output-left-box {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.var-icon-svg {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.output-key {
  font-size: 12px;
  font-weight: 600;
  color: #065f46;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dot-separator {
  font-size: 11px;
  color: #10b981;
}

.output-selector {
  font-size: 11px;
  color: #047857;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.output-type {
  flex-shrink: 0;
  border-radius: 4px;
  background: #ecfdf3;
  padding: 1px 4px;
  color: #027a48;
  font-size: 9px;
}

.action-btn-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.hover-icon-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 3px;
  border-radius: 4px;
  color: #667085;
  display: flex;
  align-items: center;
  justify-content: center;
}

.hover-icon-btn:hover {
  background-color: #e6f4ea;
  color: #10b981;
}

.hover-icon-btn.hover-danger:hover {
  background-color: #fef2f2;
  color: #f04438;
}

.empty-state {
  font-size: 12px;
  color: #98a2b3;
  text-align: center;
  padding: 16px;
  border: 1px dashed #eaecf0;
  border-radius: 8px;
  background: #fafafa;
}

.form-tip {
  font-size: 11px;
  color: #98a2b3;
  margin-top: 4px;
  display: block;
}
</style>
