<template>
  <div v-if="visibleForms.length" class="human-input-form-list" aria-label="人工输入表单">
    <h3>等待人工输入</h3>
    <HumanInputForm
      v-for="form in visibleForms"
      :key="form.form_id || form.node_id || form.form_token"
      :form-data="form"
      :submit-form="submitForm"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import HumanInputForm from './HumanInputForm.vue'
import { getVisibleHumanInputForms } from './humanInputFormUtils.js'

const props = defineProps({
  forms: { type: Array, default: () => [] },
  submitForm: { type: Function, required: true },
})

const visibleForms = computed(() => getVisibleHumanInputForms(props.forms))
</script>

<style scoped>
.human-input-form-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 12px;
}

h3 {
  margin: 0;
  color: #b54708;
  font-size: 11px;
  text-transform: uppercase;
}
</style>
