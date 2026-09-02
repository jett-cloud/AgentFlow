<template>
  <div class="tt-panel">
    <div class="panel-header">
      <div class="header-left">
        <BlockIcon type="template-transform" :size="20" />
        <input v-model="nodeTitle" class="title-input" placeholder="模板转换" :disabled="readOnly" />
      </div>
      <button class="close-btn" type="button" aria-label="关闭面板" @click="$emit('close')">
        <el-icon><Close /></el-icon>
      </button>
    </div>

    <div class="panel-body">
      <div class="form-section">
        <div class="section-header-flex">
          <label class="section-label">输入变量 (Input Variables)</label>
          <button v-if="!readOnly" class="add-btn" type="button" aria-label="添加输入变量" @click="handleAddVar">
            <el-icon><Plus /></el-icon>
          </button>
        </div>

        <div v-if="!variables.length" class="empty-hint">添加变量并绑定上游值，然后在模板中引用变量名。</div>
        <div v-else class="var-list">
          <div v-for="(variable, index) in variables" :key="index" class="var-card">
            <div class="var-row">
              <el-input
                :model-value="variable.variable"
                placeholder="变量名"
                :disabled="readOnly"
                @update:model-value="handleUpdateVarName(index, $event)"
              />
              <span class="mapping-arrow">←</span>
              <VarReferencePicker
                :model-value="variable.value_selector"
                :node-id="nodeId"
                :read-only="readOnly"
                :filter-var="templateInputFilter"
                placeholder="选择上游变量"
                @update:model-value="handleUpdateVarSelector(index, $event)"
              />
              <button
                v-if="!readOnly"
                class="del-btn"
                type="button"
                aria-label="删除输入变量"
                @click="handleRemoveVar(index)"
              >
                <el-icon><Delete /></el-icon>
              </button>
            </div>
            <div class="var-meta">
              <span>{{ variable.value_type || '未识别类型' }}</span>
              <button
                type="button"
                class="insert-btn"
                :disabled="!variable.variable"
                @click="insertVariable(variable.variable)"
              >
                插入 <code>{{ templateToken(variable.variable || 'variable') }}</code>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="form-section">
        <div class="template-title-row">
          <label class="section-label">模板内容 (Jinja2)</label>
          <a href="https://jinja.palletsprojects.com/en/3.1.x/templates/" target="_blank" rel="noopener noreferrer">Jinja2 语法</a>
        </div>
        <p class="jinja-tip">使用映射名，例如 <code v-text="templateToken('query')" />。上游节点变化后，检查清单会提示失效引用。</p>
        <el-input
          ref="templateInputRef"
          v-model="template"
          type="textarea"
          :rows="9"
          placeholder="例如：你好，{{ query }}"
          class="font-mono text-xs"
          :disabled="readOnly"
        />
      </div>

      <div class="output-section">
        <span class="section-label">输出变量 (Output Variables)</span>
        <div class="output-item"><code>output</code><span>String</span></div>
      </div>

      <NextStep :node-id="nodeId" :node-data="nodeData" :read-only="readOnly" />
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { Close, Delete, Plus } from '@element-plus/icons-vue'
import BlockIcon from '../base/BlockIcon.vue'
import NextStep from '../shared/NextStep.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import { useTemplateTransformConfig } from './useTemplateTransformConfig.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:nodeData'])

const {
  readOnly,
  template,
  variables,
  templateInputFilter,
  handleAddVar,
  handleUpdateVarName,
  handleUpdateVarSelector,
  handleRemoveVar,
} = useTemplateTransformConfig(props, emit)

const templateInputRef = ref(null)
const nodeTitle = computed({
  get: () => props.nodeData?.title || '模板转换',
  set: title => emit('update:nodeData', { ...props.nodeData, title }),
})

function insertVariable(name) {
  if (!name)
    return
  const token = `{{ ${name} }}`
  const textarea = templateInputRef.value?.textarea
  if (!textarea || typeof textarea.selectionStart !== 'number') {
    template.value = `${template.value}${token}`
    return
  }
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  template.value = `${template.value.slice(0, start)}${token}${template.value.slice(end)}`
  nextTick(() => {
    textarea.focus()
    textarea.setSelectionRange(start + token.length, start + token.length)
  })
}

function templateToken(name) {
  return `{{ ${name} }}`
}
</script>

<style scoped>
.tt-panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: #fff; border-left: 1px solid #eaecf0; }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid #f2f4f7; background: #fafafa; }
.header-left { display: flex; align-items: center; gap: 8px; flex: 1; }
.title-input { font-size: 14px; font-weight: 600; color: #101828; border: none; background: transparent; }
.close-btn, .add-btn, .del-btn, .insert-btn { border: 0; background: transparent; cursor: pointer; }
.close-btn, .add-btn { color: #667085; }
.panel-body { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.form-section, .output-section { display: flex; flex-direction: column; gap: 8px; }
.section-header-flex, .template-title-row, .var-row, .var-meta, .output-item { display: flex; align-items: center; }
.section-header-flex, .template-title-row, .var-meta, .output-item { justify-content: space-between; }
.section-label { font-size: 12px; font-weight: 600; color: #344054; }
.var-list { display: flex; flex-direction: column; gap: 8px; }
.var-card { padding: 8px; border: 1px solid #eaecf0; border-radius: 8px; background: #f9fafb; }
.var-row { gap: 6px; }
.var-row :deep(.el-input) { width: 112px; flex: 0 0 112px; }
.var-row :deep(.var-ref-picker) { min-width: 0; flex: 1; }
.mapping-arrow { color: #98a2b3; }
.del-btn { color: #98a2b3; }
.del-btn:hover { color: #f04438; }
.var-meta { margin-top: 6px; color: #98a2b3; font-size: 10px; }
.insert-btn { color: #155eef; font-size: 11px; }
.insert-btn:disabled { color: #98a2b3; cursor: not-allowed; }
.empty-hint, .jinja-tip { margin: 0; color: #667085; font-size: 11px; line-height: 1.5; }
.template-title-row a { color: #667085; font-size: 11px; text-decoration: none; }
.output-item { padding: 8px 10px; border: 1px solid #eaecf0; border-radius: 8px; color: #667085; font-size: 11px; }
.output-item code { color: #155eef; }
</style>
