<!-- src/views/copilot/components/workflow/panel/start/StartPanel.vue -->
<template>
  <div class="start-panel">
    <!-- 1. Panel 顶部 Header (图标、标题编辑、关闭按钮) -->
    <div class="panel-header">
      <div class="header-left">
        <BlockIcon type="start" :size="20" />
        <input 
          v-model="nodeTitle" 
          class="title-input" 
          placeholder="开始"
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
      
      <!-- =======================================================
           (1) 输入字段管理区 (Input Fields)
           ======================================================= -->
      <div class="form-section">
        <div class="section-header-flex">
          <label class="section-label">输入字段</label>
          <button
            v-if="!readOnly"
            type="button"
            class="add-var-btn"
            title="添加输入字段"
            @click="openAddVarDialog"
          >
            <el-icon><Plus /></el-icon>
          </button>
        </div>

        <!-- 变量列表 (完全对标 Dify VarItem 效果) -->
        <div class="var-list">
          <div 
            v-for="(item, index) in variables" 
            :key="item.variable + index"
            class="var-item-card"
          >
            <div class="var-left-box">
              <!-- Dify 专用的 {x} 变量图标 -->
              <svg class="var-icon-svg" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M4.5 3.5L3 8L4.5 12.5" stroke="#155EEF" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M11.5 3.5L13 8L11.5 12.5" stroke="#155EEF" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M9 5.5L7 10.5" stroke="#155EEF" stroke-width="1.25" stroke-linecap="round"/>
              </svg>
              
              <!-- 变量名 (variable) -->
              <span class="var-key" :title="item.variable">{{ item.variable }}</span>
              
              <!-- 中间点与 Label -->
              <template v-if="item.label && item.label !== item.variable">
                <span class="dot-separator">·</span>
                <span class="var-label" :title="item.label">{{ item.label }}</span>
              </template>
            </div>

            <div class="var-right-box">
              <!-- 默认状态: 展示 Required + 数据类型 -->
              <div class="default-info">
                <span v-if="item.required" class="required-tag">Required</span>
                <span class="type-badge">{{ formatVarTypeTag(item.type) }}</span>
              </div>

              <!-- Hover 悬浮状态: 展示编辑和删除按钮 (仅非只读) -->
              <div v-if="!readOnly" class="action-btn-group">
                <button class="hover-icon-btn" title="编辑" @click="openEditVarDialog(index)">
                  <el-icon><Edit /></el-icon>
                </button>
                <button class="hover-icon-btn hover-danger" title="删除" @click="handleRemoveVariable(index)">
                  <el-icon><Delete /></el-icon>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 系统内置变量 (System Variables) -->
        <div class="system-vars-container">
          <div class="split-line"></div>
          
          <!-- userinput.query (对话模式显示) -->
          <div v-if="isChatMode" class="var-item-card system-var">
            <div class="var-left-box">
              <svg class="var-icon-svg" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M4.5 3.5L3 8L4.5 12.5" stroke="#155EEF" stroke-width="1.25" stroke-linecap="round"/>
                <path d="M11.5 3.5L13 8L11.5 12.5" stroke="#155EEF" stroke-width="1.25" stroke-linecap="round"/>
                <path d="M9 5.5L7 10.5" stroke="#155EEF" stroke-width="1.25" stroke-linecap="round"/>
              </svg>
              <span class="var-key text-gray-700 font-medium">userinput.query</span>
            </div>
            <div class="var-right-box">
              <span class="type-badge text-gray-400">String</span>
            </div>
          </div>

          <!-- userinput.files -->
          <div class="var-item-card system-var mt-1.5">
            <div class="var-left-box">
              <svg class="var-icon-svg" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M4.5 3.5L3 8L4.5 12.5" stroke="#155EEF" stroke-width="1.25" stroke-linecap="round"/>
                <path d="M11.5 3.5L13 8L11.5 12.5" stroke="#155EEF" stroke-width="1.25" stroke-linecap="round"/>
                <path d="M9 5.5L7 10.5" stroke="#155EEF" stroke-width="1.25" stroke-linecap="round"/>
              </svg>
              <span class="var-key text-gray-700 font-medium">userinput.files</span>
            </div>
            <div class="var-right-box">
              <span class="type-badge text-gray-400">Array[File]</span>
            </div>
          </div>
        </div>
      </div>

      <!-- =======================================================
           (2) 下一步节点关联组件 (NextStep)
           ======================================================= -->
      <NextStep 
        :node-id="nodeId"
        :node-data="nodeData"
        :read-only="readOnly"
        @add-next-node="handleSelectNextNode"
      />
    </div>

    <!-- =======================================================
         3. 1:1 对标 Dify ConfigModalFormFields 的高级配置 Dialog
         ======================================================= -->
    <el-dialog 
      v-model="varDialogVisible" 
      :title="isEditMode ? '编辑变量 (Edit Variable)' : '添加变量 (Add Variable)'" 
      width="460px"
      append-to-body
      class="dify-var-modal workflow-dialog"
    >
      <el-form :model="varForm" label-position="top" size="small" class="space-y-1">
        
        <!-- 1. 字段类型 Selection (TypeSelector) -->
        <el-form-item label="字段类型 (Type)" required>
          <el-select 
            v-model="varForm.type" 
            class="w-full"
            @change="handleTypeChangeInForm"
          >
            <el-option
              v-for="item in INPUT_VAR_TYPE_OPTIONS"
              :key="item.value"
              :label="item.name"
              :value="item.value"
            >
              <div class="flex items-center justify-between">
                <span>{{ item.name }}</span>
                <el-tag size="small" type="info" class="font-mono text-xs">{{ item.tag }}</el-tag>
              </div>
            </el-option>
          </el-select>
        </el-form-item>

        <!-- 2. 变量 Key (varName) -->
        <el-form-item label="变量 Key (varName)" required>
          <el-input 
            v-model="varForm.variable" 
            placeholder="如: query, user_id, doc_text" 
            :disabled="isEditMode" 
          />
        </el-form-item>

        <!-- 3. 显示名称 (labelName) -->
        <el-form-item label="显示名称 (Label)" required>
          <el-input v-model="varForm.label" placeholder="如: 用户问题, 输入参数标题" />
        </el-form-item>

        <!-- 4.1 [text-input & paragraph] 专属: Max Length -->
        <el-form-item 
          v-if="['text-input', 'paragraph'].includes(varForm.type)" 
          label="最大字符长度 (Max Length)"
        >
          <el-input-number v-model="varForm.max_length" :min="1" :max="10000" class="w-full" />
        </el-form-item>

        <!-- 4.2 [text-input] 专属: 默认短文本 -->
        <el-form-item v-if="varForm.type === 'text-input'" label="默认值 (Default Value)">
          <el-input v-model="varForm.default" placeholder="请输入默认文本" />
        </el-form-item>

        <!-- 4.3 [paragraph] 专属: 默认长文本 Textarea -->
        <el-form-item v-if="varForm.type === 'paragraph'" label="默认值 (Default Text)">
          <el-input v-model="varForm.default" type="textarea" :rows="3" placeholder="请输入默认段落" />
        </el-form-item>

        <!-- 4.4 [number] 专属: 默认数字 -->
        <el-form-item v-if="varForm.type === 'number'" label="默认数字 (Default Number)">
          <el-input-number v-model="varForm.default" class="w-full" placeholder="输入数字默认值" />
        </el-form-item>

        <!-- 4.5 [checkbox] 专属: 默认布尔状态 -->
        <el-form-item v-if="varForm.type === 'checkbox'" label="默认选中状态">
          <el-select v-model="varForm.default" class="w-full">
            <el-option label="默认开启 (True)" :value="true" />
            <el-option label="默认关闭 / 无默认值 (False)" :value="false" />
          </el-select>
        </el-form-item>

        <!-- 4.6 [select] 专属: 动态 Options 选项列表 & 默认值下拉 -->
        <template v-if="varForm.type === 'select'">
          <el-form-item label="下拉菜单选项 (Options)" required>
            <div class="space-y-2 w-full">
              <div 
                v-for="(opt, idx) in varForm.options" 
                :key="idx" 
                class="flex items-center gap-2"
              >
                <el-input v-model="varForm.options[idx]" placeholder="输入选项值" />
                <el-button 
                  v-if="varForm.options.length > 1" 
                  type="danger" 
                  circle 
                  size="small" 
                  @click="removeSelectOption(idx)"
                >
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
              <el-button size="small" type="primary" plain class="w-full mt-1" @click="addSelectOption">
                + 添加选项
              </el-button>
            </div>
          </el-form-item>

          <el-form-item label="默认选中项 (Default Option)">
            <el-select v-model="varForm.default" clearable class="w-full" placeholder="请选择默认项">
              <el-option 
                v-for="opt in varForm.options" 
                :key="opt" 
                :label="opt" 
                :value="opt" 
              />
            </el-select>
          </el-form-item>
        </template>

        <!-- 4.7 [single-file & multi-files] 专属: 允许上传文件类型与允许最大数量 -->
        <template v-if="['file', 'file-list', 'single-file', 'multi-files'].includes(varForm.type)">
          <el-form-item label="支持上传的文件类型" required>
            <el-checkbox-group v-model="varForm.allowed_file_types">
              <el-checkbox label="document">文档 (Document)</el-checkbox>
              <el-checkbox label="image">图片 (Image)</el-checkbox>
              <el-checkbox label="audio">音频 (Audio)</el-checkbox>
              <el-checkbox label="video">视频 (Video)</el-checkbox>
            </el-checkbox-group>
          </el-form-item>

          <el-form-item v-if="['file-list', 'multi-files'].includes(varForm.type)" label="最多允许上传文件数">
            <el-input-number v-model="varForm.max_length" :min="1" :max="10" class="w-full" />
          </el-form-item>
        </template>

        <!-- 4.8 [json-object] 专属: JSON Schema 架构描述框 -->
        <el-form-item v-if="varForm.type === 'json-object'" label="JSON Schema 架构 (必须为 type: object)">
          <el-input 
            v-model="varForm.json_schema" 
            type="textarea" 
            :rows="4" 
            placeholder='{\n  "type": "object",\n  "properties": {\n    "name": { "type": "string" }\n  }\n}'
            class="font-mono text-xs"
          />
        </el-form-item>

        <!-- 5. 是否必填 & 隐藏设置开关 -->
        <div class="pt-3 border-t flex items-center justify-between">
          <label class="flex items-center gap-2 cursor-pointer">
            <el-switch v-model="varForm.required" size="small" />
            <span class="text-xs font-semibold text-gray-700">设为必填 (Required)</span>
          </label>

          <label v-if="!varForm.required" class="flex items-center gap-2 cursor-pointer">
            <el-switch v-model="varForm.hide" size="small" />
            <span class="text-xs font-semibold text-gray-700">在界面中隐藏 (Hide)</span>
          </label>
        </div>

      </el-form>

      <template #footer>
        <el-button size="small" @click="varDialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="saveVarForm">保存变量</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, Plus, Edit, Delete } from '@element-plus/icons-vue'
import BlockIcon from '../base/BlockIcon.vue'
import NextStep from '../shared/NextStep.vue'
import { 
  useStartConfig, 
  INPUT_VAR_TYPE_OPTIONS, 
  formatVarTypeTag, 
  createPayloadForType,
  InputVarType 
} from './useStartConfig.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
  appMode: { type: String, default: 'chat' }
})

const emit = defineEmits(['close', 'update:nodeData'])

const {
  readOnly,
  isChatMode,
  variables,
  handleAddVariable,
  handleRemoveVariable,
  handleUpdateVariable,
  notifyChange
} = useStartConfig(props, emit)

const nodeTitle = computed({
  get: () => props.nodeData?.title || '开始',
  set: (val) => {
    emit('update:nodeData', { ...props.nodeData, title: val })
  }
})

// 变量 Modal 控制
const varDialogVisible = ref(false)
const isEditMode = ref(false)
const editingIndex = ref(-1)

const varForm = ref(createPayloadForType('', InputVarType.textInput))

// 切换类型时，按 Dify 源码 createPayloadForType 重新调整数据结构
const handleTypeChangeInForm = (newType) => {
  const currentVarName = varForm.value.variable
  const currentLabel = varForm.value.label
  const nextPayload = createPayloadForType(currentVarName, newType)
  nextPayload.label = currentLabel
  varForm.value = nextPayload
}

// select 类型增删选项
const addSelectOption = () => {
  if (!Array.isArray(varForm.value.options)) varForm.value.options = []
  varForm.value.options.push(`选项${varForm.value.options.length + 1}`)
}

const removeSelectOption = (index) => {
  if (Array.isArray(varForm.value.options)) {
    varForm.value.options.splice(index, 1)
  }
}

const openAddVarDialog = () => {
  isEditMode.value = false
  editingIndex.value = -1
  varForm.value = createPayloadForType('', InputVarType.textInput)
  varDialogVisible.value = true
}

const openEditVarDialog = (index) => {
  isEditMode.value = true
  editingIndex.value = index
  const item = variables[index]
  varForm.value = JSON.parse(JSON.stringify(item))
  varDialogVisible.value = true
}

const saveVarForm = () => {
  if (!varForm.value.variable.trim()) {
    ElMessage.warning('请输入变量 Key (varName)')
    return
  }

  if (!varForm.value.label.trim()) {
    varForm.value.label = varForm.value.variable.trim()
  }

  if (isEditMode.value) {
    handleUpdateVariable(editingIndex.value, { ...varForm.value })
    varDialogVisible.value = false
  } else {
    const ok = handleAddVariable({ ...varForm.value })
    if (ok) varDialogVisible.value = false
  }
}

const handleSelectNextNode = () => {
  ElMessage.info('触发添加下一个节点操作')
}
</script>

<style scoped>
.start-panel {
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

.var-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.var-item-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 32px;
  background: #fcfcfd;
  border: 1px solid #eaecf0;
  border-radius: 8px;
  padding: 0 10px;
  transition: all 0.15s ease;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
}

.var-item-card:hover {
  border-color: #d0d5dd;
  box-shadow: 0 2px 4px rgba(16, 24, 40, 0.08);
}

.var-left-box {
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

.var-key {
  font-size: 13px;
  font-weight: 500;
  color: #344054;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dot-separator {
  font-size: 12px;
  color: #98a2b3;
  flex-shrink: 0;
}

.var-label {
  font-size: 13px;
  font-weight: 500;
  color: #667085;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.var-right-box {
  display: flex;
  align-items: center;
  position: relative;
  flex-shrink: 0;
}

.default-info {
  display: flex;
  align-items: center;
  gap: 6px;
}

.required-tag {
  font-size: 11px;
  color: #667085;
}

.type-badge {
  font-size: 11px;
  color: #667085;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.action-btn-group {
  display: none;
  align-items: center;
  gap: 4px;
}

.var-item-card:hover .default-info {
  display: none;
}

.var-item-card:hover .action-btn-group {
  display: flex;
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
  background-color: #f2f4f7;
  color: #155eef;
}

.hover-icon-btn.hover-danger:hover {
  background-color: #fef2f2;
  color: #f04438;
}

.system-vars-container {
  margin-top: 4px;
}

.split-line {
  height: 1px;
  background-color: #f2f4f7;
  margin: 10px 0;
}

.system-var {
  background-color: #f8fafc;
  border-color: #f1f5f9;
  box-shadow: none;
}

.system-var:hover .default-info {
  display: flex;
}

.system-var:hover .action-btn-group {
  display: none;
}
</style>
