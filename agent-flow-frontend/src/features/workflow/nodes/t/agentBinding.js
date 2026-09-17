/**
 * Agent-v2 binding helpers.
 * Contrasts Dify web nodes/agent-v2/types.ts + hooks createInlineAgentBinding.
 */

import { applySoulPromptAndModel, normalizeAgentSoul } from './agentSoul.js'
import { filterPersistableKnowledgeSets } from './agentKnowledge.js'

/**
 * Backend wire protocol: type is always "agent" with version "2".
 * Frontend menu alias "agent-v2" must not leak into saved graph data.
 * @param {object} [data]
 * @param {object} [partial]
 */
export function normalizeAgentV2NodeData(data = {}, partial = {}) {
  const merged = { ...data, ...partial }
  return {
    ...merged,
    type: 'agent',
    version: '2',
    agent_node_kind: 'dify_agent',
    agent_binding: merged.agent_binding || { binding_type: 'inline_agent' },
    agent_task: merged.agent_task ?? '',
  }
}

/**
 * Graph-projected model used by canvas + checklist (soul stays in composer).
 * @param {object} [data]
 */
export function hasAgentNodeModel(data = {}) {
  const model = data?.model
  if (!model || typeof model !== 'object')
    return false
  const name = model.name || model.model
  return Boolean(String(model.provider || '').trim() && String(name || '').trim())
}

/**
 * @param {unknown} data
 */
export function isAgentV2NodeData(data = {}) {
  return data?.agent_node_kind === 'dify_agent' && String(data?.version) === '2'
}

/**
 * @param {object} [binding]
 */
export function hasValidInlineAgentBinding(binding = {}) {
  return (
    binding.binding_type === 'inline_agent'
    && typeof binding.agent_id === 'string'
    && binding.agent_id.length > 0
    && typeof binding.current_snapshot_id === 'string'
    && binding.current_snapshot_id.length > 0
  )
}

/**
 * @param {object} [binding]
 */
export function hasValidRosterAgentBinding(binding = {}) {
  return (
    binding.binding_type === 'roster_agent'
    && typeof binding.agent_id === 'string'
    && binding.agent_id.length > 0
  )
}

/**
 * @param {object} [binding]
 */
export function hasValidAgentBinding(binding = {}) {
  return hasValidInlineAgentBinding(binding) || hasValidRosterAgentBinding(binding)
}

/**
 * @param {object} [binding]
 */
export function needsInlineAgentBindingCreation(binding = {}) {
  return binding.binding_type === 'inline_agent' && !hasValidInlineAgentBinding(binding)
}

/**
 * @param {string} [provider]
 */
export function getModelProviderPluginId(provider = '') {
  const parts = String(provider).split('/').filter(Boolean)
  if (parts.length >= 2)
    return `${parts[0]}/${parts[1]}`
  return provider ? `langgenius/${provider}` : ''
}

/**
 * UI ModelSelector shape → AgentSoulConfig.model
 * @param {{ provider?: string, name?: string, model?: string } | null} uiModel
 */
export function uiModelToSoulModel(uiModel) {
  if (!uiModel || typeof uiModel !== 'object')
    return null
  const provider = String(uiModel.provider || '').trim()
  const model = String(uiModel.name || uiModel.model || '').trim()
  if (!provider || !model)
    return null
  return {
    model_provider: provider,
    model,
    plugin_id: getModelProviderPluginId(provider),
  }
}

/**
 * AgentSoulConfig.model → UI ModelSelector shape
 * @param {object | null} [soulModel]
 */
export function soulModelToUiModel(soulModel) {
  if (!soulModel || typeof soulModel !== 'object')
    return { provider: '', name: '', mode: 'chat', completion_params: {} }
  return {
    provider: soulModel.model_provider || soulModel.provider || '',
    name: soulModel.model || soulModel.name || '',
    mode: 'chat',
    completion_params: {},
  }
}

/**
 * Minimal soul for creating an inline binding (node_job_only).
 * @param {{ provider?: string, name?: string } | null} [uiModel]
 */
export function buildDefaultAgentSoul(uiModel = null) {
  return buildAgentSoulForSave({ soul: {}, model: uiModel, prompt: '' })
}

/**
 * Soul payload for save_to_current_version.
 * Always preserves tools/knowledge from the local soul draft.
 * @param {{ soul?: object, model?: object, prompt?: string }} input
 */
export function buildAgentSoulForSave({ soul, model, prompt } = {}) {
  const next = applySoulPromptAndModel({
    soul,
    soulModel: uiModelToSoulModel(model),
    prompt,
  })
  // Drop incomplete knowledge sets so draft save validation does not reject.
  next.knowledge = {
    sets: filterPersistableKnowledgeSets(next.knowledge?.sets || []),
  }
  return next
}

/**
 * PUT body to create inline binding (official hooks.ts).
 * @param {{ provider?: string, name?: string } | null} [uiModel]
 */
export function buildCreateInlineBindingPayload(uiModel = null) {
  return {
    variant: 'workflow',
    save_strategy: 'node_job_only',
    binding: { binding_type: 'inline_agent' },
    soul_lock: { locked: false },
    agent_soul: buildDefaultAgentSoul(uiModel),
  }
}

/**
 * PUT body to sync soul + node job.
 * Inline drafts use node_job_only (official web); that path also updates soul.
 * Always send soul_lock.locked=false — API default is locked=true and rejects
 * save_to_current_version with agent_soul when locked.
 * Roster bindings only persist node_job (soul is shared / read-only).
 * @param {{
 *   binding: object,
 *   soul?: object,
 *   model?: object,
 *   prompt?: string,
 *   agentTask?: string,
 *   declaredOutputs?: object[],
 *   saveStrategy?: string,
 * }} input
 */
export function buildSaveComposerPayload({
  binding,
  soul,
  model,
  prompt,
  agentTask,
  declaredOutputs,
  saveStrategy,
} = {}) {
  const isRoster = binding?.binding_type === 'roster_agent'
  // Inline workflow agents: node_job_only updates both node_job and soul.
  const strategy = saveStrategy || 'node_job_only'
  const payload = {
    variant: 'workflow',
    binding: binding || { binding_type: 'inline_agent' },
    soul_lock: { locked: false },
    node_job: {
      schema_version: 1,
      workflow_prompt: String(agentTask || ''),
      declared_outputs: Array.isArray(declaredOutputs) ? declaredOutputs : [],
    },
    save_strategy: strategy,
  }

  if (!isRoster) {
    payload.agent_soul = buildAgentSoulForSave({ soul: soul || normalizeAgentSoul({}), model, prompt })
  }

  return payload
}

/**
 * Prefer remote binding when it is more complete than local.
 * @param {object} [local]
 * @param {object} [remote]
 */
export function pickRicherBinding(local, remote) {
  if (hasValidAgentBinding(remote) && !hasValidAgentBinding(local))
    return remote
  if (hasValidInlineAgentBinding(remote) && !hasValidInlineAgentBinding(local))
    return remote
  if (remote?.agent_id && !local?.agent_id)
    return remote
  if (remote?.current_snapshot_id && !local?.current_snapshot_id && local?.binding_type === 'inline_agent')
    return { ...local, ...remote }
  return null
}
