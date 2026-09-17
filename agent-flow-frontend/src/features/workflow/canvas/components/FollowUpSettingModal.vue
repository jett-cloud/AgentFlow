<template>
  <!-- Contrasts Dify follow-up-setting-modal (model + default/custom prompt). -->
  <div class="follow-up-modal-mask" role="presentation" @click.self="$emit('cancel')">
    <section
      class="follow-up-modal"
      role="dialog"
      aria-modal="true"
      aria-label="回答后建议问题设置"
    >
      <header>
        <h3>回答后建议问题设置</h3>
        <button type="button" aria-label="关闭" @click="$emit('cancel')">×</button>
      </header>

      <div class="body">
        <label class="field">
          <span>模型</span>
          <ModelSelector
            v-model="model"
            :disabled="readOnly"
            placeholder="留空则使用系统默认模型"
          />
          <p class="hint">清空选择即使用租户默认模型。</p>
        </label>

        <div v-if="hasModel" class="params">
          <div class="params-title">生成参数</div>
          <label class="param-row">
            <span>Temperature</span>
            <input
              v-model.number="completionParams.temperature"
              type="number"
              min="0"
              max="2"
              step="0.1"
              :disabled="readOnly"
            >
          </label>
          <label class="param-row">
            <span>Top P</span>
            <input
              v-model.number="completionParams.top_p"
              type="number"
              min="0"
              max="1"
              step="0.05"
              :disabled="readOnly"
            >
          </label>
          <label class="param-row">
            <span>Max Tokens</span>
            <input
              v-model.number="completionParams.max_tokens"
              type="number"
              min="1"
              max="128000"
              step="1"
              :disabled="readOnly"
            >
          </label>
        </div>

        <fieldset class="prompt-modes">
          <legend>提示词</legend>
          <label class="mode-card" :class="{ active: promptMode === 'default' }">
            <input v-model="promptMode" type="radio" value="default" :disabled="readOnly" />
            <div>
              <strong>默认提示词</strong>
              <p>使用系统内置追问指令</p>
              <pre v-if="promptMode === 'default'" class="default-prompt">{{ defaultPrompt }}</pre>
            </div>
          </label>
          <label class="mode-card" :class="{ active: promptMode === 'custom' }">
            <input v-model="promptMode" type="radio" value="custom" :disabled="readOnly" />
            <div>
              <strong>自定义提示词</strong>
              <p>最多 {{ maxPromptLength }} 字</p>
              <textarea
                v-if="promptMode === 'custom'"
                v-model="prompt"
                rows="5"
                :disabled="readOnly"
                :maxlength="maxPromptLength"
                placeholder="输入自定义追问提示词…"
              />
              <p v-if="promptMode === 'custom'" class="hint">{{ prompt.length }} / {{ maxPromptLength }}</p>
            </div>
          </label>
        </fieldset>

        <p v-if="localError" class="error" role="alert">{{ localError }}</p>
      </div>

      <footer>
        <button type="button" class="ghost" @click="$emit('cancel')">取消</button>
        <button
          type="button"
          class="primary"
          :disabled="readOnly || !canSave"
          @click="handleSave"
        >
          确定
        </button>
      </footer>
    </section>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import ModelSelector from '../../nodes/shared/ModelSelector.vue'
import {
  CUSTOM_FOLLOW_UP_PROMPT_MAX_LENGTH,
  DEFAULT_FOLLOW_UP_COMPLETION_PARAMS,
  DEFAULT_FOLLOW_UP_PROMPT,
  normalizeFollowUpModel,
} from '../../model/workflowFeatures.js'

const props = defineProps({
  modelValue: { type: Object, default: null },
  promptValue: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['save', 'cancel'])

const model = ref({ provider: '', name: '', mode: 'chat', completion_params: { ...DEFAULT_FOLLOW_UP_COMPLETION_PARAMS } })
const completionParams = ref({ ...DEFAULT_FOLLOW_UP_COMPLETION_PARAMS })
const prompt = ref('')
const promptMode = ref('default')
const localError = ref('')
const defaultPrompt = DEFAULT_FOLLOW_UP_PROMPT
const maxPromptLength = CUSTOM_FOLLOW_UP_PROMPT_MAX_LENGTH

const hasModel = computed(() => Boolean(model.value?.provider && model.value?.name))

function syncFromProps() {
  const normalized = normalizeFollowUpModel(props.modelValue)
  model.value = normalized
    ? { ...normalized, completion_params: { ...DEFAULT_FOLLOW_UP_COMPLETION_PARAMS, ...(normalized.completion_params || {}) } }
    : { provider: '', name: '', mode: 'chat', completion_params: { ...DEFAULT_FOLLOW_UP_COMPLETION_PARAMS } }
  completionParams.value = {
    ...DEFAULT_FOLLOW_UP_COMPLETION_PARAMS,
    ...(model.value.completion_params || {}),
  }
  prompt.value = props.promptValue || ''
  promptMode.value = prompt.value.trim() ? 'custom' : 'default'
  localError.value = ''
}

watch(() => [props.modelValue, props.promptValue], syncFromProps, { immediate: true })

watch(model, (next) => {
  if (!next?.provider || !next?.name)
    return
  completionParams.value = {
    ...DEFAULT_FOLLOW_UP_COMPLETION_PARAMS,
    ...(next.completion_params || {}),
  }
}, { deep: true })

const canSave = computed(() => {
  if (promptMode.value !== 'custom')
    return true
  const trimmed = prompt.value.trim()
  return Boolean(trimmed) && trimmed.length <= maxPromptLength
})

function handleSave() {
  localError.value = ''
  if (promptMode.value === 'custom') {
    const trimmed = prompt.value.trim()
    if (!trimmed) {
      localError.value = '自定义提示词不能为空'
      return
    }
    if (trimmed.length > maxPromptLength) {
      localError.value = `提示词不能超过 ${maxPromptLength} 字`
      return
    }
  }
  const normalized = normalizeFollowUpModel({
    ...model.value,
    completion_params: {
      ...DEFAULT_FOLLOW_UP_COMPLETION_PARAMS,
      temperature: Number(completionParams.value.temperature) || 0.7,
      top_p: Number(completionParams.value.top_p) || 1,
      max_tokens: Math.max(1, Number(completionParams.value.max_tokens) || 512),
    },
  })
  emit('save', {
    model: normalized || null,
    prompt: promptMode.value === 'custom' ? prompt.value.trim() : '',
  })
}
</script>

<style scoped>
.follow-up-modal-mask {
  position: absolute;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgb(16 24 40 / 35%);
}

.follow-up-modal {
  display: flex;
  width: min(520px, 100%);
  max-height: min(560px, 100%);
  flex-direction: column;
  overflow: hidden;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 16px 40px rgb(16 24 40 / 18%);
}

header,
footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 14px;
}

header {
  border-bottom: 1px solid #f2f4f7;
}

footer {
  justify-content: flex-end;
  border-top: 1px solid #f2f4f7;
}

header h3 {
  margin: 0;
  color: #101828;
  font-size: 14px;
}

header button {
  border: 0;
  background: transparent;
  color: #667085;
  font-size: 18px;
  cursor: pointer;
}

.body {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  gap: 14px;
  overflow: auto;
  padding: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #344054;
  font-size: 12px;
}

.params {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid #eaecf0;
  border-radius: 10px;
  background: #f9fafb;
}

.params-title {
  color: #344054;
  font-size: 12px;
  font-weight: 600;
}

.param-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #475467;
  font-size: 12px;
}

.param-row input {
  width: 96px;
  padding: 5px 8px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  font: inherit;
}

.prompt-modes {
  margin: 0;
  padding: 0;
  border: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.prompt-modes legend {
  margin-bottom: 4px;
  color: #344054;
  font-size: 12px;
  font-weight: 600;
}

.mode-card {
  display: flex;
  gap: 10px;
  padding: 10px;
  border: 1px solid #eaecf0;
  border-radius: 10px;
  cursor: pointer;
}

.mode-card.active {
  border-color: #b2ccff;
  background: #f5f8ff;
}

.mode-card strong {
  display: block;
  color: #101828;
  font-size: 12px;
}

.mode-card p {
  margin: 2px 0 0;
  color: #667085;
  font-size: 11px;
}

.mode-card textarea,
.default-prompt {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-top: 8px;
  padding: 8px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #f9fafb;
  color: #344054;
  font: 11px/1.45 ui-monospace, Consolas, monospace;
  white-space: pre-wrap;
}

.default-prompt {
  max-height: 120px;
  overflow: auto;
  margin: 8px 0 0;
}

.hint {
  margin: 0;
  color: #98a2b3;
  font-size: 11px;
}

.error {
  margin: 0;
  padding: 6px 8px;
  border-radius: 7px;
  background: #fef3f2;
  color: #b42318;
  font-size: 11px;
}

.ghost,
.primary {
  padding: 7px 12px;
  border: 0;
  border-radius: 7px;
  font-size: 12px;
  cursor: pointer;
}

.ghost {
  background: #f2f4f7;
  color: #344054;
}

.primary {
  background: #0033ff;
  color: #fff;
}

.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
