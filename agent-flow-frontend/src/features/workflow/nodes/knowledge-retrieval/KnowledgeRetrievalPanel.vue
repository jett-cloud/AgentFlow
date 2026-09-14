<!-- src/views/copilot/components/workflow/panel/knowledge-retrieval/KnowledgeRetrievalPanel.vue -->
<template>
  <div class="kr-panel">
    <PanelHeader
      block-type="knowledge-retrieval"
      :title="nodeTitle"
      :description="nodeData.desc"
      :legacy-description="nodeData.description"
      placeholder="知识检索"
      :read-only="readOnly"
      @update:title="onTitleChange"
      @update:description="onDescriptionChange"
      @close="$emit('close')"
    />

    <div class="panel-body">
      <PanelSection label="知识库" required>
        <div v-if="selectedDatasets.length" class="dataset-chips">
          <div v-for="item in selectedDatasets" :key="item.id" class="chip">
            <span>{{ item.name }}</span>
            <button
              v-if="!readOnly"
              type="button"
              class="chip-x"
              @click="removeDataset(item.id)"
            >
              ×
            </button>
          </div>
        </div>
        <el-select
          :model-value="datasetIds"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          class="w-full"
          placeholder="选择知识库"
          :disabled="readOnly || datasetStore.loading"
          @update:model-value="datasetIds = $event"
        >
          <el-option
            v-for="item in datasetStore.datasets"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>
        <p v-if="datasetStore.loadError" class="hint error">{{ datasetStore.loadError }}</p>
        <p v-else-if="!datasetStore.datasets.length && !datasetStore.loading" class="hint">
          暂无知识库，请先到
          <RouterLink to="/datasets">知识库</RouterLink>
          创建并上传文档。
        </p>
        <p v-else class="hint">
          <RouterLink to="/datasets">管理知识库 →</RouterLink>
        </p>
      </PanelSection>

      <PanelSection label="查询变量 (Query Variable)">
        <VarReferencePicker
          v-model="querySelector"
          :node-id="nodeId"
          :filter-var="isKnowledgeQueryInput"
          placeholder="选择查询变量，如 start.query"
          :read-only="readOnly"
        />
      </PanelSection>

      <PanelSection label="查询附件 (Query Attachment)">
        <VarReferencePicker
          v-model="queryAttachmentSelector"
          :node-id="nodeId"
          :filter-var="isKnowledgeAttachmentInput"
          placeholder="可选：选择图片文件或文件数组"
          :read-only="readOnly"
        />
      </PanelSection>

      <PanelSection label="检索模式 (Retrieval Mode)">
        <el-select
          v-model="retrievalMode"
          class="w-full"
          size="small"
          :disabled="readOnly"
        >
          <el-option
            v-for="mode in RETRIEVAL_MODES"
            :key="mode.value"
            :label="mode.label"
            :value="mode.value"
          />
        </el-select>
      </PanelSection>

      <template v-if="retrievalMode === 'multiple'">
        <PanelSection label="Top K 召回条数">
          <div class="slider-row">
            <el-slider v-model="topK" :min="1" :max="10" :step="1" :disabled="readOnly" />
            <span class="val-badge">{{ topK }}</span>
          </div>
        </PanelSection>

        <PanelSection label="Score 匹配度阈值">
          <div class="switch-row">
            <el-switch v-model="scoreThresholdEnabled" :disabled="readOnly" />
            <span class="hint">启用后过滤低相关片段</span>
          </div>
          <div v-if="scoreThresholdEnabled" class="slider-row">
            <el-slider v-model="scoreThreshold" :min="0" :max="1" :step="0.05" :disabled="readOnly" />
            <span class="val-badge">{{ scoreThreshold }}</span>
          </div>
        </PanelSection>

        <PanelSection label="Rerank">
          <div class="switch-row">
            <el-switch v-model="rerankingEnable" :disabled="readOnly" />
            <span class="hint">启用重排序或切换加权得分</span>
          </div>
          <div v-if="rerankingEnable || rerankingMode === 'weighted_score'" class="rerank-model">
            <el-radio-group v-model="rerankingMode" size="small" :disabled="readOnly">
              <el-radio-button
                v-for="mode in RERANKING_MODES"
                :key="mode.value"
                :value="mode.value"
              >
                {{ mode.label }}
              </el-radio-button>
            </el-radio-group>
            <template v-if="rerankingMode === 'reranking_model' && rerankingEnable">
            <el-select
              :model-value="rerankKey"
              filterable
              clearable
              placeholder="选择 Rerank 模型"
              class="w-full"
              :disabled="readOnly"
              @update:model-value="onRerankSelect"
            >
              <el-option
                v-for="m in rerankModels"
                :key="`${m.provider}/${m.model}`"
                :label="`${m.providerLabel} / ${m.label}`"
                :value="`${m.provider}::${m.model}`"
              />
            </el-select>
            <p v-if="!rerankModels.length" class="hint">
              未检测到 Rerank 模型，请到
              <RouterLink to="/integrations?tab=models">工作区集成</RouterLink>
              配置。
            </p>
            </template>
            <template v-else-if="rerankingMode === 'weighted_score'">
              <div class="slider-row">
                <span class="hint">语义 {{ vectorWeight }}</span>
                <el-slider :model-value="vectorWeight" :min="0" :max="1" :step="0.05" :disabled="readOnly" @update:model-value="onVectorWeight" />
              </div>
              <div class="slider-row">
                <span class="hint">关键词 {{ keywordWeight }}</span>
                <el-slider :model-value="keywordWeight" :min="0" :max="1" :step="0.05" :disabled="readOnly" @update:model-value="onKeywordWeight" />
              </div>
              <p v-if="weightedEmbeddingHint" class="hint error">{{ weightedEmbeddingHint }}</p>
              <p v-else class="hint">Embedding：{{ weightedScore?.vector_setting?.embedding_provider_name }} / {{ weightedScore?.vector_setting?.embedding_model_name }}</p>
            </template>
          </div>
        </PanelSection>
      </template>

      <PanelSection v-else label="N 选 1 推理模型" required>
        <ModelSelector v-model="singleModel" :read-only="readOnly" />
        <p class="hint">由模型根据知识库描述选择最匹配的单个库进行检索。</p>
      </PanelSection>

      <PanelSection label="元数据过滤">
        <el-select
          v-model="metadataFilteringMode"
          class="w-full"
          size="small"
          :disabled="readOnly"
        >
          <el-option
            v-for="mode in METADATA_FILTER_MODES"
            :key="mode.value"
            :label="mode.label"
            :value="mode.value"
          />
        </el-select>

        <div v-if="metadataFilteringMode === 'automatic'" class="meta-block">
          <p class="hint">自动模式需要指定用于推断过滤条件的模型。</p>
          <ModelSelector v-model="metadataModel" :read-only="readOnly" />
        </div>

        <div v-if="metadataFilteringMode === 'manual'" class="meta-block">
          <div class="switch-row">
            <span class="hint">条件逻辑</span>
            <el-radio-group v-model="metadataLogicalOperator" size="small" :disabled="readOnly">
              <el-radio-button value="and">AND</el-radio-button>
              <el-radio-button value="or">OR</el-radio-button>
            </el-radio-group>
          </div>
          <p v-if="!sharedMetadata.length" class="hint">
            所选知识库没有共同元数据。请先在知识库设置中定义字段。
          </p>
          <div
            v-for="cond in metadataConditions.conditions"
            :key="cond.id"
            class="cond-row"
          >
            <el-select
              :model-value="conditionFieldKey(cond)"
              size="small"
              filterable
              placeholder="选择字段"
              :disabled="readOnly"
              @update:model-value="key => onConditionField(cond, key)"
            >
              <el-option
                v-for="field in sharedMetadata"
                :key="fieldKey(field)"
                :label="`${field.name} (${typeLabel(field.type)})`"
                :value="fieldKey(field)"
              />
            </el-select>
            <el-select
              :model-value="cond.comparison_operator"
              size="small"
              :disabled="readOnly"
              @update:model-value="op => updateMetadataCondition(cond.id, { comparison_operator: op })"
            >
              <el-option
                v-for="op in operatorsForCondition(cond)"
                :key="op"
                :label="op"
                :value="op"
              />
            </el-select>
            <el-input-number
              v-if="conditionType(cond) === 'number' && operatorRequiresValue(cond.comparison_operator)"
              :model-value="Number(cond.value) || 0"
              size="small"
              controls-position="right"
              :disabled="readOnly"
              @update:model-value="val => updateMetadataCondition(cond.id, { value: val })"
            />
            <el-date-picker
              v-else-if="conditionType(cond) === 'time' && operatorRequiresValue(cond.comparison_operator)"
              :model-value="cond.value"
              type="datetime"
              size="small"
              value-format="YYYY-MM-DD HH:mm:ss"
              placeholder="时间"
              :disabled="readOnly"
              @update:model-value="val => updateMetadataCondition(cond.id, { value: val })"
            />
            <el-input
              v-else-if="operatorRequiresValue(cond.comparison_operator)"
              :model-value="cond.value"
              placeholder="值"
              size="small"
              :disabled="readOnly"
              @update:model-value="updateMetadataCondition(cond.id, { value: $event })"
            />
            <span v-else class="hint">无需填值</span>
            <el-button
              v-if="!readOnly"
              link
              type="danger"
              @click="removeMetadataCondition(cond.id)"
            >
              删
            </el-button>
          </div>
          <el-select
            v-if="!readOnly && remainingMetadata.length"
            :model-value="''"
            size="small"
            placeholder="添加条件"
            class="add-cond"
            @update:model-value="onAddCondition"
          >
            <el-option
              v-for="field in remainingMetadata"
              :key="fieldKey(field)"
              :label="`${field.name} (${typeLabel(field.type)})`"
              :value="fieldKey(field)"
            />
          </el-select>
        </div>
      </PanelSection>

      <PanelSection label="输出变量" border-top>
        <OutputVarList node-type="knowledge-retrieval" />
      </PanelSection>

      <NextStep
        :node-id="nodeId"
        :node-data="nodeData"
        :read-only="readOnly"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import PanelHeader from '../shared/PanelHeader.vue'
import PanelSection from '../shared/PanelSection.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import OutputVarList from '../shared/OutputVarList.vue'
import NextStep from '../shared/NextStep.vue'
import ModelSelector from '../shared/ModelSelector.vue'
import {
  useKnowledgeRetrievalConfig,
  RETRIEVAL_MODES,
  RERANKING_MODES,
  METADATA_FILTER_MODES,
} from './useKnowledgeRetrievalConfig.js'
import { useDatasetStore } from '@/features/datasets/state/useDatasetStore.js'
import { fetchDatasetMetadata } from '@/features/datasets/api/difyDatasetsApi.js'
import { fetchModelsByType } from '@/features/integrations/api/difyModelsApi.js'
import {
  isKnowledgeAttachmentInput,
  isKnowledgeQueryInput,
  syncWeightedScoreEmbedding,
} from './knowledgeRetrievalNode.js'
import {
  defaultOperatorForType,
  fieldForCondition,
  intersectMetadataByName,
  METADATA_TYPES,
  operatorRequiresValue,
  operatorsForMetadataType,
} from '@/features/datasets/model/metadataFields.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'update:nodeData'])
const datasetStore = useDatasetStore()
const rerankModels = ref([])

const {
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
} = useKnowledgeRetrievalConfig(props, emit)

const selectedDatasets = computed(() => {
  const ids = new Set(datasetIds.value)
  return datasetStore.datasets.filter(d => ids.has(d.id))
})

const vectorWeight = computed(() => Number(weightedScore.value?.vector_setting?.vector_weight ?? 0.7))
const keywordWeight = computed(() => Number(weightedScore.value?.keyword_setting?.keyword_weight ?? 0.3))
const weightedEmbeddingHint = computed(() => {
  const provider = weightedScore.value?.vector_setting?.embedding_provider_name
  const model = weightedScore.value?.vector_setting?.embedding_model_name
  if (provider && model)
    return ''
  return '所选知识库没有 embedding 配置，无法保存加权得分。'
})

watch([rerankingMode, selectedDatasets], () => {
  if (rerankingMode.value !== 'weighted_score')
    return
  const next = syncWeightedScoreEmbedding(weightedScore.value, selectedDatasets.value)
  const current = weightedScore.value
  if (
    current?.vector_setting?.vector_weight === next.vector_setting.vector_weight
    && current?.keyword_setting?.keyword_weight === next.keyword_setting.keyword_weight
    && current?.vector_setting?.embedding_provider_name === next.vector_setting.embedding_provider_name
    && current?.vector_setting?.embedding_model_name === next.vector_setting.embedding_model_name
  )
    return
  weightedScore.value = next
}, { deep: true })

function onVectorWeight(value) {
  const next = Number(value)
  onWeightPair(next, Number((1 - next).toFixed(2)))
}

function onKeywordWeight(value) {
  const next = Number(value)
  onWeightPair(Number((1 - next).toFixed(2)), next)
}

function onWeightPair(vector, keyword) {
  const synced = syncWeightedScoreEmbedding(weightedScore.value, selectedDatasets.value)
  weightedScore.value = {
    vector_setting: {
      ...synced.vector_setting,
      vector_weight: vector,
    },
    keyword_setting: { keyword_weight: keyword },
  }
}

const sharedMetadata = computed(() => intersectMetadataByName(
  selectedDatasets.value.map(dataset => dataset.doc_metadata || []),
))

const usedFieldKeys = computed(() => new Set(
  metadataConditions.value.conditions.map(cond => conditionFieldKey(cond)).filter(Boolean),
))

const remainingMetadata = computed(() =>
  sharedMetadata.value.filter(field => !usedFieldKeys.value.has(fieldKey(field))),
)

const rerankKey = computed(() => {
  const provider = rerankModel.value?.provider
  const name = rerankModel.value?.name
  return provider && name ? `${provider}::${name}` : ''
})

function fieldKey(field) {
  return field ? `${field.id}::${field.name}` : ''
}

function conditionFieldKey(cond) {
  const field = fieldForCondition(cond, sharedMetadata.value)
  return field ? fieldKey(field) : (cond.metadata_id && cond.name ? `${cond.metadata_id}::${cond.name}` : '')
}

function conditionType(cond) {
  return fieldForCondition(cond, sharedMetadata.value)?.type || 'string'
}

function typeLabel(type) {
  return METADATA_TYPES.find(item => item.value === type)?.label || type || '文本'
}

function operatorsForCondition(cond) {
  return operatorsForMetadataType(conditionType(cond))
}

function onConditionField(cond, key) {
  const field = sharedMetadata.value.find(item => fieldKey(item) === key)
  if (!field)
    return
  const operators = operatorsForMetadataType(field.type)
  const operator = operators.includes(cond.comparison_operator)
    ? cond.comparison_operator
    : defaultOperatorForType(field.type)
  updateMetadataCondition(cond.id, {
    metadata_id: field.id,
    name: field.name,
    comparison_operator: operator,
    value: operatorRequiresValue(operator) ? cond.value : '',
  })
}

function onAddCondition(key) {
  const field = remainingMetadata.value.find(item => fieldKey(item) === key)
    || sharedMetadata.value.find(item => fieldKey(item) === key)
  addMetadataCondition(field)
}

function removeDataset(id) {
  datasetIds.value = datasetIds.value.filter(x => x !== id)
}

function onRerankSelect(key) {
  if (!key) {
    rerankModel.value = { provider: '', name: '', mode: 'rerank', completion_params: {} }
    return
  }
  const [provider, name] = String(key).split('::')
  rerankModel.value = { provider, name, mode: 'rerank', completion_params: {} }
}

async function loadRerankModels() {
  try {
    const res = await fetchModelsByType('rerank')
    const data = res?.data || res || []
    const list = []
    ;(Array.isArray(data) ? data : []).forEach((p) => {
      const provider = p.provider || p.provider_name || ''
      const providerLabel = p.label?.zh_Hans || p.label?.en_US || p.label || provider
      ;(p.models || []).forEach((m) => {
        const model = m.model || m.model_name
        if (!model)
          return
        list.push({
          provider,
          providerLabel,
          model,
          label: m.label?.zh_Hans || m.label?.en_US || m.label || model,
        })
      })
    })
    rerankModels.value = list
  }
  catch {
    rerankModels.value = []
  }
}

onMounted(() => {
  datasetStore.loadDatasets()
  loadRerankModels()
})

watch(datasetIds, async (ids) => {
  for (const id of ids || []) {
    const dataset = datasetStore.datasets.find(item => item.id === id)
    if (!dataset || Array.isArray(dataset.doc_metadata))
      continue
    try {
      const res = await fetchDatasetMetadata(id)
      dataset.doc_metadata = res.doc_metadata || res.data?.doc_metadata || []
    }
    catch {
      dataset.doc_metadata = []
    }
  }
}, { immediate: true })

const nodeTitle = computed({
  get: () => props.nodeData?.title || '知识检索',
  set: (val) => emit('update:nodeData', { ...props.nodeData, title: val }),
})

function onTitleChange(val) {
  emit('update:nodeData', { ...props.nodeData, title: val })
}

function onDescriptionChange(val) {
  const { description: _legacyDescription, ...nodeData } = props.nodeData
  emit('update:nodeData', { ...nodeData, desc: val })
}
</script>

<style scoped>
.kr-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: #fff;
  border-left: 1px solid #eaecf0;
}
.panel-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.dataset-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eff4ff;
  color: #3538cd;
  font-size: 12px;
}
.chip-x {
  border: none;
  background: transparent;
  cursor: pointer;
  color: #6172f3;
  font-size: 14px;
  line-height: 1;
  padding: 0;
}
.slider-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.slider-row .el-slider { flex: 1; }
.switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.val-badge {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: #344054;
  min-width: 28px;
  text-align: right;
}
.meta-block {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cond-row {
  display: grid;
  grid-template-columns: 1fr 110px 1fr auto;
  gap: 6px;
  align-items: center;
}
.add-cond { width: 180px; }
.hint { margin: 0; font-size: 12px; color: #667085; }
.hint.error { color: #b42318; }
.w-full { width: 100%; }
.rerank-model {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
</style>
