<template>
  <div class="email-config">
    <el-checkbox
      :model-value="config.recipients.include_bound_group"
      :disabled="readOnly"
      @update:model-value="updateRecipients({ include_bound_group: $event })"
    >
      包含当前绑定群组
    </el-checkbox>
    <HumanInputMemberSelector
      :model-value="config.recipients.items"
      :read-only="readOnly"
      @update:model-value="updateMemberItems"
    />
    <div class="field">
      <span class="label">外部收件邮箱</span>
      <el-input
        :model-value="externalEmails"
        type="textarea"
        :rows="2"
        placeholder="多个邮箱用换行、逗号或分号分隔"
        :disabled="readOnly"
        @update:model-value="updateExternalEmails"
      />
    </div>
    <div class="field">
      <span class="label">邮件主题</span>
      <el-input
        :model-value="config.subject"
        :disabled="readOnly"
        @update:model-value="updateConfig({ subject: $event })"
      />
    </div>
    <div class="field">
      <span class="label" v-text="urlRequirement" />
      <el-input
        :model-value="config.body"
        type="textarea"
        :rows="4"
        :disabled="readOnly"
        @update:model-value="updateConfig({ body: $event })"
      />
    </div>
    <el-checkbox
      :model-value="config.debug_mode"
      :disabled="readOnly"
      @update:model-value="updateConfig({ debug_mode: $event })"
    >
      调试模式
    </el-checkbox>
    <div v-if="emailIncomplete" class="incomplete" v-text="incompleteHint" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import HumanInputMemberSelector from './HumanInputMemberSelector.vue'
import {
  externalEmailsToRecipients,
  isHumanInputDeliveryValid,
  normalizeHumanInputEmailConfig,
} from './humanInputNode.js'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])
const urlRequirement = '邮件正文（必须包含 {{#url#}}）'
const incompleteHint = '启用邮件时需要主题、包含 {{#url#}} 的正文，以及绑定群组或至少一个收件人'
const config = computed(() => normalizeHumanInputEmailConfig(props.modelValue))
const externalEmails = computed(() => config.value.recipients.items
  .filter(item => item.type === 'external')
  .map(item => item.email)
  .join('\n'))

function updateConfig(partial) {
  emit('update:modelValue', normalizeHumanInputEmailConfig({ ...config.value, ...partial }))
}

function updateRecipients(partial) {
  updateConfig({ recipients: { ...config.value.recipients, ...partial } })
}

function updateMemberItems(items) {
  const externals = config.value.recipients.items.filter(item => item.type === 'external')
  const members = (Array.isArray(items) ? items : []).filter(item => item.type === 'member')
  updateRecipients({ items: [...members, ...externals] })
}

function updateExternalEmails(value) {
  const members = config.value.recipients.items.filter(item => item.type === 'member')
  updateRecipients({ items: [...members, ...externalEmailsToRecipients(value)] })
}

const emailIncomplete = computed(() => !isHumanInputDeliveryValid({
  type: 'email',
  enabled: true,
  config: config.value,
}))
</script>

<style scoped>
.email-config { display: flex; flex-direction: column; gap: 10px; padding: 10px; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; }
.field { display: flex; flex-direction: column; gap: 4px; }
.label { color: #475569; font-size: 11px; font-weight: 600; }
.incomplete { color: #b42318; font-size: 12px; }
</style>
