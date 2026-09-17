<template>
  <NodePanelShell v-bind="shellProps" block-type="knowledge-index" @close="$emit('close')" @update:node-data="emitUpdate">
    <PanelSection label="分段结构" required>
      <el-select
        :model-value="nodeData.chunk_structure"
        placeholder="选择分段结构…"
        :disabled="readOnly"
        @change="updateChunkStructure"
      >
        <el-option label="通用" value="text_model" />
        <el-option label="父子分段" value="hierarchical_model" />
        <el-option label="问答" value="qa_model" />
      </el-select>
    </PanelSection>

    <PanelSection label="分段输入变量" required>
      <VarReferencePicker
        :model-value="nodeData.index_chunk_variable_selector || []"
        :node-id="nodeId"
        :filter-var="filterChunkVariable"
        placeholder="选择与分段结构匹配的上游变量"
        :read-only="readOnly"
        @update:model-value="updateField('index_chunk_variable_selector', $event)"
      />
    </PanelSection>

    <PanelSection label="索引方式" required>
      <el-radio-group
        :model-value="nodeData.indexing_technique"
        :disabled="readOnly"
        @change="updateIndexingTechnique"
      >
        <el-radio value="high_quality">高质量</el-radio>
        <el-radio value="economy">经济</el-radio>
      </el-radio-group>
    </PanelSection>

    <PanelSection v-if="nodeData.indexing_technique === 'high_quality'" label="Embedding 模型" required>
      <el-select
        :model-value="embeddingKey"
        filterable
        clearable
        class="w-full"
        placeholder="选择工作区 Embedding 模型"
        :disabled="readOnly"
        @update:model-value="updateEmbeddingModel"
      >
        <el-option
          v-for="model in embeddingModels"
          :key="`${model.provider}/${model.model}`"
          :label="`${model.providerLabel} / ${model.label}`"
          :value="`${model.provider}::${model.model}`"
        />
      </el-select>
      <p v-if="!embeddingModels.length" class="hint">请先在工作区集成中配置 Embedding 模型。</p>
    </PanelSection>

    <PanelSection label="关键词数量" required>
      <el-input-number
        :model-value="nodeData.keyword_number ?? 10"
        :min="1"
        :max="100"
        :disabled="readOnly"
        @change="updateField('keyword_number', $event)"
      />
    </PanelSection>

    <PanelSection label="检索方式">
      <el-select
        :model-value="nodeData.retrieval_model?.search_method"
        placeholder="选择检索方式…"
        :disabled="readOnly"
        @change="updateRetrievalMethod"
      >
        <el-option label="混合检索" value="hybrid_search" />
        <el-option label="向量检索" value="semantic_search" />
        <el-option label="全文检索" value="full_text_search" />
        <el-option label="关键词检索" value="keyword_search" />
      </el-select>
    </PanelSection>

    <PanelSection label="Top K">
      <el-input-number
        :model-value="nodeData.retrieval_model?.top_k ?? 3"
        :min="1"
        :max="20"
        :disabled="readOnly"
        @change="updateTopK"
      />
    </PanelSection>

    <PanelSection label="分数阈值">
      <el-switch
        :model-value="nodeData.retrieval_model?.score_threshold_enabled || false"
        :disabled="readOnly"
        @change="updateRetrieval({ score_threshold_enabled: $event })"
      />
      <el-input-number
        v-if="nodeData.retrieval_model?.score_threshold_enabled"
        :model-value="nodeData.retrieval_model?.score_threshold ?? 0"
        :min="0"
        :max="1"
        :step="0.01"
        :disabled="readOnly"
        @change="updateScoreThreshold"
      />
    </PanelSection>

    <PanelSection v-if="nodeData.retrieval_model?.search_method === 'hybrid_search'" label="Rerank">
      <el-switch
        :model-value="nodeData.retrieval_model?.reranking_enable || false"
        :disabled="readOnly"
        @change="updateRetrieval({ reranking_enable: $event, reranking_mode: 'reranking_model' })"
      />
      <el-select
        v-if="nodeData.retrieval_model?.reranking_enable"
        :model-value="rerankKey"
        filterable
        clearable
        class="w-full"
        placeholder="选择 Rerank 模型"
        :disabled="readOnly"
        @update:model-value="updateRerankModel"
      >
        <el-option
          v-for="model in rerankModels"
          :key="`${model.provider}/${model.model}`"
          :label="`${model.providerLabel} / ${model.label}`"
          :value="`${model.provider}::${model.model}`"
        />
      </el-select>
    </PanelSection>
  </NodePanelShell>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import NodePanelShell from '../shared/NodePanelShell.vue'
import PanelSection from '../shared/PanelSection.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import { fetchModelsByType } from '@/features/integrations/api/difyModelsApi.js'
import { flattenModelCatalog } from '@/features/datasets/model/retrievalModel.js'
import { isKnowledgeChunkInput, normalizeKnowledgeBaseData } from './knowledgeBaseNode.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:nodeData'])
const shellProps = computed(() => ({ nodeId: props.nodeId, nodeData: props.nodeData, readOnly: props.readOnly }))
const embeddingModels = ref([])
const rerankModels = ref([])
const emitUpdate = data => emit('update:nodeData', data)
const updateField = (field, value) => emitUpdate(normalizeKnowledgeBaseData({ ...props.nodeData, [field]: value }))
const updateRetrieval = partial => updateField('retrieval_model', { ...(props.nodeData.retrieval_model || {}), ...partial })
const updateRetrievalMethod = value => updateRetrieval({ search_method: value })
const updateTopK = value => updateRetrieval({ top_k: value })
const updateScoreThreshold = value => updateRetrieval({ score_threshold: value })

const filterChunkVariable = variable => isKnowledgeChunkInput(variable, props.nodeData.chunk_structure)

function updateChunkStructure(value) {
  const forcesHighQuality = ['hierarchical_model', 'qa_model'].includes(value)
  emitUpdate(normalizeKnowledgeBaseData({
    ...props.nodeData,
    chunk_structure: value,
    index_chunk_variable_selector: [],
    ...(forcesHighQuality ? { indexing_technique: 'high_quality' } : {}),
  }))
}

function updateIndexingTechnique(value) {
  const retrievalModel = {
    ...(props.nodeData.retrieval_model || {}),
    ...(value === 'economy'
      ? { search_method: 'keyword_search', reranking_enable: false }
      : props.nodeData.retrieval_model?.search_method === 'keyword_search'
        ? { search_method: 'semantic_search' }
        : {}),
  }
  emitUpdate(normalizeKnowledgeBaseData({
    ...props.nodeData,
    indexing_technique: value,
    retrieval_model: retrievalModel,
  }))
}

const embeddingKey = computed(() => props.nodeData.embedding_model_provider && props.nodeData.embedding_model
  ? `${props.nodeData.embedding_model_provider}::${props.nodeData.embedding_model}`
  : '')
const rerankKey = computed(() => {
  const model = props.nodeData.retrieval_model?.reranking_model
  return model?.reranking_provider_name && model?.reranking_model_name
    ? `${model.reranking_provider_name}::${model.reranking_model_name}`
    : ''
})

function updateEmbeddingModel(key) {
  const [provider = '', model = ''] = String(key || '').split('::')
  emitUpdate(normalizeKnowledgeBaseData({
    ...props.nodeData,
    embedding_model_provider: provider,
    embedding_model: model,
  }))
}

function updateRerankModel(key) {
  const [provider = '', model = ''] = String(key || '').split('::')
  updateRetrieval({
    reranking_model: {
      reranking_provider_name: provider,
      reranking_model_name: model,
    },
  })
}

onMounted(async () => {
  const [embedding, rerank] = await Promise.allSettled([
    fetchModelsByType('text-embedding'),
    fetchModelsByType('rerank'),
  ])
  embeddingModels.value = embedding.status === 'fulfilled' ? flattenModelCatalog(embedding.value) : []
  rerankModels.value = rerank.status === 'fulfilled' ? flattenModelCatalog(rerank.value) : []
})
</script>
