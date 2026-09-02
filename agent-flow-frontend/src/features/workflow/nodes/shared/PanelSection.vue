<!-- panel/base/PanelSection.vue -->
<template>
  <div class="panel-section" :class="{ 'with-border': borderTop }">
    <div v-if="label || $slots.extra" class="section-header">
      <label v-if="label" class="section-label">
        {{ label }}
        <span v-if="required" class="required">*</span>
        <slot name="label-extra" />
      </label>
      <slot name="extra" />
    </div>
    <slot />
  </div>
</template>

<script setup>
defineProps({
  label: { type: String, default: '' },
  required: { type: Boolean, default: false },
  borderTop: { type: Boolean, default: false },
})
</script>

<style scoped>
.panel-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.panel-section.with-border {
  border-top: 1px solid #f2f4f7;
  padding-top: 12px;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.section-label {
  font-size: 12px;
  font-weight: 600;
  color: #344054;
  display: flex;
  align-items: center;
  gap: 4px;
}
.required {
  color: #f04438;
}
</style>
