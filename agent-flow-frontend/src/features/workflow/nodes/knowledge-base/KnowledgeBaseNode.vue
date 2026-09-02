<template>
  <BaseNode :id="id" :data="data" :selected="selected" :read-only="readOnly">
    <div class="knowledge-base-content">
      <SettingRow
        label="分段变量"
        :value="chunkVariable"
        :warning="!data.chunk_structure"
      />
      <SettingRow label="索引方式" :value="indexingTechnique" :warning="!data.indexing_technique" />
      <SettingRow
        v-if="data.indexing_technique === 'high_quality'"
        label="Embedding"
        :value="data.embedding_model"
        :warning="!data.embedding_model"
      />
      <SettingRow
        label="检索方式"
        :value="retrievalMethod"
        :warning="!retrievalMethod"
      />
    </div>
  </BaseNode>
</template>

<script setup>
import { computed } from 'vue'
import BaseNode from '../base/BaseNode.vue'
import SettingRow from '../base/SettingRow.vue'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})

const chunkVariable = computed(() =>
  props.data?.index_chunk_variable_selector?.at?.(-1) || '',
)
const indexingTechnique = computed(() => ({
  high_quality: '高质量',
  economy: '经济',
}[props.data?.indexing_technique] || props.data?.indexing_technique || ''))
const retrievalMethod = computed(() =>
  props.data?.retrieval_model?.search_method || '',
)
</script>

<style scoped>
.knowledge-base-content {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
</style>
