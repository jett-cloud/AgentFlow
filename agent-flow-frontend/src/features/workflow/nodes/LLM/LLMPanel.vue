<!-- src/views/copilot/components/workflow/panel/LLM/LLMPanel.vue -->
<template>
  <div class="llm-panel">
    <PanelHeader
      block-type="llm"
      :title="inputs.title"
      :description="inputs.desc"
      :legacy-description="nodeData.description"
      placeholder="LLM 节点名称"
      :read-only="readOnly"
      @update:title="onTitleChange"
      @update:description="onDescriptionChange"
      @close="$emit('close')"
    />

    <!-- 2. Panel 滚动配置表单主体 -->
    <div class="panel-body">
      
      <!-- (1) 模型选择 -->
      <PanelSection label="模型 (Model)" required>
        <ModelSelector
          v-model="inputs.model"
          :read-only="readOnly"
          @change="notifyChange"
        />
      </PanelSection>

      <!-- (2) 上下文引用 -->
      <PanelSection label="上下文 (Context)">
        <template #extra>
          <el-switch 
            v-model="inputs.context.enabled" 
            size="small"
            :disabled="readOnly"
          />
        </template>

        <VarReferencePicker
          v-if="inputs.context.enabled"
          :model-value="inputs.context.variable_selector"
          :node-id="nodeId"
          placeholder="选择引用的上下文变量"
          :read-only="readOnly"
          @update:model-value="handleContextVarChange"
        />

        <div v-if="shouldShowContextTip" class="context-tip-warning">
          ⚠️ 提示：你已开启上下文，但尚未在下方 Prompt 模板中设置上下文变量。
        </div>
      </PanelSection>

      <!-- =======================================================
           (3) 提示词模版区 (Prompt Templates) -> handlePromptChange
           ======================================================= -->
      <div class="form-section">
        <div class="section-header-flex">
          <label class="section-label">
            <span>Prompt 提示词模版</span>
            <span class="required text-red-500">*</span>
          </label>
          <el-button v-if="!readOnly" size="small" type="primary" link @click="addPromptItem">
            + 添加消息角色
          </el-button>
        </div>
        
        <div class="prompt-list">
          <div 
            v-for="(item, index) in inputs.prompt_template" 
            :key="index" 
            class="prompt-card"
          >
            <div class="prompt-card-header">
              <div class="prompt-card-left">
                <el-select v-model="item.role" size="small" style="width: 110px" :disabled="readOnly" @change="notifyChange">
                  <el-option label="SYSTEM" value="system" />
                  <el-option label="USER" value="user" />
                  <el-option label="ASSISTANT" value="assistant" />
                </el-select>
                <el-radio-group
                  v-model="item.edition_type"
                  size="small"
                  :disabled="readOnly"
                  @change="() => onEditionTypeChange(item)"
                >
                  <el-radio-button label="basic">Basic</el-radio-button>
                  <el-radio-button label="jinja2">Jinja</el-radio-button>
                </el-radio-group>
              </div>

              <button 
                v-if="inputs.prompt_template.length > 1 && !readOnly"
                class="del-role-btn" 
                @click="removePromptItem(index)"
                title="删除该消息块"
              >
                <el-icon><Delete /></el-icon>
              </button>
            </div>

            <PromptVariableTextarea
              v-if="item.edition_type !== 'jinja2'"
              v-model="item.text"
              :node-id="nodeId"
              :rows="4"
              :read-only="readOnly"
              placeholder="输入提示词，敲 { 插入上游/环境/会话/系统变量…"
              @change="notifyChange"
            />

            <div v-else class="jinja-editor">
              <p class="jinja-tip">
                Jinja2 模式：用双花括号包住映射名（如 name），支持 if/for 等语法。
              </p>
              <el-input
                v-model="item.jinja2_text"
                type="textarea"
                :rows="5"
                :disabled="readOnly"
                :placeholder="jinjaPlaceholder"
                class="jinja-textarea"
                @input="notifyChange"
              />
            </div>
          </div>
        </div>

        <div v-if="hasJinjaPrompt" class="jinja-vars-box">
          <div class="section-header-flex">
            <label class="section-label">Jinja 变量映射</label>
            <el-button v-if="!readOnly" size="small" type="primary" link @click="addJinjaVariable">
              + 添加映射
            </el-button>
          </div>
          <p class="jinja-tip">
            先把工作流变量映射成模板名，再在 Jinja 文本里用该名字引用。
          </p>
          <div v-if="inputs.prompt_config.jinja2_variables.length" class="jinja-var-list">
            <div
              v-for="(jv, jIndex) in inputs.prompt_config.jinja2_variables"
              :key="jIndex"
              class="jinja-var-row"
            >
              <el-input
                v-model="jv.variable"
                size="small"
                placeholder="模板变量名"
                :disabled="readOnly"
                @input="notifyChange"
              />
              <VarReferencePicker
                :model-value="jv.value_selector"
                :node-id="nodeId"
                placeholder="绑定工作流变量"
                :read-only="readOnly"
                @update:model-value="(val) => { jv.value_selector = val; notifyChange() }"
              />
              <button
                v-if="!readOnly"
                type="button"
                class="del-role-btn"
                title="删除映射"
                @click="removeJinjaVariable(jIndex)"
              >
                <el-icon><Delete /></el-icon>
              </button>
            </div>
          </div>
          <div v-else class="jinja-empty">还没有映射，点击「添加映射」。</div>
        </div>
      </div>

      <!-- =======================================================
           (4) 对话记忆配置 (Memory Section) -> handleMemoryChange
           ======================================================= -->
      <div v-if="isChatMode" class="form-section border-t pt-3">
        <div class="section-header-flex">
          <label class="section-label flex items-center gap-1">
            <span>对话记忆 (Memory)</span>
            <el-tooltip content="自动保存并带入上下文历史对话轮数" placement="top">
              <el-icon class="info-icon text-gray-400"><InfoFilled /></el-icon>
            </el-tooltip>
          </label>
          <el-switch 
            v-model="memoryEnabled" 
            size="small"
            :disabled="readOnly"
          />
        </div>
        
        <div v-if="memoryEnabled" class="memory-config-box">
          <div class="param-header">
            <span>滑动窗口记忆轮数</span>
            <span class="param-val">{{ memoryWindowSize }} 轮</span>
          </div>
          <el-slider 
            v-model="memoryWindowSize" 
            :min="1" 
            :max="50" 
            :step="1"
            :disabled="readOnly"
          />
        </div>
      </div>

      <!-- =======================================================
           (5) 视觉多模态图像解析 (Vision) -> handleVisionResolutionChange
           ======================================================= -->
      <div v-if="isVisionModel" class="form-section border-t pt-3">
        <div class="section-header-flex">
          <label class="section-label flex items-center gap-1">
            <span>视觉图像解析 (Vision)</span>
            <el-tooltip content="允许模型处理输入的图片或文档附件" placement="top">
              <el-icon class="info-icon text-gray-400"><InfoFilled /></el-icon>
            </el-tooltip>
          </label>
          <el-switch 
            v-model="visionEnabled" 
            size="small"
            :disabled="readOnly"
          />
        </div>

        <div v-if="visionEnabled" class="vision-config-box">
          <span class="sub-label">解析清晰度:</span>
          <el-radio-group v-model="visionDetail" size="small" :disabled="readOnly">
            <el-radio-button label="low">低 (Low)</el-radio-button>
            <el-radio-button label="high">高 (High)</el-radio-button>
            <el-radio-button label="auto">自动 (Auto)</el-radio-button>
          </el-radio-group>
        </div>
      </div>

      <!-- =======================================================
           (6) 模型高级参数设置 (Hyperparameters) -> handleCompletionParamsChange
           ======================================================= -->
      <div class="form-section border-t pt-3">
        <div class="section-title-bar cursor-pointer flex items-center justify-between" @click="showAdvanced = !showAdvanced">
          <span class="section-label">模型高阶参数 (Temperature / Penalty)</span>
          <el-icon :class="{ 'is-rotate': showAdvanced }" class="transition-transform"><ArrowRight /></el-icon>
        </div>

        <div v-show="showAdvanced" class="advanced-params mt-3">
          <!-- Temperature 温度 -->
          <div class="param-item">
            <div class="param-header flex justify-between text-xs text-gray-600 mb-1">
              <span>Temperature (随机性)</span>
              <span class="param-val">{{ inputs.model.completion_params.temperature }}</span>
            </div>
            <el-slider 
              v-model="inputs.model.completion_params.temperature" 
              :min="0" 
              :max="2" 
              :step="0.1" 
              :disabled="readOnly"
              @change="notifyChange"
            />
          </div>

          <!-- Top P -->
          <div class="param-item mt-2">
            <div class="param-header flex justify-between text-xs text-gray-600 mb-1">
              <span>Top P (核采样)</span>
              <span class="param-val">{{ inputs.model.completion_params.top_p }}</span>
            </div>
            <el-slider 
              v-model="inputs.model.completion_params.top_p" 
              :min="0" 
              :max="1" 
              :step="0.05" 
              :disabled="readOnly"
              @change="notifyChange"
            />
          </div>

          <!-- Max Tokens 最大输出长度 -->
          <div class="param-item mt-3">
            <div class="param-header flex justify-between text-xs text-gray-600 mb-1">
              <span>Max Tokens (最大生成长度)</span>
            </div>
            <el-input-number 
              v-model="inputs.model.completion_params.max_tokens" 
              :min="1" 
              :max="16384" 
              :step="256"
              class="w-full"
              :disabled="readOnly"
              @change="notifyChange"
            />
          </div>
        </div>
      </div>

      <!-- =======================================================
           (7) 启用推理标签分离 (ReasoningFormatConfig) -> 1:1 对标 Dify
           ======================================================= -->
      <div class="form-section border-t pt-3">
        <div class="section-header-flex">
          <label class="section-label flex items-center gap-1">
            <span>启用推理标签分离</span>
            <el-tooltip content="开启后，大模型的思考过程将从输出文本中分离，直接写入 reasoning_content 变量中" placement="top">
              <el-icon class="info-icon text-gray-400"><InfoFilled /></el-icon>
            </el-tooltip>
          </label>
          <el-switch 
            :model-value="inputs.reasoning_format === 'separated'" 
            size="small"
            :disabled="readOnly"
            @change="handleReasoningFormatSwitch"
          />
        </div>
      </div>

      <!-- (8) 输出变量 -->
      <PanelSection label="输出变量" border-top>
        <template #extra>
          <div class="flex items-center gap-1" @click.stop>
            <span class="text-xs text-gray-500">结构化输出</span>
            <el-switch 
              v-model="inputs.structured_output_enabled" 
              size="small"
              :disabled="readOnly"
              @change="handleStructureOutputChange"
            />
          </div>
        </template>

        <OutputVarList
          node-type="llm"
          :node-data="inputs"
          :extra-vars="reasoningExtraVars"
        />

        <div v-if="inputs.structured_output_enabled" class="json-schema-box mt-3">
          <div class="sub-label mb-1 text-xs text-gray-600">JSON Schema 架构设定:</div>
          <el-input 
            v-model="structuredOutputSchemaText" 
            type="textarea" 
            :rows="3" 
            :disabled="readOnly"
            placeholder='{"type": "object", "properties": {"summary": {"type": "string"}}}'
          />
        </div>
      </PanelSection>

      <!-- =======================================================
           (9) 失败时重试 (RetryOnPanel - 通用 BasePanel 继承)
           ======================================================= -->
      <div class="form-section border-t pt-3">
        <div class="section-header-flex">
          <label class="section-label flex items-center gap-1">
            <span>失败时重试</span>
          </label>
          <el-switch 
            v-model="retryEnabled" 
            size="small"
            :disabled="readOnly"
          />
        </div>
        <div v-if="retryEnabled" class="retry-config-box mt-2 space-y-3 p-2.5 bg-gray-50 rounded-md border border-gray-100">
          <div class="flex items-center justify-between text-xs">
            <span class="text-gray-600">最大重试次数</span>
            <div class="flex items-center gap-2">
              <el-slider v-model="maxRetries" :min="1" :max="10" style="width: 90px" size="small" />
              <span class="w-10 text-right text-gray-500">{{ maxRetries }} 次</span>
            </div>
          </div>
          <div class="flex items-center justify-between text-xs">
            <span class="text-gray-600">重试间隔时间</span>
            <div class="flex items-center gap-2">
              <el-slider v-model="retryInterval" :min="100" :max="5000" :step="100" style="width: 90px" size="small" />
              <span class="w-12 text-right text-gray-500">{{ retryInterval }} ms</span>
            </div>
          </div>
        </div>
      </div>

      <!-- =======================================================
           (10) 异常处理 (ErrorHandleOnPanel - 通用 BasePanel 继承)
           ======================================================= -->
      <div class="form-section border-t pt-3">
        <div class="section-header-flex">
          <label class="section-label flex items-center gap-1">
            <span>异常处理</span>
            <el-tooltip content="当节点执行异常时（例如超出 Token 或超时），可设置恢复兜底策略" placement="top">
              <el-icon class="info-icon text-gray-400"><InfoFilled /></el-icon>
            </el-tooltip>
          </label>
          <el-select v-model="errorStrategy" size="small" style="width: 110px" :disabled="readOnly" @change="handleErrorStrategyChange">
            <el-option label="无" value="none" />
            <el-option label="设置默认值" value="defaultValue" />
            <el-option label="异常分支" value="failBranch" />
          </el-select>
        </div>
      </div>

      <!-- =======================================================
           (11) 下一步 (NextStep - 通用 BasePanel 继承)
           ======================================================= -->
      <NextStep 
        :node-id="nodeId"
        :node-data="nodeData || inputs"
        :read-only="readOnly"
        @add-next-node="handleSelectNextNode"
      />

    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled, ArrowRight, Delete } from '@element-plus/icons-vue'
import PanelHeader from '../shared/PanelHeader.vue'
import PanelSection from '../shared/PanelSection.vue'
import ModelSelector from '../shared/ModelSelector.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import PromptVariableTextarea from '../shared/PromptVariableTextarea.vue'
import OutputVarList from '../shared/OutputVarList.vue'
import NextStep from '../shared/NextStep.vue'
import { useLLMConfig, EditionType } from './useLLMConfig.js'
import { getNodeErrorStrategy, updateNodeErrorStrategy } from '../../model/nodeErrorStrategy.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
  appMode: { type: String, default: 'chat' }
})

const emit = defineEmits(['close', 'update:nodeData'])

const showAdvanced = ref(true)
const jinjaPlaceholder = '例如: Hello {{ name }}{% if city %} from {{ city }}{% endif %}'

const errorStrategy = ref(getNodeErrorStrategy(props.nodeData))

const {
  readOnly,
  inputs,
  isChatMode,
  shouldShowContextTip,
  hasJinjaPrompt,
  isVisionModel,
  memoryEnabled,
  memoryWindowSize,
  visionEnabled,
  visionDetail,
  structuredOutputSchemaText,
  handleContextVarChange,
  handleMemoryChange,
  handleVisionResolutionChange,
  handleReasoningFormatChange,
  handleStructureOutputChange,
  notifyChange
} = useLLMConfig(props, emit)

function updateRetryConfig(patch) {
  inputs.retry_config = {
    retry_enabled: false,
    max_retries: 3,
    retry_interval: 1000,
    ...(inputs.retry_config || {}),
    ...patch,
  }
  notifyChange()
}

const retryEnabled = computed({
  get: () => Boolean(inputs.retry_config?.retry_enabled),
  set: retry_enabled => updateRetryConfig({ retry_enabled }),
})
const maxRetries = computed({
  get: () => inputs.retry_config?.max_retries ?? 3,
  set: max_retries => updateRetryConfig({ max_retries }),
})
const retryInterval = computed({
  get: () => inputs.retry_config?.retry_interval ?? 1000,
  set: retry_interval => updateRetryConfig({ retry_interval }),
})

const reasoningExtraVars = computed(() =>
  inputs.reasoning_format === 'separated'
    ? [{ variable: 'reasoning_content', type: 'string', des: '推理链文本' }]
    : []
)

function onTitleChange(val) {
  inputs.title = val
  notifyChange()
}

function onDescriptionChange(val) {
  inputs.desc = val
  notifyChange()
}

function handleErrorStrategyChange(strategy) {
  emit('update:nodeData', updateNodeErrorStrategy(props.nodeData, strategy))
}

// 切换 Reasoning Format 开关 (ON = separated, OFF = tagged)
const handleReasoningFormatSwitch = (enabled) => {
  handleReasoningFormatChange(enabled ? 'separated' : 'tagged')
}

// 动态添加提示词角色块
const addPromptItem = () => {
  if (readOnly.value) return
  if (!Array.isArray(inputs.prompt_template)) {
    inputs.prompt_template = [{ role: 'system', text: inputs.prompt_template || '', edition_type: EditionType.basic, jinja2_text: '' }]
  }
  inputs.prompt_template.push({ role: 'user', text: '', edition_type: EditionType.basic, jinja2_text: '' })
  notifyChange()
}

// 删除指定提示词角色块
const removePromptItem = (index) => {
  if (readOnly.value) return
  if (Array.isArray(inputs.prompt_template) && inputs.prompt_template.length > 1) {
    inputs.prompt_template.splice(index, 1)
    notifyChange()
  }
}

function onEditionTypeChange(item) {
  if (item.edition_type === EditionType.jinja2 && !item.jinja2_text && item.text)
    item.jinja2_text = item.text
  if (!inputs.prompt_config)
    inputs.prompt_config = { jinja2_variables: [] }
  if (!Array.isArray(inputs.prompt_config.jinja2_variables))
    inputs.prompt_config.jinja2_variables = []
  notifyChange()
}

function addJinjaVariable() {
  if (!inputs.prompt_config)
    inputs.prompt_config = { jinja2_variables: [] }
  inputs.prompt_config.jinja2_variables.push({
    variable: `var_${inputs.prompt_config.jinja2_variables.length + 1}`,
    value_selector: [],
  })
  notifyChange()
}

function removeJinjaVariable(index) {
  inputs.prompt_config.jinja2_variables.splice(index, 1)
  notifyChange()
}

// 点击下一个节点快捷处理
const handleSelectNextNode = () => {
  ElMessage.info('触发选择下一个工作流节点')
}
</script>

<style scoped>
.llm-panel {
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

.warning-dot {
  width: 6px;
  height: 6px;
  background-color: #f59e0b;
  border-radius: 50%;
  display: inline-block;
}

.context-tip-warning {
  font-size: 11px;
  color: #d97706;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  padding: 6px 10px;
  border-radius: 6px;
  margin-top: 4px;
}

.prompt-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.prompt-card {
  border: 1px solid #eaecf0;
  border-radius: 8px;
  padding: 8px 10px;
  background: #fcfcfd;
}

.prompt-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  gap: 8px;
}

.prompt-card-left {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.jinja-editor,
.jinja-vars-box {
  margin-top: 6px;
}

.jinja-tip {
  margin: 0 0 8px;
  color: #667085;
  font-size: 11px;
  line-height: 1.5;
}

.jinja-tip code {
  padding: 0 3px;
  border-radius: 3px;
  background: #f2f4f7;
  color: #155eef;
  font-family: ui-monospace, monospace;
}

.jinja-textarea :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
}

.jinja-vars-box {
  padding: 10px;
  border: 1px solid #eaecf0;
  border-radius: 8px;
  background: #f8fafc;
}

.jinja-var-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.jinja-var-row {
  display: grid;
  grid-template-columns: minmax(90px, 120px) 1fr auto;
  gap: 8px;
  align-items: center;
}

.jinja-empty {
  color: #98a2b3;
  font-size: 12px;
}

.del-role-btn {
  background: none;
  border: none;
  color: #98a2b3;
  cursor: pointer;
  padding: 2px 4px;
}

.del-role-btn:hover {
  color: #f04438;
}

.memory-config-box,
.vision-config-box,
.json-schema-box {
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
  padding: 10px;
  margin-top: 6px;
}

.is-rotate {
  transform: rotate(90deg);
}

.var-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f9fafb;
  border: 1px solid #f2f4f7;
  padding: 6px 10px;
  border-radius: 6px;
}
</style>
