<!-- src/views/copilot/components/workflow/panel/code/CodePanel.vue -->
<!--
  Code 代码执行节点面板组件
  放置于右侧抽屉面板，提供语言切换 (Python3/JavaScript)、输入参数绑定、代码编辑器与输出类型结构管理。
-->
<template>
  <div class="code-panel">
    <PanelHeader
      block-type="code"
      :title="nodeTitle"
      :description="nodeData.desc"
      :legacy-description="nodeData.description"
      placeholder="代码执行"
      :read-only="readOnly"
      @update:title="onTitleChange"
      @update:description="onDescriptionChange"
      @close="$emit('close')"
    />

    <!-- 2. Panel 主体配置表单 -->
    <div class="panel-body">
      <!-- (1) 编程语言选择器 -->
      <div class="form-section">
        <label class="section-label">编程语言 (Language)</label>
        <el-select 
          v-model="codeLanguage" 
          class="w-full" 
          size="small"
          :disabled="readOnly"
        >
          <el-option label="Python 3" value="python3" />
          <el-option label="JavaScript (Node.js)" value="javascript" />
        </el-select>
      </div>

      <!-- (2) 输入变量管理 (Input Variables) -->
      <div class="form-section">
        <div class="section-header-flex">
          <label class="section-label">输入变量 (Input Variables)</label>
          <button 
            v-if="!readOnly" 
            type="button" 
            class="add-btn" 
            title="添加输入变量"
            @click="openAddInputModal"
          >
            <el-icon><Plus /></el-icon>
          </button>
        </div>

        <div class="input-vars-list">
          <div
            v-for="(item, index) in variables" 
            :key="index"
            class="var-card"
          >
            <div class="var-card-left">
              <el-input
                :model-value="item.variable"
                size="small"
                class="var-key-input"
                :disabled="readOnly"
                @change="(value) => updateInputName(index, value)"
              />
              <span class="arrow">←</span>
              <VarReferencePicker
                :model-value="item.value_selector"
                :node-id="nodeId"
                :read-only="readOnly"
                :filter-var="codeInputFilter"
                placeholder="选择上游变量"
                @update:model-value="(selector) => updateInputSelector(index, selector)"
              />
              <span class="var-type-badge">{{ item.value_type || 'string' }}</span>
            </div>
            <button 
              v-if="!readOnly" 
              type="button" 
              class="del-btn" 
              @click="handleRemoveInputVar(index)"
            >
              <el-icon><Delete /></el-icon>
            </button>
          </div>

          <div v-if="!variables.length" class="empty-tip">
            未配置输入变量，主函数参数需在此映射
          </div>
        </div>
      </div>

      <!-- (3) 代码编辑器 (Code Editor) -->
      <div class="form-section">
        <div class="section-header-flex">
          <label class="section-label">代码内容 (Code)</label>
          <button
            v-if="!readOnly"
            type="button"
            class="sync-btn"
            @click="handleSyncFunctionSignature"
          >
            同步函数签名
          </button>
        </div>

        <div class="editor-container">
          <el-input
            v-model="code"
            type="textarea"
            :rows="12"
            spellcheck="false"
            :disabled="readOnly"
            class="code-textarea font-mono"
            placeholder="// 请在此编写代码..."
          />
        </div>
      </div>

      <!-- (4) 输出变量结构管理 (Output Variables) -->
      <div class="form-section">
        <div class="section-header-flex">
          <label class="section-label">输出字段定义 (Output Variables)</label>
          <button 
            v-if="!readOnly" 
            type="button" 
            class="add-btn" 
            title="添加输出字段"
            @click="openAddOutputModal"
          >
            <el-icon><Plus /></el-icon>
          </button>
        </div>

        <div class="output-vars-list">
          <div 
            v-for="(outInfo, outName) in outputs" 
            :key="outName"
            class="output-card"
          >
            <el-input
              :model-value="outName"
              size="small"
              class="out-name-input"
              :disabled="readOnly"
              @change="(value) => renameOutput(outName, value)"
            />
            <el-select 
              :model-value="outInfo.type || 'string'" 
              size="small" 
              class="type-select"
              :disabled="readOnly"
              @change="(val) => handleUpdateOutputVarType(outName, val)"
            >
              <el-option 
                v-for="opt in OUTPUT_TYPE_OPTIONS" 
                :key="opt.value" 
                :label="opt.label" 
                :value="opt.value" 
              />
            </el-select>
            <button 
              v-if="!readOnly" 
              type="button" 
              class="del-btn" 
              @click="handleRemoveOutputVar(outName)"
            >
              <el-icon><Delete /></el-icon>
            </button>
          </div>
        </div>
      </div>

      <!-- (5) 失败重试配置 (Retry on Failure) -->
      <RetryConfig 
        :node-data="nodeData" 
        :read-only="readOnly" 
        @update:retry-config="handleRetryConfigUpdate"
      />

      <!-- (6) 异常处理策略 (Error Handling) -->
      <ErrorHandleConfig 
        :node-data="nodeData" 
        :read-only="readOnly" 
        @update:error-strategy="handleErrorStrategyUpdate"
        @update:default-value="handleDefaultValueUpdate"
      />

      <!-- 下一步节点关联组组件 -->
      <NextStep 
        :node-id="nodeId"
        :node-data="nodeData"
        :read-only="readOnly"
        @add-next-node="handleSelectNextNode"
      />
    </div>

    <!-- 3. 添加输入变量 Modal -->
    <el-dialog 
      v-model="inputModalVisible" 
      title="添加输入变量" 
      width="400px" 
      append-to-body
      class="workflow-dialog"
    >
      <el-form :model="inputForm" label-position="top" size="small">
        <el-form-item label="变量名称 (参数 Key)" required>
          <el-input v-model="inputForm.name" placeholder="例如: arg1, input_text" />
        </el-form-item>
        <el-form-item label="上游变量 (Selector)" required>
          <VarReferencePicker
            v-model="inputForm.selector"
            :node-id="nodeId"
            :filter-var="codeInputFilter"
            placeholder="选择上游节点输出变量"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="inputModalVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="saveInputVar">保存</el-button>
      </template>
    </el-dialog>

    <!-- 4. 添加输出字段 Modal -->
    <el-dialog 
      v-model="outputModalVisible" 
      title="添加输出字段" 
      width="400px" 
      append-to-body
      class="workflow-dialog"
    >
      <el-form :model="outputForm" label-position="top" size="small">
        <el-form-item label="字段名称 (Output Key)" required>
          <el-input v-model="outputForm.name" placeholder="例如: result, count, status" />
        </el-form-item>
        <el-form-item label="数据类型 (Data Type)" required>
          <el-select v-model="outputForm.type" class="w-full">
            <el-option 
              v-for="opt in OUTPUT_TYPE_OPTIONS" 
              :key="opt.value" 
              :label="opt.label" 
              :value="opt.value" 
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="outputModalVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="saveOutputVar">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Delete } from '@element-plus/icons-vue'
import PanelHeader from '../shared/PanelHeader.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import NextStep from '../shared/NextStep.vue'
import RetryConfig from '../shared/RetryConfig.vue'
import ErrorHandleConfig from '../shared/ErrorHandleConfig.vue'
import { useCodeConfig, OUTPUT_TYPE_OPTIONS } from './useCodeConfig.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false }
})

const emit = defineEmits(['close', 'update:nodeData'])

const {
  readOnly,
  codeLanguage,
  code,
  variables,
  outputs,
  codeInputFilter,
  handleAddInputVar,
  handleRemoveInputVar,
  handleUpdateInputVar,
  handleAddOutputVar,
  handleRemoveOutputVar,
  handleRenameOutputVar,
  handleUpdateOutputVarType,
  handleSyncFunctionSignature,
  handleErrorStrategyUpdate,
  handleDefaultValueUpdate
} = useCodeConfig(props, emit)

const handleRetryConfigUpdate = (retryConfig) => {
  emit('update:nodeData', { ...props.nodeData, retry_config: retryConfig })
}

const nodeTitle = computed({
  get: () => props.nodeData?.title || '代码执行',
  set: (val) => {
    emit('update:nodeData', { ...props.nodeData, title: val })
  }
})

function onTitleChange(val) {
  emit('update:nodeData', { ...props.nodeData, title: val })
}

function onDescriptionChange(val) {
  const { description: _legacyDescription, ...nodeData } = props.nodeData
  emit('update:nodeData', { ...nodeData, desc: val })
}

// 输入变量 Dialog 状态
const inputModalVisible = ref(false)
const inputForm = ref({ name: '', selector: [] })

// 输出变量 Dialog 状态
const outputModalVisible = ref(false)
const outputForm = ref({ name: '', type: 'string' })

const openAddInputModal = () => {
  inputForm.value = { name: '', selector: [] }
  inputModalVisible.value = true
}

const saveInputVar = () => {
  if (!inputForm.value.name.trim()) {
    ElMessage.warning('请输入变量名称')
    return
  }
  if (!inputForm.value.selector?.length) {
    ElMessage.warning('请选择上游变量')
    return
  }
  const ok = handleAddInputVar(inputForm.value.name.trim(), inputForm.value.selector)
  if (ok) {
    inputModalVisible.value = false
  } else {
    ElMessage.warning('该变量名已存在')
  }
}

const updateInputName = (index, value) => {
  const name = String(value || '').trim()
  if (!/^[A-Za-z_]\w*$/.test(name)) {
    ElMessage.warning('变量名只能包含字母、数字和下划线，且不能以数字开头')
    return
  }
  if (variables.value.some((item, itemIndex) => itemIndex !== index && item.variable === name)) {
    ElMessage.warning('该变量名已存在')
    return
  }
  handleUpdateInputVar(index, { ...variables.value[index], variable: name })
}

const updateInputSelector = (index, selector) => {
  handleUpdateInputVar(index, { ...variables.value[index], value_selector: selector })
}

const openAddOutputModal = () => {
  outputForm.value = { name: '', type: 'string' }
  outputModalVisible.value = true
}

const saveOutputVar = () => {
  if (!outputForm.value.name.trim()) {
    ElMessage.warning('请输入字段名称')
    return
  }
  const ok = handleAddOutputVar(outputForm.value.name.trim(), outputForm.value.type)
  if (ok) {
    outputModalVisible.value = false
  } else {
    ElMessage.warning('该输出字段已存在')
  }
}

const renameOutput = (oldName, value) => {
  const name = String(value || '').trim()
  if (!/^[A-Za-z_]\w*$/.test(name)) {
    ElMessage.warning('输出字段名只能包含字母、数字和下划线，且不能以数字开头')
    return
  }
  if (!handleRenameOutputVar(oldName, name))
    ElMessage.warning('该输出字段已存在')
}

const handleSelectNextNode = () => {
  ElMessage.info('触发添加下一个节点操作')
}
</script>

<style scoped>
.code-panel {
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

.code-hint {
  font-size: 10px;
  color: #94a3b8;
}

.add-btn {
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

.input-vars-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.var-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fcfcfd;
  border: 1px solid #eaecf0;
  border-radius: 6px;
  padding: 4px 8px;
  height: 30px;
}

.var-card-left {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  min-width: 0;
  flex: 1;
}

.var-key {
  font-weight: 600;
  color: #334155;
}

.var-key-input {
  width: 92px;
  flex: 0 0 92px;
}

.var-type-badge {
  flex: 0 0 auto;
  padding: 2px 5px;
  border-radius: 4px;
  background: #f2f4f7;
  color: #667085;
  font-size: 10px;
}

.arrow {
  color: #94a3b8;
}

.var-val {
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.del-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #98a2b3;
  padding: 2px;
}

.del-btn:hover {
  color: #f04438;
}

.editor-container {
  border-radius: 8px;
  overflow: hidden;
}

:deep(.code-textarea .el-textarea__inner) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  background-color: #0f172a;
  color: #f8fafc;
  line-height: 1.5;
  border-radius: 8px;
}

.output-vars-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.output-card {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
  padding: 4px 8px;
}

.out-name {
  font-size: 12px;
  font-weight: 600;
  color: #166534;
  width: 90px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.out-name-input {
  width: 110px;
  flex: 0 0 110px;
}

.sync-btn {
  padding: 3px 7px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  background: #fff;
  color: #344054;
  font-size: 11px;
  cursor: pointer;
}

.type-select {
  flex: 1;
}

.empty-tip {
  font-size: 11px;
  color: #98a2b3;
  font-style: italic;
  text-align: center;
  padding: 8px 0;
}
</style>
