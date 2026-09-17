<!-- src/views/copilot/components/workflow/panel/human-input/HumanInputPanel.vue -->
<template>
  <div class="hi-panel">
    <!-- Header 头部 -->
    <div class="panel-header">
      <div class="header-left">
        <BlockIcon type="human-input" :size="20" />
        <input v-model="nodeTitle" class="title-input" placeholder="人机交互" :disabled="readOnly" />
      </div>
      <button type="button" class="close-btn" aria-label="关闭配置面板" @click="$emit('close')"><el-icon><Close /></el-icon></button>
    </div>

    <!-- Body 配置主体 (完全对齐 Dify 源码四大配置区块) -->
    <div class="panel-body">
      <!-- 1. 交付通知渠道 (Delivery Methods) -->
      <div class="form-section">
        <div class="section-label">交付/通知途径 (DELIVERY METHODS)</div>
        <el-checkbox-group :model-value="deliveryMethods" :disabled="readOnly" class="checkbox-group" @change="onDeliveryMethodsChange">
          <el-checkbox value="webapp" :disabled="readOnly || webAppAddDisabled">🤖 WebApp 弹窗与对话交互</el-checkbox>
          <el-checkbox value="email">✉️ Email 邮件通知交互</el-checkbox>
        </el-checkbox-group>
        <HumanInputEmailConfig
          v-if="deliveryMethods.includes('email')"
          v-model="emailConfig"
          :read-only="readOnly"
        />
      </div>

      <!-- 2. 表单内容与提示词 (Form Content) -->
      <div class="form-section">
        <div class="section-header">
          <div class="section-label">表单内容 (FORM CONTENT)</div>
          <div class="actions-group">
            <el-button 
              size="small" 
              :type="isPreview ? 'primary' : 'default'" 
              link 
              @click="isPreview = !isPreview"
            >
              <el-icon><View /></el-icon> {{ isPreview ? '编辑' : '预览' }}
            </el-button>
            <el-button size="small" type="default" link @click="copyContent">
              <el-icon><DocumentCopy /></el-icon> 复制
            </el-button>
          </div>
        </div>

        <!-- 编辑模式 vs 预览模式 -->
        <div v-if="!isPreview" class="editor-wrapper">
          <HumanInputContentEditor
            :model-value="prompt"
            :fields="inputs"
            :node-id="nodeId"
            :read-only="readOnly"
            @update:model-value="prompt = $event"
            @update:fields="inputs = $event"
            @rename-field="onRenameField"
            @remove-field="onRemoveField"
          />
        </div>
        <HumanInputFormPreview
          v-else
          :content="prompt"
          :fields="inputs"
          :actions="userActions"
        />
      </div>

      <!-- 3. 分支操作按钮 (User Actions) -->
      <div class="form-section">
        <div class="section-header">
          <div class="section-label">分支操作按钮 (USER ACTIONS)</div>
          <el-button v-if="!readOnly" size="small" type="primary" link @click="addUserAction">
            <el-icon><Plus /></el-icon> 添加按钮
          </el-button>
        </div>

        <div v-if="userActions && userActions.length" class="actions-list">
          <div v-for="(act, aIdx) in userActions" :key="actionDraftKey(act, aIdx)" class="action-card">
            <div class="action-field">
              <el-input
                :model-value="act.title"
                size="small"
                placeholder="按钮文案（如：同意）"
                :maxlength="100"
                show-word-limit
                :disabled="readOnly"
                @update:model-value="updateUserAction(aIdx, { title: $event })"
              />
              <span v-if="!String(act.title || '').trim()" class="field-error">按钮文案不能为空</span>
            </div>
            <div class="action-field">
              <el-input
                :model-value="actionIdDisplay(act, aIdx)"
                size="small"
                placeholder="分支 ID（如：approve）"
                :disabled="readOnly"
                @update:model-value="commitActionId(act, aIdx, $event)"
              />
              <span v-if="actionIdError(act, aIdx)" class="field-error">{{ actionIdError(act, aIdx) }}</span>
            </div>
            <el-select 
              :model-value="act.button_style"
              size="small" 
              placeholder="按钮风格" 
              :disabled="readOnly" 
              @change="updateUserAction(aIdx, { button_style: $event })"
            >
              <el-option 
                v-for="s in BUTTON_STYLES" 
                :key="s.value" 
                :label="s.label" 
                :value="s.value" 
              />
            </el-select>
            <button
              v-if="!readOnly && userActions.length > 1"
              type="button"
              class="icon-btn"
              aria-label="删除操作按钮"
              @click="onRemoveUserAction(aIdx)"
            >
              <el-icon><Delete /></el-icon>
            </button>
          </div>
        </div>
        <div v-else class="empty-tip">未配置操作按钮，需至少添加一个分支按钮</div>
      </div>

      <!-- 4. 超时设置 (Timeout) -->
      <div class="form-section">
        <div class="section-label">超时设置 (TIMEOUT)</div>
        <div class="timeout-row">
          <span class="timeout-text">等待响应时限:</span>
          <el-input-number 
            v-model="timeout" 
            :min="1" 
            :max="168" 
            size="small" 
            :disabled="readOnly" 
            style="width: 90px;"
          />
          <el-select 
            v-model="timeoutUnit" 
            size="small" 
            :disabled="readOnly" 
            style="width: 80px;"
          >
            <el-option label="小时" value="hour" />
            <el-option label="天" value="day" />
          </el-select>
        </div>
      </div>

      <!-- 5. 输出变量透出 (Output Vars) -->
      <div class="form-section output-vars-section">
        <div class="section-label">输出变量 (OUTPUT VARIABLES)</div>
        <div class="var-tags-list">
          <div class="var-tag"><span class="var-name">__action_id</span> <span class="var-type">string</span></div>
          <div class="var-tag"><span class="var-name">__action_value</span> <span class="var-type">string</span></div>
          <div class="var-tag"><span class="var-name">__rendered_content</span> <span class="var-type">string</span></div>
          <div v-for="(inputItem, iIdx) in inputs" :key="iIdx" class="var-tag">
            <span class="var-name">{{ inputItem.output_variable_name || `input_${iIdx}` }}</span> 
            <span class="var-type">{{ outputType(inputItem.type) }}</span>
          </div>
        </div>
      </div>

      <!-- 6. 下游节点串联提示 -->
      <NextStep :node-id="nodeId" :node-data="nodeData" :read-only="readOnly" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, inject } from 'vue'
import { Close, Plus, Delete, View, DocumentCopy } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import BlockIcon from '../base/BlockIcon.vue'
import NextStep from '../shared/NextStep.vue'
import HumanInputEmailConfig from './HumanInputEmailConfig.vue'
import HumanInputContentEditor from './HumanInputContentEditor.vue'
import HumanInputFormPreview from './HumanInputFormPreview.vue'
import {
  applyHumanInputActionIdInput,
  humanInputActionIdErrorMessage,
  humanInputDraftKey,
  pruneHumanInputDrafts,
  removeHumanInputOutputToken,
  renameHumanInputOutputToken,
} from './humanInputNode.js'
import { canAddHumanInputWebApp } from '../../model/workflowEntry.js'
import { 
  useHumanInputConfig, 
  BUTTON_STYLES 
} from './useHumanInputConfig.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false }
})

const emit = defineEmits(['close', 'update:nodeData'])
const graph = inject('workflowGraph', null)
const isPreview = ref(false)
const actionIdDrafts = ref({})

const { 
  readOnly, 
  prompt, 
  deliveryMethods, 
  emailConfig,
  inputs, 
  userActions, 
  timeout, 
  timeoutUnit,
  addUserAction, 
  removeUserAction,
  updateUserAction,
} = useHumanInputConfig(props, (event, val) => {
  emit(event, val)
})

const canvasNodes = computed(() => graph?.nodes?.value || graph?.getNodes?.() || [])
const webAppAddDisabled = computed(() => !canAddHumanInputWebApp(canvasNodes.value, deliveryMethods.value))

function onDeliveryMethodsChange(types) {
  const next = Array.isArray(types) ? types : []
  if (next.includes('webapp') && !canAddHumanInputWebApp(canvasNodes.value, deliveryMethods.value))
    return
  deliveryMethods.value = next
}

const nodeTitle = computed({
  get: () => props.nodeData?.title || '人机交互',
  set: (val) => emit('update:nodeData', { ...props.nodeData, title: val })
})

const copyContent = () => {
  if (navigator.clipboard && prompt.value) {
    navigator.clipboard.writeText(prompt.value)
    ElMessage.success('已复制表单内容到剪贴板')
  }
}

function onRenameField({ oldName, newName }) {
  prompt.value = renameHumanInputOutputToken(prompt.value, oldName, newName)
}

function onRemoveField({ name, oldName }) {
  prompt.value = removeHumanInputOutputToken(prompt.value, name || oldName)
}

function actionDraftKey(act, index) {
  return humanInputDraftKey(act?.id, index)
}

function actionIdDisplay(act, index) {
  return actionIdDrafts.value[actionDraftKey(act, index)]?.display ?? act.id
}

function actionIdError(act, index) {
  const stored = act?.id || ''
  const draft = actionIdDrafts.value[actionDraftKey(act, index)]
  const result = applyHumanInputActionIdInput(
    draft?.display ?? stored,
    userActions.value.map(item => item.id).filter((_, current) => current !== index),
    stored,
  )
  return humanInputActionIdErrorMessage(result.error)
}

function commitActionId(act, index, raw) {
  const stored = act?.id || ''
  const others = userActions.value
    .map(item => item.id)
    .filter((_, current) => current !== index)
  const result = applyHumanInputActionIdInput(raw, others, stored)
  const key = actionDraftKey(act, index)
  if (result.error) {
    actionIdDrafts.value = { ...actionIdDrafts.value, [key]: { display: result.display } }
    return
  }
  const next = { ...actionIdDrafts.value }
  delete next[key]
  actionIdDrafts.value = next
  if (stored === result.id)
    return
  updateUserAction(index, { id: result.id })
}

function onRemoveUserAction(index) {
  const remaining = userActions.value
    .filter((_, current) => current !== index)
    .map((item, current) => actionDraftKey(item, current))
  actionIdDrafts.value = pruneHumanInputDrafts(actionIdDrafts.value, remaining)
  removeUserAction(index)
}

const outputType = type => ({
  paragraph: 'string',
  select: 'string',
  file: 'file',
  'file-list': 'arrayFile',
})[type] || 'string'
</script>

<style scoped>
.hi-panel { 
  display: flex; 
  flex-direction: column; 
  height: 100%; 
  overflow: hidden; 
  background: #fff; 
  border-left: 1px solid #eaecf0; 
}
.panel-header { 
  display: flex; 
  align-items: center; 
  justify-content: space-between; 
  padding: 12px 16px; 
  border-bottom: 1px solid #f2f4f7; 
  background: #fafafa; 
}
.header-left { display: flex; align-items: center; gap: 8px; flex: 1; }
.title-input { font-size: 14px; font-weight: 600; color: #101828; border: none; background: transparent; }
.close-btn { background: transparent; border: none; cursor: pointer; color: #667085; }
.close-btn:focus-visible,
.icon-btn:focus-visible { outline: 2px solid #155eef; outline-offset: 2px; }
.icon-btn { display: inline-flex; align-items: center; justify-content: center; background: transparent; border: none; cursor: pointer; color: #667085; padding: 4px; }

.panel-body { 
  flex: 1; 
  overflow-y: auto; 
  padding: 16px; 
  display: flex; 
  flex-direction: column; 
  gap: 20px; 
}

.form-section { display: flex; flex-direction: column; gap: 8px; }
.section-header { display: flex; align-items: center; justify-content: space-between; }
.section-label { font-size: 11px; font-weight: 700; color: #64748b; letter-spacing: 0.5px; }
.actions-group { display: flex; align-items: center; gap: 6px; }

.checkbox-group { display: flex; flex-direction: column; gap: 6px; }

/* 编辑与预览 */
.editor-wrapper { display: flex; flex-direction: column; }
.preview-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
}
.preview-title { font-weight: 600; color: #475569; margin-bottom: 4px; }
.preview-content { color: #1e293b; white-space: pre-wrap; word-break: break-all; }

/* 按钮列表 */
.actions-list { display: flex; flex-direction: column; gap: 8px; }
.action-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px;
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
.action-field { display: flex; flex: 1; min-width: 0; flex-direction: column; gap: 3px; }
.field-error { color: #d92d20; font-size: 10px; line-height: 1.2; }

.empty-tip {
  font-size: 11px;
  color: #98a2b3;
  font-style: italic;
  background: #fafafa;
  padding: 8px;
  border-radius: 4px;
  border: 1px dashed #eaecf0;
  text-align: center;
}

.timeout-row { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #344054; }
.timeout-text { font-size: 12px; color: #475569; }

/* 输出变量清单 */
.output-vars-section {
  background: #f8fafc;
  border-radius: 8px;
  padding: 10px;
  border: 1px solid #f1f5f9;
}
.var-tags-list { display: flex; flex-direction: column; gap: 4px; }
.var-tag {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  font-family: ui-monospace, monospace;
  background: #ffffff;
  padding: 4px 8px;
  border-radius: 4px;
  border: 1px solid #e2e8f0;
}
.var-name { color: #0f172a; font-weight: 600; }
.var-type { color: #64748b; font-size: 10px; }
</style>
