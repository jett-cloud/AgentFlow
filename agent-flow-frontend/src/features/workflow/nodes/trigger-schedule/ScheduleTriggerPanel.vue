<template>
  <NodePanelShell v-bind="shellProps" block-type="trigger-schedule" @close="$emit('close')" @update:node-data="emitUpdate">
    <PanelSection label="配置方式">
      <el-radio-group :model-value="mode" :disabled="readOnly" @change="onModeChange">
        <el-radio-button label="visual">可视化</el-radio-button>
        <el-radio-button label="cron">Cron</el-radio-button>
      </el-radio-group>
    </PanelSection>

    <template v-if="mode === 'visual'">
      <PanelSection label="频率" required>
        <el-select
          :model-value="frequency"
          :disabled="readOnly"
          @change="onFrequencyChange"
        >
          <el-option label="每小时" value="hourly" />
          <el-option label="每天" value="daily" />
          <el-option label="每周" value="weekly" />
          <el-option label="每月" value="monthly" />
        </el-select>
      </PanelSection>

      <PanelSection v-if="frequency === 'hourly'" label="第几分钟">
        <el-slider
          :model-value="visualConfig.on_minute"
          :min="0"
          :max="59"
          :disabled="readOnly"
          @update:model-value="patchVisual({ on_minute: $event })"
        />
        <p class="hint">每小时的第 {{ visualConfig.on_minute }} 分钟触发</p>
      </PanelSection>

      <PanelSection v-else label="时间">
        <el-input
          :model-value="visualConfig.time"
          type="time"
          :disabled="readOnly"
          @input="patchVisual({ time: $event })"
        />
      </PanelSection>

      <PanelSection v-if="frequency === 'weekly'" label="星期">
        <el-checkbox-group
          :model-value="visualConfig.weekdays"
          :disabled="readOnly"
          @change="patchVisual({ weekdays: $event })"
        >
          <el-checkbox v-for="day in weekdayOptions" :key="day.value" :label="day.value">
            {{ day.label }}
          </el-checkbox>
        </el-checkbox-group>
      </PanelSection>

      <PanelSection v-if="frequency === 'monthly'" label="每月日期">
        <el-select
          :model-value="visualConfig.monthly_days"
          multiple
          filterable
          :disabled="readOnly"
          @change="patchVisual({ monthly_days: $event })"
        >
          <el-option v-for="n in 31" :key="n" :label="`${n} 日`" :value="n" />
        </el-select>
      </PanelSection>

      <PanelSection label="生成的 Cron">
        <code class="cron-preview">{{ previewCron }}</code>
      </PanelSection>
    </template>

    <template v-else>
      <PanelSection label="Cron 表达式" required>
        <el-input
          :model-value="nodeData.cron || nodeData.cron_expression"
          name="schedule-cron"
          autocomplete="off"
          placeholder="例如 0 0 * * *…"
          :disabled="readOnly"
          @input="updateCron"
        />
      </PanelSection>
      <PanelSection label="常用模板">
        <div class="preset-row">
          <el-button size="small" :disabled="readOnly" @click="applyPreset('0 * * * *')">每小时</el-button>
          <el-button size="small" :disabled="readOnly" @click="applyPreset('0 9 * * *')">每天 09:00</el-button>
          <el-button size="small" :disabled="readOnly" @click="applyPreset('0 9 * * 1')">每周一 09:00</el-button>
        </div>
      </PanelSection>
    </template>

    <PanelSection label="时区">
      <el-select
        :model-value="nodeData.timezone || 'Asia/Shanghai'"
        filterable
        allow-create
        :disabled="readOnly"
        @change="updateField('timezone', $event)"
      >
        <el-option label="Asia/Shanghai" value="Asia/Shanghai" />
        <el-option label="UTC" value="UTC" />
        <el-option label="America/New_York" value="America/New_York" />
      </el-select>
    </PanelSection>
    <PanelSection label="启用">
      <el-switch
        :model-value="nodeData.enabled !== false"
        :disabled="readOnly"
        @change="updateField('enabled', $event)"
      />
    </PanelSection>
  </NodePanelShell>
</template>

<script setup>
import { computed } from 'vue'
import NodePanelShell from '../shared/NodePanelShell.vue'
import PanelSection from '../shared/PanelSection.vue'
import {
  buildCronFromVisual,
  getDefaultVisualConfig,
  resolveScheduleCron,
} from './scheduleTrigger.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:nodeData'])

const weekdayOptions = [
  { value: '0', label: '日' },
  { value: '1', label: '一' },
  { value: '2', label: '二' },
  { value: '3', label: '三' },
  { value: '4', label: '四' },
  { value: '5', label: '五' },
  { value: '6', label: '六' },
]

const shellProps = computed(() => ({ nodeId: props.nodeId, nodeData: props.nodeData, readOnly: props.readOnly }))
const mode = computed(() => props.nodeData.mode || (props.nodeData.cron || props.nodeData.cron_expression ? 'cron' : 'visual'))
const frequency = computed(() => props.nodeData.frequency || 'daily')
const visualConfig = computed(() => ({
  ...getDefaultVisualConfig(),
  ...(props.nodeData.visual_config || {}),
}))
const previewCron = computed(() => resolveScheduleCron({
  mode: 'visual',
  frequency: frequency.value,
  visual_config: visualConfig.value,
}))

function emitUpdate(data) {
  emit('update:nodeData', data)
}
function updateField(field, value) {
  emitUpdate({ ...props.nodeData, [field]: value })
}
function updateCron(value) {
  emitUpdate({
    ...props.nodeData,
    mode: 'cron',
    cron: value,
    cron_expression: undefined,
  })
}
function applyPreset(value) {
  updateCron(value)
}
function onModeChange(nextMode) {
  if (nextMode === 'visual') {
    const nextVisual = props.nodeData.visual_config || getDefaultVisualConfig()
    const cron = buildCronFromVisual({
      frequency: props.nodeData.frequency || 'daily',
      visual_config: nextVisual,
    })
    emitUpdate({
      ...props.nodeData,
      mode: 'visual',
      frequency: props.nodeData.frequency || 'daily',
      visual_config: nextVisual,
      cron,
      cron_expression: undefined,
    })
    return
  }
  emitUpdate({
    ...props.nodeData,
    mode: 'cron',
    cron: props.nodeData.cron || props.nodeData.cron_expression || previewCron.value,
  })
}
function onFrequencyChange(nextFrequency) {
  const nextVisual = { ...visualConfig.value }
  const cron = buildCronFromVisual({ frequency: nextFrequency, visual_config: nextVisual })
  emitUpdate({
    ...props.nodeData,
    mode: 'visual',
    frequency: nextFrequency,
    visual_config: nextVisual,
    cron,
    cron_expression: undefined,
  })
}
function patchVisual(partial) {
  const nextVisual = { ...visualConfig.value, ...partial }
  const cron = buildCronFromVisual({ frequency: frequency.value, visual_config: nextVisual })
  emitUpdate({
    ...props.nodeData,
    mode: 'visual',
    frequency: frequency.value,
    visual_config: nextVisual,
    cron,
    cron_expression: undefined,
  })
}
</script>

<style scoped>
.preset-row { display:flex; flex-wrap:wrap; gap:6px; }
.hint { margin: 6px 0 0; font-size: 12px; color: #667085; }
.cron-preview {
  display: block;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f9fafb;
  color: #155eef;
  font-size: 12px;
}
</style>
