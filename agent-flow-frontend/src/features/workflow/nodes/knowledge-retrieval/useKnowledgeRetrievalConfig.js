// src/views/copilot/components/workflow/node/knowledge-retrieval/useKnowledgeRetrievalConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { parseSelectorInput } from '../../model/availableVariables.js'
import { normalizeKnowledgeRetrievalData, RERANKING_MODES, applyRerankingMode, applyWeightedScore } from './knowledgeRetrievalNode.js'
import { defaultOperatorForType } from '@/features/datasets/model/metadataFields.js'

export { RERANKING_MODES }

/** Dify retrieval_mode: single | multiple */
export const RETRIEVAL_MODES = [
  { label: '多路召回 (Multiple)', value: 'multiple' },
  { label: 'N 选 1 召回 (Single)', value: 'single' },
]

export const METADATA_FILTER_MODES = [
  { label: '关闭', value: 'disabled' },
  { label: '自动', value: 'automatic' },
  { label: '手动', value: 'manual' },
]

export const METADATA_OPERATORS = [
  'contains',
  'not contains',
  'start with',
  'end with',
  'is',
  'is not',
  'empty',
  'not empty',
  '=',
  '≠',
  '>',
  '<',
  '≥',
  '≤',
  'in',
  'not in',
  'before',
  'after',
]

const DEFAULT_MULTIPLE = {
  top_k: 4,
  score_threshold: null,
  reranking_enable: false,
  reranking_model: { provider: '', model: '' },
  reranking_mode: 'reranking_model',
}

function uid() {
  return `meta_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`
}

export function useKnowledgeRetrievalConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)

  function patch(partial) {
    emit('update:nodeData', normalizeKnowledgeRetrievalData({ ...nodeData.value, ...partial }))
  }

  const querySelector = computed({
    get: () => nodeData.value?.query_variable_selector || [],
    set: (val) => {
      const selector = parseSelectorInput(val)
      patch({ query_variable_selector: selector })
    },
  })

  const queryAttachmentSelector = computed({
    get: () => nodeData.value?.query_attachment_selector || [],
    set: val => patch({ query_attachment_selector: parseSelectorInput(val) }),
  })

  const datasetIds = computed({
    get: () => nodeData.value?.dataset_ids || (nodeData.value?.dataset_id ? [nodeData.value.dataset_id] : []),
    set: (val) => patch({ dataset_ids: Array.isArray(val) ? val : [] }),
  })

  const retrievalMode = computed({
    get: () => {
      const mode = nodeData.value?.retrieval_mode
      if (mode === 'single' || mode === 'multiple')
        return mode
      return 'multiple'
    },
    set: (val) => patch({ retrieval_mode: val }),
  })

  const multipleConfig = computed(() => ({
    ...DEFAULT_MULTIPLE,
    ...(nodeData.value?.multiple_retrieval_config || {}),
    reranking_model: {
      ...DEFAULT_MULTIPLE.reranking_model,
      ...(nodeData.value?.multiple_retrieval_config?.reranking_model || {}),
    },
  }))

  function patchMultiple(partial) {
    patch({
      multiple_retrieval_config: { ...multipleConfig.value, ...partial },
      top_k: undefined,
      score_threshold: undefined,
    })
  }

  const topK = computed({
    get: () => multipleConfig.value.top_k ?? 4,
    set: (val) => patchMultiple({ top_k: val }),
  })

  const scoreThresholdEnabled = computed({
    get: () => !(
      multipleConfig.value.score_threshold === undefined
      || multipleConfig.value.score_threshold === null
    ),
    set: (enabled) => {
      patchMultiple({
        score_threshold: enabled ? (multipleConfig.value.score_threshold ?? 0.5) : null,
      })
    },
  })

  const scoreThreshold = computed({
    get: () => multipleConfig.value.score_threshold ?? 0.5,
    set: (val) => patchMultiple({ score_threshold: val }),
  })

  const rerankingEnable = computed({
    get: () => !!multipleConfig.value.reranking_enable,
    set: (val) => patchMultiple({ reranking_enable: !!val }),
  })

  const rerankModel = computed({
    get: () => ({
      provider: multipleConfig.value.reranking_model?.provider || '',
      name: multipleConfig.value.reranking_model?.model || '',
      mode: 'rerank',
      completion_params: {},
    }),
    set: (model) => {
      patchMultiple({
        reranking_model: {
          provider: model?.provider || '',
          model: model?.name || model?.model || '',
        },
      })
    },
  })

  const rerankingMode = computed({
    get: () => multipleConfig.value.reranking_mode || 'reranking_model',
    set: value => patchMultiple(applyRerankingMode(multipleConfig.value, value)),
  })

  const weightedScore = computed({
    get: () => multipleConfig.value.weights,
    set: weights => patchMultiple(applyWeightedScore(multipleConfig.value, weights)),
  })

  const singleModel = computed({
    get: () => {
      const model = nodeData.value?.single_retrieval_config?.model || {}
      return {
        provider: model.provider || '',
        name: model.name || '',
        mode: model.mode || 'chat',
        completion_params: model.completion_params || {},
      }
    },
    set: (model) => {
      patch({
        single_retrieval_config: {
          ...(nodeData.value?.single_retrieval_config || {}),
          model: {
            provider: model?.provider || '',
            name: model?.name || '',
            mode: model?.mode || 'chat',
            completion_params: model?.completion_params || {},
          },
        },
      })
    },
  })

  const metadataFilteringMode = computed({
    get: () => nodeData.value?.metadata_filtering_mode || 'disabled',
    set: (val) => patch({ metadata_filtering_mode: val }),
  })

  const metadataConditions = computed(() => {
    const conditions = nodeData.value?.metadata_filtering_conditions
    return {
      logical_operator: conditions?.logical_operator || 'and',
      conditions: Array.isArray(conditions?.conditions) ? conditions.conditions : [],
    }
  })

  const metadataLogicalOperator = computed({
    get: () => metadataConditions.value.logical_operator,
    set: (val) => patch({
      metadata_filtering_conditions: {
        ...metadataConditions.value,
        logical_operator: val,
      },
    }),
  })

  function addMetadataCondition(field) {
    if (!field?.name)
      return
    patch({
      metadata_filtering_conditions: {
        ...metadataConditions.value,
        conditions: [
          ...metadataConditions.value.conditions,
          {
            id: uid(),
            metadata_id: field.id,
            name: field.name,
            comparison_operator: defaultOperatorForType(field.type),
            value: '',
          },
        ],
      },
    })
  }

  function updateMetadataCondition(id, partial) {
    patch({
      metadata_filtering_conditions: {
        ...metadataConditions.value,
        conditions: metadataConditions.value.conditions.map((c) => {
          if (c.id !== id)
            return c
          return { ...c, ...partial }
        }),
      },
    })
  }

  function removeMetadataCondition(id) {
    patch({
      metadata_filtering_conditions: {
        ...metadataConditions.value,
        conditions: metadataConditions.value.conditions.filter(c => c.id !== id),
      },
    })
  }

  const metadataModel = computed({
    get: () => {
      const model = nodeData.value?.metadata_model_config || {}
      return {
        provider: model.provider || '',
        name: model.name || '',
        mode: model.mode || 'chat',
        completion_params: model.completion_params || {},
      }
    },
    set: (model) => {
      patch({
        metadata_model_config: {
          provider: model?.provider || '',
          name: model?.name || '',
          mode: model?.mode || 'chat',
          completion_params: model?.completion_params || {},
        },
      })
    },
  })

  return {
    readOnly,
    querySelector,
    queryAttachmentSelector,
    datasetIds,
    retrievalMode,
    topK,
    scoreThresholdEnabled,
    scoreThreshold,
    rerankingEnable,
    rerankingMode,
    weightedScore,
    rerankModel,
    singleModel,
    metadataFilteringMode,
    metadataConditions,
    metadataLogicalOperator,
    addMetadataCondition,
    updateMetadataCondition,
    removeMetadataCondition,
    metadataModel,
    RETRIEVAL_MODES,
    RERANKING_MODES,
    METADATA_FILTER_MODES,
    METADATA_OPERATORS,
  }
}
