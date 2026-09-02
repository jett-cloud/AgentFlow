<template>
  <NodePanelShell v-bind="shellProps" block-type="agent" @close="$emit('close')" @update:node-data="emitUpdate">
    <PanelSection label="绑定方式" required>
      <!-- TODO(roster): 工作区 Roster Agent 选择尚未实现。打开 ROSTER_BINDING_ENABLED
           后恢复「从 Roster 选择」单选项和下面的 Roster Agent 下拉框。 -->
      <el-radio-group
        v-if="ROSTER_BINDING_ENABLED"
        :model-value="bindingType"
        :disabled="readOnly || bindingBusy"
        @change="onBindingTypeChange"
      >
        <el-radio-button label="inline_agent">内联 Agent</el-radio-button>
        <el-radio-button label="roster_agent">从 Roster 选择</el-radio-button>
      </el-radio-group>
      <p v-if="bindingType === 'inline_agent' || !ROSTER_BINDING_ENABLED" class="hint" :class="{ error: !!bindingError }">
        <template v-if="bindingBusy">正在创建内联 Agent 绑定…</template>
        <template v-else-if="bindingError">
          {{ bindingError }}
          <el-button size="small" text type="primary" :disabled="readOnly" @click="ensureInlineBinding">重试</el-button>
        </template>
        <template v-else-if="inlineReady">已绑定 · {{ shortId(nodeData.agent_binding?.agent_id) }}</template>
        <template v-else>打开面板后将自动创建 inline binding</template>
      </p>
      <p v-else class="hint">Roster Agent 的 Soul（模型/工具/知识库）只读；本节点只编辑任务与输出。</p>
    </PanelSection>

    <PanelSection v-if="ROSTER_BINDING_ENABLED && bindingType === 'roster_agent'" label="Roster Agent" required>
      <el-select
        :model-value="rosterAgentId"
        filterable
        class="w-full"
        placeholder="选择已发布的 Agent"
        :disabled="readOnly || rosterLoading"
        @change="onRosterSelect"
      >
        <el-option
          v-for="agent in rosterAgents"
          :key="agent.id"
          :label="agent.name || agent.id"
          :value="agent.id"
        />
      </el-select>
      <p v-if="rosterError" class="hint error">{{ rosterError }}</p>
    </PanelSection>

    <PanelSection label="任务说明 (agent_task)">
      <el-input
        :model-value="nodeData.agent_task || ''"
        type="textarea"
        :rows="4"
        placeholder="描述此节点希望 Agent 完成的任务…"
        :disabled="readOnly"
        @input="updateField('agent_task', $event)"
      />
    </PanelSection>

    <PanelSection label="模型（Composer Soul）">
      <ModelSelector
        :model-value="soulModel"
        :read-only="!soulEditable"
        @update:model-value="onSoulModelChange"
      />
    </PanelSection>

    <PanelSection label="系统指令（Soul Prompt）">
      <el-input
        :model-value="soulPrompt"
        type="textarea"
        :rows="5"
        placeholder="Agent 系统提示词…"
        :disabled="!soulEditable || !resolvedAppId || (bindingType === 'inline_agent' && !inlineReady)"
        @input="onSoulPromptInput"
      />
    </PanelSection>

    <AgentToolsSection
      :tools="soulTools"
      :read-only="!soulEditable"
      @update:tools="onSoulToolsChange"
    />

    <AgentKnowledgeSection
      :sets="soulKnowledgeSets"
      :read-only="!soulEditable"
      @update:sets="onSoulKnowledgeChange"
    />

    <PanelSection label="声明输出变量">
      <OutputVarList :vars="outputPanelVars" />
      <div v-if="!readOnly" class="output-add">
        <el-input v-model="newOutputName" size="small" placeholder="变量名" />
        <el-select v-model="newOutputType" size="small" style="width: 110px">
          <el-option label="String" value="string" />
          <el-option label="Number" value="number" />
          <el-option label="Boolean" value="boolean" />
          <el-option label="Object" value="object" />
          <el-option label="Array" value="array" />
          <el-option label="File" value="file" />
        </el-select>
        <el-button size="small" @click="addOutput">添加</el-button>
      </div>
      <div v-if="customOutputs.length" class="custom-outputs">
        <div v-for="item in customOutputs" :key="item.name" class="custom-row">
          <code>{{ item.name }}</code>
          <span class="type-tag">{{ item.type }}</span>
          <el-button
            v-if="!readOnly"
            size="small"
            text
            type="danger"
            @click="removeOutput(item.name)"
          >
            删除
          </el-button>
        </div>
      </div>
    </PanelSection>

    <div class="composer-actions">
      <el-button
        size="small"
        type="primary"
        :loading="composerSaving"
        :disabled="composerSyncDisabled"
        @click="persistComposer()"
      >
        同步 Composer
      </el-button>
      <span v-if="composerMessage" class="hint" :class="{ error: composerError }">{{ composerMessage }}</span>
      <span v-else-if="inlineNeedsModel" class="hint error">请先选择模型后再同步 Soul（否则工作流保存会失败）</span>
      <span v-else class="hint">改模型/提示词/工具/知识库/任务后会自动同步</span>
    </div>
    <p v-if="!resolvedAppId" class="hint error">缺少 appId，无法调用 agent-composer 接口</p>
  </NodePanelShell>
</template>

<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import NodePanelShell from '../shared/NodePanelShell.vue'
import PanelSection from '../shared/PanelSection.vue'
import ModelSelector from '../shared/ModelSelector.vue'
import OutputVarList from '../shared/OutputVarList.vue'
import AgentToolsSection from './AgentToolsSection.vue'
import AgentKnowledgeSection from './AgentKnowledgeSection.vue'
import {
  listRosterAgents,
  loadAgentComposer,
  saveAgentComposer,
} from '@/features/workflow/api/difyAgentApi.js'
import {
  buildCreateInlineBindingPayload,
  buildSaveComposerPayload,
  hasAgentNodeModel,
  hasValidInlineAgentBinding,
  needsInlineAgentBindingCreation,
  normalizeAgentV2NodeData,
  pickRicherBinding,
  soulModelToUiModel,
} from './agentBinding.js'
import { normalizeAgentSoul, withSoulDifyTools, withSoulKnowledgeSets } from './agentSoul.js'
import {
  DEFAULT_AGENT_DECLARED_OUTPUTS,
  addDeclaredOutput,
  declaredOutputsToPanelVars,
  getAgentDeclaredOutputs,
  removeDeclaredOutput,
} from './agentOutputs.js'

const AUTO_SYNC_DEBOUNCE_MS = 700
/** TODO(roster): set true when workspace Roster Agent picker is implemented. */
const ROSTER_BINDING_ENABLED = false

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
  appId: { type: String, default: '' },
})
const emit = defineEmits(['close', 'update:nodeData'])

const workflowAppId = inject('workflowAppId', null)
const resolvedAppId = computed(() => props.appId || workflowAppId?.value || '')

const shellProps = computed(() => ({
  nodeId: props.nodeId,
  nodeData: props.nodeData,
  readOnly: props.readOnly,
}))

const bindingType = computed(() => props.nodeData?.agent_binding?.binding_type || 'inline_agent')
const rosterAgentId = computed(() => (
  bindingType.value === 'roster_agent' ? (props.nodeData?.agent_binding?.agent_id || '') : ''
))
const inlineReady = computed(() => hasValidInlineAgentBinding(props.nodeData?.agent_binding))
const soulEditable = computed(() => !props.readOnly && bindingType.value === 'inline_agent')
const inlineNeedsModel = computed(() => (
  bindingType.value === 'inline_agent' && !hasAgentNodeModel({ model: soulModel.value })
))
const composerSyncDisabled = computed(() => (
  props.readOnly
  || !resolvedAppId.value
  || (bindingType.value === 'inline_agent' && !inlineReady.value)
  || inlineNeedsModel.value
  || (bindingType.value === 'roster_agent' && !rosterAgentId.value)
))

const rosterAgents = ref([])
const rosterLoading = ref(false)
const rosterError = ref('')
const bindingBusy = ref(false)
const bindingError = ref('')
const composerSaving = ref(false)
const composerMessage = ref('')
const composerError = ref(false)
const pendingComposerResync = ref(false)
const suppressAutoSync = ref(true)
const soulDraft = ref(normalizeAgentSoul({}))
const soulModel = ref({ provider: '', name: '', mode: 'chat', completion_params: {} })
const soulPrompt = ref('')
const newOutputName = ref('')
const newOutputType = ref('string')
let autoSyncTimer = null

const soulTools = computed(() => soulDraft.value?.tools?.dify_tools || [])
const soulKnowledgeSets = computed(() => soulDraft.value?.knowledge?.sets || [])
const declaredOutputs = computed(() => getAgentDeclaredOutputs(props.nodeData))
const outputPanelVars = computed(() => declaredOutputsToPanelVars(declaredOutputs.value))
const defaultNames = new Set(DEFAULT_AGENT_DECLARED_OUTPUTS.map(item => item.name))
const customOutputs = computed(() => declaredOutputs.value.filter(item => !defaultNames.has(item.name)))

function shortId(id) {
  const text = String(id || '')
  return text.length > 10 ? `${text.slice(0, 8)}…` : text
}

function emitUpdate(data) {
  emit('update:nodeData', data)
}

function updateField(field, value) {
  emitUpdate(ensureAgentV2Shape({ [field]: value }))
}

function ensureAgentV2Shape(partial = {}) {
  return normalizeAgentV2NodeData(props.nodeData, {
    agent_declared_outputs: props.nodeData.agent_declared_outputs || getAgentDeclaredOutputs(props.nodeData),
    ...partial,
  })
}

function applySoulToLocal(soul) {
  soulDraft.value = normalizeAgentSoul(soul || {})
  if (soulDraft.value.model)
    soulModel.value = soulModelToUiModel(soulDraft.value.model)
  soulPrompt.value = String(soulDraft.value.prompt?.system_prompt || '')
}

function clearAutoSyncTimer() {
  if (autoSyncTimer) {
    clearTimeout(autoSyncTimer)
    autoSyncTimer = null
  }
}

function scheduleAutoSync() {
  if (props.readOnly || suppressAutoSync.value || !resolvedAppId.value)
    return
  // Inline: avoid wiping soul before the user picks a model.
  if (bindingType.value === 'inline_agent' && !hasAgentNodeModel({ model: soulModel.value }))
    return
  // Roster: only need a selected agent to sync node_job.
  if (bindingType.value === 'roster_agent' && !rosterAgentId.value)
    return
  if (composerSaving.value)
    pendingComposerResync.value = true
  clearAutoSyncTimer()
  autoSyncTimer = setTimeout(() => {
    persistComposer({ quiet: true })
  }, AUTO_SYNC_DEBOUNCE_MS)
}

function onBindingTypeChange(type) {
  if (type === 'roster_agent') {
    emitUpdate(ensureAgentV2Shape({
      agent_binding: {
        binding_type: 'roster_agent',
        agent_id: rosterAgentId.value || '',
      },
    }))
    return
  }
  emitUpdate(ensureAgentV2Shape({
    agent_binding: { binding_type: 'inline_agent' },
  }))
  nextTick(() => {
    ensureInlineBinding()
  })
}

function onRosterSelect(agentId) {
  emitUpdate(ensureAgentV2Shape({
    agent_binding: { binding_type: 'roster_agent', agent_id: agentId },
  }))
  nextTick(() => hydrateComposer())
}

function onSoulModelChange(model) {
  if (!soulEditable.value)
    return
  soulModel.value = model
  emitUpdate(ensureAgentV2Shape({ model: { ...model } }))
  scheduleAutoSync()
}

function onSoulPromptInput(value) {
  if (!soulEditable.value)
    return
  soulPrompt.value = value
}

function onSoulToolsChange(tools) {
  if (!soulEditable.value)
    return
  soulDraft.value = withSoulDifyTools(soulDraft.value, tools)
  scheduleAutoSync()
}

function onSoulKnowledgeChange(sets) {
  if (!soulEditable.value)
    return
  soulDraft.value = withSoulKnowledgeSets(soulDraft.value, sets)
  scheduleAutoSync()
}

function addOutput() {
  const next = addDeclaredOutput(declaredOutputs.value, {
    name: newOutputName.value,
    type: newOutputType.value,
  })
  if (next.length === declaredOutputs.value.length)
    return
  emitUpdate(ensureAgentV2Shape({ agent_declared_outputs: next }))
  newOutputName.value = ''
  scheduleAutoSync()
}

function removeOutput(name) {
  emitUpdate(ensureAgentV2Shape({
    agent_declared_outputs: removeDeclaredOutput(declaredOutputs.value, name),
  }))
  scheduleAutoSync()
}

async function loadRoster() {
  rosterLoading.value = true
  rosterError.value = ''
  try {
    const response = await listRosterAgents({ page: 1, limit: 50 })
    rosterAgents.value = response.data || response.items || []
  }
  catch (e) {
    rosterError.value = e.response?.data?.message || e.message || '加载 Roster 失败'
    rosterAgents.value = []
  }
  finally {
    rosterLoading.value = false
  }
}

/**
 * Hydrate soul UI from composer. Only write binding back when remote is richer.
 */
async function hydrateComposer() {
  if (!resolvedAppId.value || !props.nodeId)
    return
  try {
    const state = await loadAgentComposer(resolvedAppId.value, props.nodeId)
    const soul = state?.agent_soul || state?.soul || {}
    applySoulToLocal(soul)

    const remoteBinding = state?.binding || state?.agent_binding
    const richer = pickRicherBinding(props.nodeData?.agent_binding, remoteBinding)
    const remoteTask = state?.node_job?.workflow_prompt
    const remoteOutputs = state?.node_job?.declared_outputs
    const patch = {}
    if (richer)
      patch.agent_binding = richer
    if (typeof remoteTask === 'string' && remoteTask && !props.nodeData.agent_task)
      patch.agent_task = remoteTask
    if (Array.isArray(remoteOutputs) && remoteOutputs.length && !props.nodeData.agent_declared_outputs?.length)
      patch.agent_declared_outputs = remoteOutputs
    if (hasAgentNodeModel({ model: soulModel.value }) && !hasAgentNodeModel(props.nodeData))
      patch.model = { ...soulModel.value }
    if (Object.keys(patch).length)
      emitUpdate(ensureAgentV2Shape(patch))
  }
  catch {
    // New nodes may not have composer state yet.
  }
}

async function ensureInlineBinding() {
  if (props.readOnly || !resolvedAppId.value)
    return null
  if (bindingType.value !== 'inline_agent')
    return props.nodeData?.agent_binding || null
  if (!needsInlineAgentBindingCreation(props.nodeData?.agent_binding || { binding_type: 'inline_agent' }))
    return props.nodeData.agent_binding

  bindingBusy.value = true
  bindingError.value = ''
  try {
    const payload = buildCreateInlineBindingPayload(soulModel.value)
    const result = await saveAgentComposer(resolvedAppId.value, props.nodeId, payload)
    const binding = result?.binding || result?.agent_binding
    if (!hasValidInlineAgentBinding(binding)) {
      bindingError.value = '创建绑定失败：未返回 agent_id / current_snapshot_id'
      return null
    }
    emitUpdate(ensureAgentV2Shape({ agent_binding: binding }))
    const soul = result?.agent_soul || result?.soul
    if (soul)
      applySoulToLocal(soul)
    return binding
  }
  catch (e) {
    bindingError.value = e.response?.data?.message || e.message || '创建内联绑定失败'
    return null
  }
  finally {
    bindingBusy.value = false
  }
}

async function persistComposer({ quiet = false } = {}) {
  if (!resolvedAppId.value || props.readOnly)
    return
  if (composerSaving.value) {
    pendingComposerResync.value = true
    return
  }
  if (bindingType.value === 'inline_agent' && !hasAgentNodeModel({ model: soulModel.value })) {
    if (!quiet) {
      composerError.value = true
      composerMessage.value = '请先选择模型'
    }
    return
  }
  composerSaving.value = true
  pendingComposerResync.value = false
  if (!quiet) {
    composerMessage.value = ''
    composerError.value = false
  }
  try {
    let binding = props.nodeData.agent_binding
    if (bindingType.value === 'inline_agent') {
      binding = await ensureInlineBinding()
      if (!hasValidInlineAgentBinding(binding))
        throw new Error(bindingError.value || '内联绑定未就绪')
    }
    else if (!binding?.agent_id) {
      throw new Error('请先选择 Roster Agent')
    }

    // Keep local prompt/model on the draft before save.
    soulDraft.value = normalizeAgentSoul({
      ...soulDraft.value,
      prompt: { system_prompt: soulPrompt.value },
    })

    const payload = buildSaveComposerPayload({
      binding,
      soul: soulDraft.value,
      model: soulModel.value,
      prompt: soulPrompt.value,
      agentTask: props.nodeData.agent_task || '',
      declaredOutputs: getAgentDeclaredOutputs(props.nodeData),
    })
    const result = await saveAgentComposer(resolvedAppId.value, props.nodeId, payload)
    const nextBinding = result?.binding || result?.agent_binding || binding
    const resultSoul = result?.agent_soul || result?.soul
    // A newer local edit happened while this save was in flight; keep the draft.
    if (resultSoul && !pendingComposerResync.value)
      applySoulToLocal(resultSoul)
    const projectedModel = soulModelToUiModel(
      pendingComposerResync.value ? soulDraft.value.model : (resultSoul?.model || null),
    )
    const nextModel = hasAgentNodeModel({ model: projectedModel })
      ? projectedModel
      : (hasAgentNodeModel({ model: soulModel.value }) ? { ...soulModel.value } : props.nodeData.model)
    emitUpdate(ensureAgentV2Shape({
      agent_binding: nextBinding,
      ...(nextModel ? { model: nextModel } : {}),
      agent_declared_outputs: getAgentDeclaredOutputs(props.nodeData),
    }))
    if (!quiet) {
      composerMessage.value = 'Composer 已同步'
      composerError.value = false
    }
    else {
      composerMessage.value = '已自动同步'
      composerError.value = false
    }
  }
  catch (e) {
    composerError.value = true
    composerMessage.value = e.response?.data?.message || e.message || '同步失败'
  }
  finally {
    composerSaving.value = false
    if (pendingComposerResync.value)
      persistComposer({ quiet: true })
  }
}

async function bootstrapPanel() {
  suppressAutoSync.value = true
  clearAutoSyncTimer()
  try {
    if (
      props.nodeData.type !== 'agent'
      || !props.nodeData.version
      || props.nodeData.agent_node_kind !== 'dify_agent'
    ) {
      emitUpdate(ensureAgentV2Shape())
    }
    else if (!Array.isArray(props.nodeData.agent_declared_outputs) || !props.nodeData.agent_declared_outputs.length) {
      emitUpdate(ensureAgentV2Shape({
        agent_declared_outputs: getAgentDeclaredOutputs(props.nodeData),
      }))
    }
    // TODO(roster): restore loadRoster() when ROSTER_BINDING_ENABLED is true.
    if (ROSTER_BINDING_ENABLED)
      await loadRoster()
    await hydrateComposer()
    if (bindingType.value === 'inline_agent' && !props.readOnly)
      await ensureInlineBinding()
    // Hydrate local UI model from graph projection if composer had none.
    if (!hasAgentNodeModel({ model: soulModel.value }) && hasAgentNodeModel(props.nodeData))
      soulModel.value = { ...props.nodeData.model, mode: 'chat', completion_params: {} }
  }
  finally {
    await nextTick()
    suppressAutoSync.value = false
  }
}

onMounted(() => {
  bootstrapPanel()
})

onBeforeUnmount(() => {
  clearAutoSyncTimer()
})

watch(() => props.nodeId, () => {
  bindingError.value = ''
  composerMessage.value = ''
  soulDraft.value = normalizeAgentSoul({})
  bootstrapPanel()
})

watch(soulPrompt, () => {
  scheduleAutoSync()
})

watch(() => props.nodeData.agent_task, () => {
  scheduleAutoSync()
})
</script>

<style scoped>
.w-full { width: 100%; }
.composer-actions { display: flex; align-items: center; gap: 10px; padding: 0 0 8px; }
.hint { margin: 6px 0 0; font-size: 12px; color: #667085; }
.hint.error { color: #b42318; }
.output-add {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.custom-outputs {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.custom-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
}
.type-tag {
  color: #667085;
  margin-right: auto;
}
</style>
