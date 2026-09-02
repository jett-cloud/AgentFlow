<template>
  <!-- Aligns with Dify workflow-panel/last-run + before-run-form (simplified). -->
  <div class="last-run-panel">
    <div class="toolbar">
      <button
        type="button"
        class="run-btn"
        :disabled="running || readOnly"
        @click="submitRun"
      >
        {{ running ? '运行中…' : '运行此节点' }}
      </button>
      <button type="button" class="ghost-btn" :disabled="loading" @click="reload">刷新</button>
    </div>

    <label class="field">
      <span>运行输入 (JSON)</span>
      <textarea
        v-model="inputsText"
        rows="6"
        :disabled="running || readOnly"
        spellcheck="false"
        placeholder='{ "key": "value" }'
      />
      <small v-if="inputsError" class="error">{{ inputsError }}</small>
    </label>

    <div v-if="loading" class="state">加载上次运行…</div>
    <div v-else-if="!displayResult && !running" class="state empty">
      <p>还没有运行记录。填写输入后点击「运行此节点」。</p>
    </div>
    <div v-else class="result">
      <div class="meta">
        <span class="status" :data-status="displayStatus">{{ statusLabel }}</span>
        <span v-if="elapsedLabel" class="badge">{{ elapsedLabel }}</span>
        <span v-if="tokensLabel" class="badge">{{ tokensLabel }}</span>
      </div>
      <div v-if="displayError" class="error-box">{{ displayError }}</div>

      <h3>Inputs</h3>
      <pre class="body">{{ formatValue(displayResult?.inputs) }}</pre>

      <h3 v-if="displayResult?.process_data">Process Data</h3>
      <pre v-if="displayResult?.process_data" class="body">{{ formatValue(displayResult.process_data) }}</pre>

      <h3>Outputs</h3>
      <pre class="body">{{ formatValue(displayResult?.outputs) }}</pre>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { fetchNodeLastRun } from '@/features/workflow/api/difyWorkflowApi.js'

const props = defineProps({
  appId: { type: String, default: '' },
  nodeId: { type: String, required: true },
  nodeData: { type: Object, default: () => ({}) },
  /** Latest result from this session's single-node run (overrides GET until refresh). */
  liveResult: { type: Object, default: null },
  running: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['run'])

const loading = ref(false)
const lastRun = ref(null)
const inputsText = ref('{}')
const inputsError = ref('')

const displayResult = computed(() => props.liveResult || lastRun.value)
const displayStatus = computed(() => {
  if (props.running)
    return 'running'
  return displayResult.value?.status || ''
})
const displayError = computed(() => {
  const err = displayResult.value?.error
  if (!err)
    return ''
  return typeof err === 'string' ? err : (err.message || String(err))
})
const statusLabel = computed(() => ({
  running: '运行中',
  succeeded: '成功',
  failed: '失败',
  stopped: '已停止',
  exception: '异常',
}[displayStatus.value] || displayStatus.value || '—'))

const elapsedLabel = computed(() => {
  const t = displayResult.value?.elapsed_time
  if (t === undefined || t === null)
    return ''
  return `${Number(t).toFixed(3)}s`
})
const tokensLabel = computed(() => {
  const tokens = displayResult.value?.execution_metadata?.total_tokens
  if (tokens === undefined || tokens === null)
    return ''
  return `${tokens} tokens`
})

function formatValue(value) {
  if (value === undefined || value === null)
    return '—'
  if (typeof value === 'string')
    return value
  try {
    return JSON.stringify(value, null, 2)
  }
  catch {
    return String(value)
  }
}

async function reload() {
  if (!props.appId || !props.nodeId)
    return
  loading.value = true
  try {
    lastRun.value = await fetchNodeLastRun(props.appId, props.nodeId)
    if (lastRun.value?.inputs && typeof lastRun.value.inputs === 'object')
      inputsText.value = JSON.stringify(lastRun.value.inputs, null, 2)
  }
  catch (error) {
    if (error.response?.status === 404)
      lastRun.value = null
    else
      lastRun.value = null
  }
  finally {
    loading.value = false
  }
}

function submitRun() {
  inputsError.value = ''
  let inputs = {}
  try {
    const parsed = JSON.parse(inputsText.value || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
      throw new Error('输入必须是 JSON 对象')
    inputs = parsed
  }
  catch (error) {
    inputsError.value = error.message || 'JSON 无效'
    return
  }
  emit('run', { nodeId: props.nodeId, inputs })
}

watch(
  () => [props.appId, props.nodeId],
  () => {
    inputsText.value = '{}'
    lastRun.value = null
    reload()
  },
  { immediate: true },
)
</script>

<style scoped>
.last-run-panel {
  display: flex;
  height: 100%;
  box-sizing: border-box;
  flex-direction: column;
  gap: 12px;
  overflow: auto;
  padding: 16px 20px 24px;
}
.toolbar {
  display: flex;
  gap: 8px;
}
.run-btn,
.ghost-btn {
  height: 32px;
  padding: 0 12px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
}
.run-btn {
  border: 0;
  background: #0033ff;
  color: #fff;
}
.run-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.ghost-btn {
  border: 1px solid #eaecf0;
  background: #fff;
  color: #344054;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #344054;
  font-size: 12px;
  font-weight: 600;
}
.field textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  padding: 10px;
  border: 1px solid #eaecf0;
  border-radius: 8px;
  background: #f9fafb;
  color: #101828;
  font: 12px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace;
}
.field .error {
  color: #d92d20;
  font-weight: 500;
}
.state {
  color: #667085;
  font-size: 13px;
  line-height: 1.5;
}
.state.empty {
  padding: 16px;
  border: 1px dashed #eaecf0;
  border-radius: 10px;
  background: #f9fafb;
}
.result {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.status {
  font-size: 12px;
  font-weight: 600;
  color: #667085;
}
.status[data-status='succeeded'] { color: #079455; }
.status[data-status='failed'],
.status[data-status='exception'] { color: #d92d20; }
.status[data-status='running'] { color: #0033ff; }
.badge {
  padding: 2px 6px;
  border-radius: 999px;
  background: #eff4ff;
  color: #155eef;
  font-size: 10px;
}
.error-box {
  padding: 8px 10px;
  border-radius: 8px;
  background: #fef3f2;
  color: #b42318;
  font-size: 12px;
}
h3 {
  margin: 4px 0 0;
  color: #667085;
  font-size: 11px;
  text-transform: uppercase;
}
.body {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  padding: 10px;
  border-radius: 8px;
  background: #f2f4f7;
  color: #101828;
  font: 12px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
