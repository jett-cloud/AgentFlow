<template>
  <!-- Contrasts Dify file-upload setting-content (types / methods / max_length). -->
  <div class="file-upload-modal-mask" role="presentation" @click.self="$emit('cancel')">
    <section
      class="file-upload-modal"
      role="dialog"
      aria-modal="true"
      aria-label="文件上传设置"
    >
      <header>
        <h3>文件上传设置</h3>
        <button type="button" aria-label="关闭" @click="$emit('cancel')">×</button>
      </header>

      <div class="body">
        <fieldset class="group">
          <legend>支持的文件类型</legend>
          <label
            v-for="option in typeOptions"
            :key="option.value"
            class="check-row"
          >
            <input
              v-model="types"
              type="checkbox"
              :value="option.value"
              :disabled="readOnly"
            >
            <span>{{ option.label }}</span>
          </label>
        </fieldset>

        <fieldset class="group">
          <legend>上传方式</legend>
          <label
            v-for="option in methodOptions"
            :key="option.value"
            class="check-row"
          >
            <input
              v-model="methods"
              type="checkbox"
              :value="option.value"
              :disabled="readOnly"
            >
            <span>{{ option.label }}</span>
          </label>
        </fieldset>

        <label class="field">
          <span>单次最多上传数量（1–{{ maxLimit }}）</span>
          <input
            v-model.number="numberLimits"
            type="number"
            min="1"
            :max="maxLimit"
            :disabled="readOnly"
          >
        </label>

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
import {
  FILE_UPLOAD_METHOD_OPTIONS,
  FILE_UPLOAD_TYPE_OPTIONS,
  MAX_FILE_UPLOAD_LIMIT,
  clampFileUploadNumberLimits,
  normalizeFileUploadMethods,
  normalizeFileUploadTypes,
} from '../../model/workflowFeatures.js'

const props = defineProps({
  types: { type: Array, default: () => ['image'] },
  methods: { type: Array, default: () => ['local_file', 'remote_url'] },
  numberLimits: { type: Number, default: 3 },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['save', 'cancel'])

const types = ref(['image'])
const methods = ref(['local_file', 'remote_url'])
const numberLimits = ref(3)
const localError = ref('')
const typeOptions = FILE_UPLOAD_TYPE_OPTIONS
const methodOptions = FILE_UPLOAD_METHOD_OPTIONS
const maxLimit = MAX_FILE_UPLOAD_LIMIT

function syncFromProps() {
  const nextTypes = normalizeFileUploadTypes(props.types)
  types.value = nextTypes.length ? nextTypes : ['image']
  methods.value = normalizeFileUploadMethods(props.methods)
  numberLimits.value = clampFileUploadNumberLimits(props.numberLimits)
  localError.value = ''
}

watch(
  () => [props.types, props.methods, props.numberLimits],
  syncFromProps,
  { immediate: true, deep: true },
)

const canSave = computed(() => (
  normalizeFileUploadTypes(types.value).length > 0
  && Array.isArray(methods.value)
  && methods.value.some(m => m === 'local_file' || m === 'remote_url')
))

function handleSave() {
  localError.value = ''
  const nextTypes = normalizeFileUploadTypes(types.value)
  const rawMethods = (Array.isArray(methods.value) ? methods.value : [])
    .filter(m => m === 'local_file' || m === 'remote_url')
  if (!nextTypes.length) {
    localError.value = '请至少选择一种文件类型'
    return
  }
  if (!rawMethods.length) {
    localError.value = '请至少选择一种上传方式'
    return
  }
  emit('save', {
    types: nextTypes,
    methods: normalizeFileUploadMethods(rawMethods),
    numberLimits: clampFileUploadNumberLimits(numberLimits.value),
  })
}
</script>

<style scoped>
.file-upload-modal-mask {
  position: absolute;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgb(16 24 40 / 35%);
}

.file-upload-modal {
  display: flex;
  width: min(420px, 100%);
  max-height: min(520px, 100%);
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

.group {
  margin: 0;
  padding: 0;
  border: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.group legend {
  margin-bottom: 4px;
  color: #344054;
  font-size: 12px;
  font-weight: 600;
}

.check-row {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #344054;
  font-size: 12px;
  cursor: pointer;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #344054;
  font-size: 12px;
}

.field input[type='number'] {
  width: 100px;
  padding: 7px 9px;
  border: 1px solid #d0d5dd;
  border-radius: 7px;
  font: inherit;
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
