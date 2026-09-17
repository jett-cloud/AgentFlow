<!-- src/views/copilot/components/workflow/panel/question-classifier/QuestionClassifierPanel.vue -->
<template>
  <div class="qc-panel">
    <PanelHeader
      block-type="question-classifier"
      :title="nodeTitle"
      :description="nodeData.desc"
      :legacy-description="nodeData.description"
      placeholder="问题分类器"
      :read-only="readOnly"
      @update:title="onTitleChange"
      @update:description="onDescriptionChange"
      @close="$emit('close')"
    />

    <div class="panel-body">
      <PanelSection label="输入变量 (Query)" required>
        <VarReferencePicker
          v-model="querySelector"
          :node-id="nodeId"
          placeholder="选择要分类的文本变量"
          :read-only="readOnly"
          :filter-var="isQuestionClassifierInput"
        />
      </PanelSection>

      <PanelSection label="模型 (Model)" required>
        <ModelSelector v-model="model" :read-only="readOnly" @change="onModelChange" />
      </PanelSection>

      <PanelSection label="分类类别定义 (Classes)">
        <template #extra>
          <button v-if="!readOnly" type="button" class="add-btn" @click="openAddClassModal">
            <el-icon><Plus /></el-icon>
          </button>
        </template>

        <div class="classes-list">
          <div v-for="(item, idx) in classes" :key="item.id" class="class-card">
            <el-input
              :model-value="item.name"
              size="small"
              placeholder="输入分类名称"
              :disabled="readOnly"
              @input="(val) => handleUpdateClassName(idx, val)"
            />
            <button
              v-if="!readOnly && classes.length > 2"
              type="button"
              class="del-btn"
              @click="handleRemoveClass(idx)"
            >
              <el-icon><Delete /></el-icon>
            </button>
          </div>
        </div>
      </PanelSection>

      <PanelSection label="输出变量" border-top>
        <OutputVarList node-type="question-classifier" />
      </PanelSection>

      <NextStep
        :node-id="nodeId"
        :node-data="nodeData"
        :read-only="readOnly"
        @add-next-node="handleSelectNextNode"
      />
    </div>

    <el-dialog v-model="addClassModalVisible" title="添加分类主题" width="380px" append-to-body class="workflow-dialog">
      <el-form label-position="top" size="small">
        <el-form-item label="分类名称" required>
          <el-input v-model="newClassName" placeholder="如: 技术支持, 售前咨询" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="addClassModalVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="saveNewClass">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Delete } from '@element-plus/icons-vue'
import PanelHeader from '../shared/PanelHeader.vue'
import PanelSection from '../shared/PanelSection.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import ModelSelector from '../shared/ModelSelector.vue'
import OutputVarList from '../shared/OutputVarList.vue'
import NextStep from '../shared/NextStep.vue'
import { useQuestionClassifierConfig } from './useQuestionClassifierConfig.js'
import { isQuestionClassifierInput, normalizeQuestionClassifierData } from './questionClassifierNode.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'update:nodeData'])

const {
  readOnly,
  classes,
  handleAddClass,
  handleRemoveClass,
  handleUpdateClassName,
} = useQuestionClassifierConfig(props, emit)

const nodeTitle = computed({
  get: () => props.nodeData?.title || '问题分类器',
  set: (val) => emit('update:nodeData', { ...props.nodeData, title: val }),
})

const querySelector = computed({
  get: () => props.nodeData?.query_variable_selector || [],
  set: (val) => emit('update:nodeData', { ...normalizeQuestionClassifierData(props.nodeData), query_variable_selector: val || [] }),
})

const model = computed({
  get: () => props.nodeData?.model || { provider: '', name: '', mode: 'chat', completion_params: {} },
  set: (val) => emit('update:nodeData', { ...props.nodeData, model: val }),
})

function onTitleChange(val) {
  emit('update:nodeData', { ...props.nodeData, title: val })
}

function onDescriptionChange(val) {
  const { description: _legacyDescription, ...nodeData } = props.nodeData
  emit('update:nodeData', { ...nodeData, desc: val })
}

function onModelChange(val) {
  emit('update:nodeData', { ...props.nodeData, model: val })
}

const addClassModalVisible = ref(false)
const newClassName = ref('')

function openAddClassModal() {
  newClassName.value = ''
  addClassModalVisible.value = true
}

function saveNewClass() {
  if (!newClassName.value.trim()) {
    ElMessage.warning('请输入分类名称')
    return
  }
  handleAddClass(newClassName.value.trim())
  addClassModalVisible.value = false
}

function handleSelectNextNode() {
  ElMessage.info('触发添加下一个节点操作')
}
</script>

<style scoped>
.qc-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: #fff;
  border-left: 1px solid #eaecf0;
}
.panel-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.classes-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.class-card {
  display: flex;
  align-items: center;
  gap: 8px;
}
.add-btn,
.del-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #667085;
  padding: 2px 4px;
  border-radius: 4px;
}
.add-btn:hover {
  background: #f2f4f7;
  color: #101828;
}
.del-btn:hover {
  color: #f04438;
}
</style>
