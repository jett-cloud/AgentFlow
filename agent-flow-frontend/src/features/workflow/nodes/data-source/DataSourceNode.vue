<template>
  <BaseNode :id="id" :data="data" :selected="selected" :read-only="readOnly">
    <div class="data-source-content">
      <SettingRow label="提供方" :value="providerLabel" :warning="!providerLabel" />
      <SettingRow
        v-if="data.datasource_label || data.datasource_name"
        label="数据源"
        :value="data.datasource_label || data.datasource_name"
      />
      <div v-if="data._pluginMissing" class="plugin-warning">需要安装对应插件</div>
      <div v-else-if="data._datasourceAuthorized === false" class="plugin-warning">需要授权数据源</div>
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

const providerLabel = computed(() =>
  props.data?.provider_name
  || props.data?.plugin_id
  || props.data?.provider_id
  || '',
)
</script>

<style scoped>
.data-source-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.plugin-warning {
  padding: 5px 7px;
  border: 1px solid #fedf89;
  border-radius: 6px;
  background: #fffaeb;
  color: #b54708;
  font-size: 10px;
}
</style>
