/**
 * Agent Soul knowledge.sets helpers.
 */

import { normalizeKnowledgeSet } from './agentSoul.js'

function uid(prefix = 'ks') {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`
}

/**
 * @param {object} [partial]
 * @param {{ id?: string, name?: string, description?: string }[]} [datasets]
 */
export function createKnowledgeSet(partial = {}, datasets = []) {
  const datasetRefs = (Array.isArray(datasets) ? datasets : [])
    .map(ds => ({
      id: String(ds.id || '').trim(),
      name: ds.name,
      description: ds.description,
    }))
    .filter(ds => ds.id)

  const fallbackName = partial.index != null
    ? `Knowledge Set ${partial.index + 1}`
    : 'Knowledge Set'

  return normalizeKnowledgeSet({
    id: partial.id || uid('ks'),
    name: partial.name || fallbackName,
    description: partial.description ?? null,
    datasets: datasetRefs,
    query: {
      mode: partial.query?.mode || 'generated_query',
      value: partial.query?.value ?? null,
    },
    retrieval: {
      mode: partial.retrieval?.mode || 'multiple',
      top_k: partial.retrieval?.top_k ?? 4,
      score_threshold: partial.retrieval?.score_threshold ?? null,
      reranking_mode: partial.retrieval?.reranking_mode || 'reranking_model',
      reranking_enable: partial.retrieval?.reranking_enable ?? false,
      reranking_model: partial.retrieval?.reranking_model ?? null,
      model: partial.retrieval?.model ?? null,
    },
    metadata_filtering: {
      mode: partial.metadata_filtering?.mode || 'disabled',
    },
  })
}

/**
 * @param {object[]} sets
 * @param {object} [partial]
 * @param {{ id?: string, name?: string, description?: string }[]} [datasets]
 */
export function addKnowledgeSet(sets, partial = {}, datasets = []) {
  const list = Array.isArray(sets) ? [...sets] : []
  const created = createKnowledgeSet({ ...partial, index: list.length }, datasets)
  if (!created)
    return list
  list.push(created)
  return list
}

/**
 * @param {object[]} sets
 * @param {string} setId
 */
export function removeKnowledgeSet(sets, setId) {
  return (Array.isArray(sets) ? sets : []).filter(item => item.id !== setId)
}

/**
 * @param {object[]} sets
 * @param {string} setId
 * @param {object} patch
 */
export function updateKnowledgeSet(sets, setId, patch = {}) {
  return (Array.isArray(sets) ? sets : []).map((item) => {
    if (item.id !== setId)
      return item
    return normalizeKnowledgeSet({
      ...item,
      ...patch,
      query: { ...item.query, ...(patch.query || {}) },
      retrieval: { ...item.retrieval, ...(patch.retrieval || {}) },
      metadata_filtering: {
        ...item.metadata_filtering,
        ...(patch.metadata_filtering || {}),
      },
      datasets: patch.datasets !== undefined ? patch.datasets : item.datasets,
    })
  }).filter(Boolean)
}

/**
 * Map dataset ids + catalog → soul dataset refs.
 * @param {string[]} datasetIds
 * @param {(id: string) => object | null} findById
 */
export function datasetIdsToRefs(datasetIds, findById) {
  return (Array.isArray(datasetIds) ? datasetIds : [])
    .map((id) => {
      const ds = findById?.(id)
      return {
        id: String(id),
        name: ds?.name,
        description: ds?.description,
      }
    })
    .filter(item => item.id)
}

/**
 * Sets that are safe to persist (API requires ≥1 dataset per set).
 * Empty sets list is valid (= no knowledge layer).
 * @param {object[]} sets
 */
export function filterPersistableKnowledgeSets(sets) {
  return (Array.isArray(sets) ? sets : [])
    .map(normalizeKnowledgeSet)
    .filter(item => item && Array.isArray(item.datasets) && item.datasets.length > 0)
}
