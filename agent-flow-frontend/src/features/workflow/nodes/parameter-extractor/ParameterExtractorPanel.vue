<!-- src/views/copilot/components/workflow/panel/parameter-extractor/ParameterExtractorPanel.vue -->
<template>
  <div class="pe-panel">
    <PanelHeader
      block-type="parameter-extractor"
      :title="nodeTitle"
      :description="nodeData.desc"
      :legacy-description="nodeData.description"
      placeholder="参数提取器"
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
          :filter-var="isParameterExtractorInput"
          placeholder="选择要提取参数的文本变量"
          :read-only="readOnly"
        />
      </PanelSection>

      <PanelSection label="模型 (Model)" required>
        <ModelSelector
          v-model="model"
          :read-only="readOnly"
          :require-tool-call="reasoningMode === 'function_call'"
          @change="onModelChange"
        />
      </PanelSection>

      <PanelSection label="视觉输入 (Vision)">
        <template #extra>
          <el-switch v-model="visionEnabled" size="small" :disabled="readOnly" />
        </template>
        <VarReferencePicker
          v-if="visionEnabled"
          v-model="visionSelector"
          :node-id="nodeId"
          :filter-var="isVisionInput"
          placeholder="选择文件或文件数组变量"
          :read-only="readOnly"
        />
      </PanelSection>

      <PanelSection label="参数定义 (Parameters)">
        <template #extra>
          <button v-if="!readOnly" class="add-btn" @click="openAddModal">
            <el-icon><Plus /></el-icon>
          </button>
        </template>

        <div class="params-list">
          <div v-for="(p, idx) in parameters" :key="p.name + idx" class="param-card">
            <div class="param-main">
              <div class="param-heading">
                <span class="p-name font-mono">{{ p.name }}</span>
                <span v-if="p.required" class="required-tag">必填</span>
              </div>
              <span class="p-description">{{ p.description }}</span>
            </div>
            <span class="p-type font-mono">{{ p.type }}</span>
            <button v-if="!readOnly" class="del-btn" title="编辑参数" @click="openEditModal(idx)">
              <el-icon><Edit /></el-icon>
            </button>
            <button v-if="!readOnly" class="del-btn" @click="handleRemoveParam(idx)">
              <el-icon><Delete /></el-icon>
            </button>
          </div>
          <div v-if="!parameters.length" class="empty-tip">暂无参数，点击 + 添加</div>
        </div>
      </PanelSection>

      <PanelSection label="提取指令 (Instruction)">
        <el-input
          v-model="instruction"
          type="textarea"
          :rows="4"
          :disabled="readOnly"
          placeholder="补充参数提取规则，可插入上游变量"
        />
      </PanelSection>

      <PanelSection label="推理模式 (Reasoning Mode)">
        <el-radio-group v-model="reasoningMode" :disabled="readOnly">
          <el-radio-button label="prompt">Prompt</el-radio-button>
          <el-radio-button label="function_call">Function Call</el-radio-button>
        </el-radio-group>
      </PanelSection>

      <PanelSection v-if="appMode !== 'workflow'" label="对话记忆 (Memory)">
        <template #extra>
          <el-switch v-model="memoryEnabled" size="small" :disabled="readOnly" />
        </template>
        <div v-if="memoryEnabled" class="memory-row">
          <span>滑动窗口</span>
          <el-input-number v-model="memoryWindowSize" :min="1" :max="50" size="small" :disabled="readOnly" />
        </div>
      </PanelSection>

      <PanelSection label="输出变量" border-top>
        <OutputVarList
          node-type="parameter-extractor"
          :node-data="{ type: 'parameter-extractor', parameters }"
        />
      </PanelSection>

      <RetryConfig
        :node-data="nodeData"
        :read-only="readOnly"
        @update:retry-config="retryConfig => updateData({ retry_config: retryConfig })"
      />
      <ErrorHandleConfig
        :node-data="nodeData"
        :read-only="readOnly"
        @update:error-strategy="errorStrategy => updateData({ error_strategy: errorStrategy })"
        @update:default-value="updateDefaultValue"
      />

      <NextStep :node-id="nodeId" :node-data="nodeData" :read-only="readOnly" />
    </div>

    <el-dialog v-model="modalVisible" :title="editingIndex === -1 ? '添加参数' : '编辑参数'" width="420px" append-to-body class="workflow-dialog">
      <el-form :model="form" label-position="top" size="small">
        <el-form-item label="参数 Key" required>
          <el-input v-model="form.name" placeholder="例如: location" />
        </el-form-item>
        <el-form-item label="数据类型">
          <el-select v-model="form.type" class="w-full">
            <el-option label="String" value="string" />
            <el-option label="Number" value="number" />
            <el-option label="Boolean" value="boolean" />
            <el-option label="Array[String]" value="array[string]" />
            <el-option label="Array[Number]" value="array[number]" />
            <el-option label="Array[Boolean]" value="array[boolean]" />
            <el-option label="Array[Object]" value="array[object]" />
            <el-option label="Select" value="select" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.type === 'select'" label="候选值" required>
          <el-select v-model="form.options" multiple allow-create filterable default-first-option class="w-full" placeholder="输入候选值后回车" />
        </el-form-item>
        <el-form-item label="参数描述" required>
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="说明模型应如何提取该参数" />
        </el-form-item>
        <el-form-item label="是否必填">
          <el-switch v-model="form.required" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="modalVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="saveParam">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Delete, Edit } from '@element-plus/icons-vue'
import PanelHeader from '../shared/PanelHeader.vue'
import PanelSection from '../shared/PanelSection.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import ModelSelector from '../shared/ModelSelector.vue'
import OutputVarList from '../shared/OutputVarList.vue'
import NextStep from '../shared/NextStep.vue'
import RetryConfig from '../shared/RetryConfig.vue'
import ErrorHandleConfig from '../shared/ErrorHandleConfig.vue'
import { useParameterExtractorConfig } from './useParameterExtractorConfig.js'
import { isParameterExtractorInput, isParameterNameValid } from './parameterExtractorNode.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
  appMode: { type: String, default: 'chat' },
})

const emit = defineEmits(['close', 'update:nodeData'])

const {
  readOnly,
  parameters,
  updateData,
  handleAddParam,
  handleUpdateParam,
  handleRemoveParam,
} = useParameterExtractorConfig(props, emit)

const nodeTitle = computed({
  get: () => props.nodeData?.title || '参数提取器',
  set: (val) => emit('update:nodeData', { ...props.nodeData, title: val }),
})

const querySelector = computed({
  get: () => {
    const q = props.nodeData?.query
    if (Array.isArray(q)) return q
    return []
  },
  set: val => updateData({ query: val || [] }),
})

const model = computed({
  get: () => props.nodeData?.model || { provider: '', name: '', mode: 'chat', completion_params: {} },
  set: val => updateData({ model: val }),
})

const instruction = computed({
  get: () => props.nodeData?.instruction || '',
  set: value => updateData({ instruction: value }),
})

const reasoningMode = computed({
  get: () => props.nodeData?.reasoning_mode || 'prompt',
  set: reasoning_mode => updateData({ reasoning_mode }),
})

const visionEnabled = computed({
  get: () => Boolean(props.nodeData?.vision?.enabled),
  set: (enabled) => updateData({
    vision: {
      ...(props.nodeData?.vision || {}),
      enabled,
      ...(enabled ? {
        configs: {
          detail: props.nodeData?.vision?.configs?.detail || 'high',
          variable_selector: props.nodeData?.vision?.configs?.variable_selector || [],
        },
      } : {}),
    },
  }),
})

const visionSelector = computed({
  get: () => props.nodeData?.vision?.configs?.variable_selector || [],
  set: variable_selector => updateData({
    vision: {
      ...(props.nodeData?.vision || {}),
      enabled: true,
      configs: { ...(props.nodeData?.vision?.configs || {}), variable_selector },
    },
  }),
})

const isVisionInput = variable => ['file', 'arrayFile'].includes(variable?.type)

const memoryEnabled = computed({
  get: () => Boolean(props.nodeData?.memory?.window?.enabled),
  set: (enabled) => {
    if (!enabled)
      updateData({ memory: undefined })
    else
      updateData({ memory: { ...(props.nodeData?.memory || {}), window: { enabled: true, size: props.nodeData?.memory?.window?.size ?? 10 } } })
  },
})

const memoryWindowSize = computed({
  get: () => props.nodeData?.memory?.window?.size ?? 10,
  set: size => updateData({ memory: { ...(props.nodeData?.memory || {}), window: { enabled: true, size } } }),
})

function onTitleChange(val) {
  emit('update:nodeData', { ...props.nodeData, title: val })
}

function onDescriptionChange(val) {
  const { description: _legacyDescription, ...nodeData } = props.nodeData
  emit('update:nodeData', { ...nodeData, desc: val })
}

function onModelChange(val) {
  updateData({ model: val })
}

const modalVisible = ref(false)
const editingIndex = ref(-1)
const form = ref({ name: '', type: 'string', description: '', required: false, options: [] })

function openAddModal() {
  editingIndex.value = -1
  form.value = { name: '', type: 'string', description: '', required: false, options: [] }
  modalVisible.value = true
}

function openEditModal(index) {
  editingIndex.value = index
  form.value = { options: [], required: false, ...parameters.value[index] }
  modalVisible.value = true
}

function saveParam() {
  const name = form.value.name.trim()
  if (!isParameterNameValid(name)) {
    ElMessage.warning('参数 Key 只能包含字母、数字和下划线，且不能以数字开头')
    return
  }
  if (parameters.value.some((item, index) => item.name === name && index !== editingIndex.value)) {
    ElMessage.warning('参数 Key 不能重复')
    return
  }
  if (!form.value.description.trim()) {
    ElMessage.warning('请输入参数描述')
    return
  }
  if (form.value.type === 'select' && !form.value.options?.length) {
    ElMessage.warning('请至少添加一个候选值')
    return
  }
  const param = {
    name,
    type: form.value.type,
    description: form.value.description.trim(),
    required: Boolean(form.value.required),
    ...(form.value.type === 'select' ? { options: [...form.value.options] } : {}),
  }
  if (editingIndex.value === -1)
    handleAddParam(param)
  else
    handleUpdateParam(editingIndex.value, param)
  modalVisible.value = false
}

function updateDefaultValue({ key, value }) {
  const current = Array.isArray(props.nodeData?.default_value) ? props.nodeData.default_value : []
  const index = current.findIndex(item => item.key === key)
  const next = index === -1
    ? [...current, { key, value }]
    : current.map((item, itemIndex) => itemIndex === index ? { ...item, value } : item)
  updateData({ default_value: next })
}
</script>

<style scoped>
.pe-panel {
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
.params-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.param-card {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
  padding: 6px 10px;
}
.param-main {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}
.param-heading {
  display: flex;
  align-items: center;
  gap: 6px;
}
.p-name {
  font-size: 12px;
  font-weight: 600;
  color: #155eef;
}
.p-description {
  overflow: hidden;
  color: #667085;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.required-tag {
  color: #b54708;
  font-size: 10px;
}
.p-type {
  font-size: 10px;
  color: #667085;
  background: #f2f4f7;
  padding: 1px 6px;
  border-radius: 4px;
}
.add-btn,
.del-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #667085;
  padding: 2px 4px;
}
.del-btn:hover {
  color: #f04438;
}
.empty-tip {
  font-size: 12px;
  color: #98a2b3;
  padding: 8px 0;
}
.memory-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #667085;
  font-size: 12px;
}
</style>
