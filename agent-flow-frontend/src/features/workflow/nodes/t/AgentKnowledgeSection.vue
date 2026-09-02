<template>
  <PanelSection label="知识库（Soul Knowledge）">
    <p class="hint">
      知识库不会出现在上方「工具」列表里。选择知识库后点「添加 Set」（或收起下拉框）写入 Soul；查询策略请保持「Agent 生成查询」，运行时才会挂载
      <code>knowledge_base_search</code> 工具。
    </p>

    <div v-if="!readOnly" class="add-row">
      <el-select
        v-model="draftDatasetIds"
        multiple
        filterable
        collapse-tags
        collapse-tags-tooltip
        class="w-full"
        placeholder="选择知识库以新增 set…"
        :disabled="datasetStore.loading"
        @visible-change="onAddSelectVisible"
      >
        <el-option
          v-for="ds in datasetStore.datasets"
          :key="ds.id"
          :label="ds.name || ds.id"
          :value="ds.id"
        />
      </el-select>
      <el-button size="small" type="primary" :disabled="!draftDatasetIds.length" @click="onAddSet">
        添加 Set
      </el-button>
    </div>
    <p v-if="datasetStore.loadError" class="hint error">{{ datasetStore.loadError }}</p>

    <div v-if="sets.length" class="set-list">
      <div v-for="set in sets" :key="set.id" class="set-card">
        <div class="set-header">
          <el-input
            :model-value="set.name"
            size="small"
            :disabled="readOnly"
            placeholder="Set 名称"
            @update:model-value="(val) => patchSet(set.id, { name: val })"
          />
          <el-button
            v-if="!readOnly"
            size="small"
            text
            type="danger"
            @click="onRemoveSet(set.id)"
          >
            删除
          </el-button>
        </div>

        <label class="field">
          <span>知识库</span>
          <el-select
            :model-value="(set.datasets || []).map(d => d.id)"
            multiple
            filterable
            collapse-tags
            class="w-full"
            :disabled="readOnly"
            @change="(ids) => onDatasetsChange(set.id, ids)"
          >
            <el-option
              v-for="ds in datasetStore.datasets"
              :key="ds.id"
              :label="ds.name || ds.id"
              :value="ds.id"
            />
          </el-select>
        </label>

        <label class="field">
          <span>查询策略</span>
          <el-select
            :model-value="set.query?.mode || 'generated_query'"
            size="small"
            class="w-full"
            :disabled="readOnly"
            @change="(mode) => patchSet(set.id, { query: { mode } })"
          >
            <el-option label="Agent 生成查询" value="generated_query" />
            <el-option label="自定义查询" value="user_query" />
          </el-select>
        </label>
        <label v-if="set.query?.mode === 'user_query'" class="field">
          <span>自定义 Query</span>
          <el-input
            :model-value="set.query?.value || ''"
            size="small"
            :disabled="readOnly"
            placeholder="固定检索语句"
            @update:model-value="(val) => patchSet(set.id, { query: { mode: 'user_query', value: val } })"
          />
        </label>

        <label class="field">
          <span>召回模式</span>
          <el-select
            :model-value="set.retrieval?.mode || 'multiple'"
            size="small"
            class="w-full"
            :disabled="readOnly"
            @change="(mode) => patchSet(set.id, { retrieval: { mode } })"
          >
            <el-option label="多路召回" value="multiple" />
            <el-option label="N 选 1" value="single" />
          </el-select>
        </label>

        <div v-if="(set.retrieval?.mode || 'multiple') === 'multiple'" class="field-row">
          <label class="field">
            <span>Top K</span>
            <el-input-number
              :model-value="set.retrieval?.top_k ?? 4"
              :min="1"
              :max="20"
              size="small"
              :disabled="readOnly"
              @update:model-value="(val) => patchSet(set.id, { retrieval: { top_k: val } })"
            />
          </label>
          <label class="field switch-field">
            <span>Score 阈值</span>
            <el-switch
              :model-value="set.retrieval?.score_threshold != null"
              size="small"
              :disabled="readOnly"
              @change="(on) => patchSet(set.id, {
                retrieval: { score_threshold: on ? (set.retrieval?.score_threshold ?? 0.5) : null },
              })"
            />
          </label>
          <label v-if="set.retrieval?.score_threshold != null" class="field">
            <span>阈值</span>
            <el-input-number
              :model-value="set.retrieval.score_threshold"
              :min="0"
              :max="1"
              :step="0.05"
              size="small"
              :disabled="readOnly"
              @update:model-value="(val) => patchSet(set.id, { retrieval: { score_threshold: val } })"
            />
          </label>
          <label class="field switch-field">
            <span>Rerank</span>
            <el-switch
              :model-value="!!set.retrieval?.reranking_enable"
              size="small"
              :disabled="readOnly"
              @change="(val) => patchSet(set.id, { retrieval: { reranking_enable: !!val } })"
            />
          </label>
        </div>
      </div>
    </div>
    <p v-else class="hint">尚未配置知识集。当前 Agent 看不到知识库，也无法调用 knowledge_base_search。</p>
  </PanelSection>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import PanelSection from '../shared/PanelSection.vue'
import { useDatasetStore } from '@/features/datasets/state/useDatasetStore.js'
import {
  addKnowledgeSet,
  datasetIdsToRefs,
  removeKnowledgeSet,
  updateKnowledgeSet,
} from './agentKnowledge.js'

const props = defineProps({
  sets: { type: Array, default: () => [] },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['update:sets'])

const datasetStore = useDatasetStore()
const draftDatasetIds = ref([])

onMounted(() => {
  datasetStore.loadDatasets({ page: 1, limit: 100 })
})

function onAddSet() {
  const refs = datasetIdsToRefs(draftDatasetIds.value, id => datasetStore.findById(id))
  if (!refs.length)
    return
  emit('update:sets', addKnowledgeSet(props.sets, {}, refs))
  draftDatasetIds.value = []
}

function onAddSelectVisible(open) {
  if (!open && draftDatasetIds.value.length)
    onAddSet()
}

function onRemoveSet(setId) {
  emit('update:sets', removeKnowledgeSet(props.sets, setId))
}

function patchSet(setId, patch) {
  emit('update:sets', updateKnowledgeSet(props.sets, setId, patch))
}

function onDatasetsChange(setId, ids) {
  const refs = datasetIdsToRefs(ids, id => datasetStore.findById(id))
  patchSet(setId, { datasets: refs })
}
</script>

<style scoped>
.w-full { width: 100%; }
.hint { margin: 0 0 8px; font-size: 12px; color: #667085; }
.hint.error { color: #b42318; }
.add-row { display: flex; gap: 8px; align-items: flex-start; margin-bottom: 8px; }
.set-list { display: flex; flex-direction: column; gap: 10px; }
.set-card {
  border: 1px solid #eaecf0;
  border-radius: 8px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.set-header { display: flex; gap: 8px; align-items: center; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #475467; }
.field-row { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
.switch-field { min-width: 90px; }
</style>
