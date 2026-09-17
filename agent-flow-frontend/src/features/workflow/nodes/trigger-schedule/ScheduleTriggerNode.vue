<template>
  <BaseNode :id="id" :data="data" :selected="selected" :read-only="readOnly">
    <div class="trigger-content">
      <SettingRow label="计划" :value="scheduleValue" :warning="!scheduleValue" />
      <SettingRow v-if="data.timezone" label="时区" :value="data.timezone" />
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

const scheduleValue = computed(() =>
  props.data?.cron
  || props.data?.cron_expression
  || props.data?.frequency
  || '',
)
</script>

<style scoped>
.trigger-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
</style>
