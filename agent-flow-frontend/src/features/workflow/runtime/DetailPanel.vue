<template>
  <!-- Aligns with Dify ResultPanel = Status + Inputs/Process/Outputs + Meta. -->
  <div class="detail-panel">
    <section class="status-strip" :data-status="runStatus">
      <div class="row">
        <span class="label">STATUS</span>
        <strong>{{ statusLabel }}</strong>
      </div>
      <div class="row">
        <span class="label">ELAPSED</span>
        <span>{{ elapsedLabel || '—' }}</span>
      </div>
      <div class="row">
        <span class="label">TOKENS</span>
        <span>{{ tokensLabel }}</span>
      </div>
      <div class="row">
        <span class="label">STEPS</span>
        <span>{{ stepsLabel }}</span>
      </div>
    </section>

    <div v-if="runError" class="error">{{ runError }}</div>
    <button
      v-if="showTracingHint"
      type="button"
      class="hint-btn"
      @click="$emit('go-tracing')"
    >
      查看 TRACING 了解节点异常详情 →
    </button>

    <h3>INPUT</h3>
    <pre class="body">{{ formatJsonValue(result?.inputs) }}</pre>

    <template v-if="result?.process_data">
      <h3>PROCESS DATA</h3>
      <pre class="body">{{ formatJsonValue(result.process_data) }}</pre>
    </template>

    <h3>OUTPUT</h3>
    <pre class="body">{{ formatJsonValue(result?.outputs) }}</pre>

    <h3>META</h3>
    <dl class="meta">
      <div>
        <dt>Task ID</dt>
        <dd class="mono">{{ taskId || '—' }}</dd>
      </div>
      <div>
        <dt>Start Time</dt>
        <dd>{{ startTimeLabel }}</dd>
      </div>
      <div>
        <dt>Executor</dt>
        <dd>{{ executorLabel }}</dd>
      </div>
    </dl>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  extractTotalTokens,
  formatElapsed,
  formatJsonValue,
  RUN_STATUS,
} from './applyWorkflowRunEvent.js'

const props = defineProps({
  runStatus: { type: String, default: '' },
  taskId: { type: String, default: '' },
  runError: { type: String, default: '' },
  result: { type: Object, default: null },
  tracingCount: { type: Number, default: 0 },
})

defineEmits(['go-tracing'])

const statusLabel = computed(() => ({
  [RUN_STATUS.idle]: '待运行',
  [RUN_STATUS.running]: '运行中',
  [RUN_STATUS.succeeded]: '成功',
  [RUN_STATUS.failed]: '失败',
  [RUN_STATUS.stopped]: '已停止',
  [RUN_STATUS.paused]: '已暂停',
  exception: '异常',
}[props.runStatus] || props.runStatus || '—'))

const elapsedLabel = computed(() => formatElapsed(props.result?.elapsed_time))
const tokensLabel = computed(() => {
  const tokens = extractTotalTokens(props.result)
  return tokens == null ? '—' : String(tokens)
})
const stepsLabel = computed(() => {
  const steps = props.result?.total_steps ?? props.tracingCount
  return steps == null ? '—' : String(steps)
})
const showTracingHint = computed(() => (
  props.runStatus === RUN_STATUS.failed
  || props.runStatus === 'exception'
  || !!props.runError
))
const startTimeLabel = computed(() => {
  const ts = props.result?.created_at || props.result?.finished_at
  if (!ts)
    return '—'
  const ms = typeof ts === 'number' ? (ts < 1e12 ? ts * 1000 : ts) : Date.parse(ts)
  if (!Number.isFinite(ms))
    return String(ts)
  return new Date(ms).toLocaleString()
})
const executorLabel = computed(() => (
  props.result?.created_by_end_user?.name
  || props.result?.created_by_account?.name
  || props.result?.created_by
  || '—'
))
</script>

<style scoped>
.detail-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.status-strip {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 10px;
  border-radius: 10px;
  background: #f9fafb;
  border: 1px solid #eaecf0;
}
.status-strip[data-status='succeeded'] { border-color: #abefc6; background: #f6fef9; }
.status-strip[data-status='failed'] { border-color: #fecdca; background: #fef3f2; }
.status-strip[data-status='running'] { border-color: #b2ccff; background: #f5f8ff; }
.row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: #101828;
}
.label {
  color: #98a2b3;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.error {
  padding: 8px 10px;
  border-radius: 8px;
  background: #fef3f2;
  color: #b42318;
  font-size: 12px;
}
.hint-btn {
  align-self: flex-start;
  padding: 0;
  border: 0;
  background: transparent;
  color: #0033ff;
  font-size: 12px;
  cursor: pointer;
}
h3 {
  margin: 4px 0 0;
  color: #667085;
  font-size: 11px;
  text-transform: uppercase;
}
.body {
  margin: 0;
  max-height: 180px;
  overflow: auto;
  padding: 10px;
  border-radius: 8px;
  background: #f2f4f7;
  color: #101828;
  font: 11px/1.5 ui-monospace, Consolas, monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.meta {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.meta > div {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 8px;
  font-size: 12px;
}
dt { color: #667085; margin: 0; }
dd { margin: 0; color: #101828; word-break: break-all; }
.mono { font-family: ui-monospace, Consolas, monospace; }
</style>
