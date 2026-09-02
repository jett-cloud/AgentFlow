/**
 * Agent Soul normalize / merge helpers.
 * Composer save_to_current_version replaces the whole snapshot — never send
 * a partial soul that drops tools/knowledge.
 */

/**
 * @param {unknown} raw
 * @returns {object}
 */
export function normalizeAgentSoul(raw = {}) {
  const source = raw && typeof raw === 'object' ? raw : {}
  const tools = source.tools && typeof source.tools === 'object' ? source.tools : {}
  const knowledge = source.knowledge && typeof source.knowledge === 'object' ? source.knowledge : {}
  const prompt = source.prompt && typeof source.prompt === 'object' ? source.prompt : {}

  const soul = {
    ...source,
    schema_version: Number.isFinite(Number(source.schema_version)) ? Number(source.schema_version) : 1,
    prompt: {
      system_prompt: String(prompt.system_prompt ?? ''),
    },
    tools: {
      dify_tools: Array.isArray(tools.dify_tools) ? tools.dify_tools.map(normalizeDifyTool).filter(Boolean) : [],
      cli_tools: Array.isArray(tools.cli_tools) ? tools.cli_tools : [],
    },
    knowledge: {
      sets: Array.isArray(knowledge.sets) ? knowledge.sets.map(normalizeKnowledgeSet).filter(Boolean) : [],
    },
  }

  return soul
}

/**
 * @param {unknown} tool
 */
export function normalizeDifyTool(tool) {
  if (!tool || typeof tool !== 'object')
    return null
  const providerId = String(tool.provider_id || tool.provider || tool.plugin_id || '').trim()
  if (!providerId && !(tool.plugin_id && tool.provider))
    return null

  const credentialId = tool.credential_ref?.id || tool.credential_id || ''
  const credentialType = credentialId
    ? (tool.credential_type === 'oauth2' ? 'oauth2' : 'api-key')
    : 'unauthorized'

  const next = {
    enabled: tool.enabled !== false,
    provider_type: String(tool.provider_type || 'builtin'),
    provider_id: tool.provider_id || providerId || null,
    tool_name: tool.tool_name ? String(tool.tool_name) : null,
    credential_type: credentialType,
    runtime_parameters: tool.runtime_parameters && typeof tool.runtime_parameters === 'object'
      ? { ...tool.runtime_parameters }
      : {},
  }

  if (tool.plugin_id)
    next.plugin_id = String(tool.plugin_id)
  if (tool.provider)
    next.provider = String(tool.provider)
  if (tool.description != null)
    next.description = String(tool.description)
  if (credentialId) {
    next.credential_ref = {
      type: tool.credential_ref?.type || 'provider',
      id: String(credentialId),
      provider: tool.credential_ref?.provider || next.provider_id || next.provider || undefined,
    }
  }

  return next
}

/**
 * @param {unknown} set
 */
export function normalizeKnowledgeSet(set) {
  if (!set || typeof set !== 'object')
    return null
  const id = String(set.id || '').trim()
  const name = String(set.name || '').trim()
  if (!id || !name)
    return null
  const datasets = Array.isArray(set.datasets)
    ? set.datasets
      .map((ds) => {
        if (!ds || typeof ds !== 'object')
          return null
        const datasetId = String(ds.id || '').trim()
        if (!datasetId)
          return null
        return {
          id: datasetId,
          name: ds.name != null ? String(ds.name) : undefined,
          description: ds.description != null ? String(ds.description) : undefined,
        }
      })
      .filter(Boolean)
    : []

  const queryMode = set.query?.mode === 'user_query' ? 'user_query' : 'generated_query'
  const retrievalMode = set.retrieval?.mode === 'single' ? 'single' : 'multiple'
  const retrieval = {
    mode: retrievalMode,
    top_k: retrievalMode === 'multiple'
      ? (Number.isFinite(Number(set.retrieval?.top_k)) ? Number(set.retrieval.top_k) : 4)
      : (set.retrieval?.top_k ?? null),
    score_threshold: set.retrieval?.score_threshold ?? null,
    reranking_mode: set.retrieval?.reranking_mode || 'reranking_model',
    reranking_enable: Boolean(set.retrieval?.reranking_enable),
    reranking_model: set.retrieval?.reranking_model || null,
    weights: set.retrieval?.weights || null,
    model: set.retrieval?.model || null,
  }

  return {
    id,
    name,
    description: set.description ?? null,
    datasets,
    query: {
      mode: queryMode,
      value: queryMode === 'user_query' ? (set.query?.value ?? null) : null,
    },
    retrieval,
    metadata_filtering: {
      mode: set.metadata_filtering?.mode || 'disabled',
      ...(set.metadata_filtering?.model_config
        ? { model_config: set.metadata_filtering.model_config }
        : {}),
      ...(set.metadata_filtering?.conditions
        ? { conditions: set.metadata_filtering.conditions }
        : {}),
    },
  }
}

/**
 * Apply prompt / model onto a normalized soul draft (model already in soul shape).
 * @param {{ soul?: object, soulModel?: object | null, prompt?: string }} input
 */
export function applySoulPromptAndModel({ soul, soulModel, prompt } = {}) {
  const next = normalizeAgentSoul(soul)
  if (prompt !== undefined)
    next.prompt = { system_prompt: String(prompt ?? '') }
  if (soulModel)
    next.model = soulModel
  return next
}

/**
 * Replace soul.tools.dify_tools immutably.
 * @param {object} soul
 * @param {object[]} difyTools
 */
export function withSoulDifyTools(soul, difyTools) {
  const next = normalizeAgentSoul(soul)
  next.tools = {
    ...next.tools,
    dify_tools: Array.isArray(difyTools) ? difyTools.map(normalizeDifyTool).filter(Boolean) : [],
  }
  return next
}

/**
 * Replace soul.knowledge.sets immutably.
 * @param {object} soul
 * @param {object[]} sets
 */
export function withSoulKnowledgeSets(soul, sets) {
  const next = normalizeAgentSoul(soul)
  next.knowledge = {
    sets: Array.isArray(sets) ? sets.map(normalizeKnowledgeSet).filter(Boolean) : [],
  }
  return next
}
