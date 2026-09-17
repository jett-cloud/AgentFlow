<template>
  <div class="form-preview">
    <div v-for="(segment, index) in segments" :key="index">
      <div v-if="segment.type === 'text'" class="markdown" v-html="renderMarkdown(segment.text)" />
      <div v-else class="field-preview">
        <span class="field-name">{{ segment.name }}</span>
        <el-input v-if="fieldType(segment.name) === 'paragraph'" disabled type="textarea" :rows="2" placeholder="段落输入" />
        <el-select v-else-if="fieldType(segment.name) === 'select'" disabled placeholder="下拉选择" />
        <el-button v-else-if="fieldType(segment.name) === 'file'" disabled>上传文件</el-button>
        <el-button v-else-if="fieldType(segment.name) === 'file-list'" disabled>上传多个文件</el-button>
        <el-input v-else disabled :placeholder="segment.name" />
      </div>
    </div>
    <div class="actions">
      <el-button
        v-for="action in actions"
        :key="action.id"
        disabled
        :type="action.button_style === 'primary' ? 'primary' : 'default'"
        :class="humanInputPreviewActionClass(action.button_style)"
      >
        {{ action.title || action.id }}
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { renderMarkdown } from '../../utils/helpers.js'
import { splitHumanInputFormContent, humanInputPreviewActionClass } from './humanInputNode.js'

const props = defineProps({
  content: { type: String, default: '' },
  fields: { type: Array, default: () => [] },
  actions: { type: Array, default: () => [] },
})

const segments = computed(() => splitHumanInputFormContent(props.content))
const fieldType = name => props.fields.find(field => field.output_variable_name === name)?.type || 'paragraph'
</script>

<style scoped>
.form-preview { display: flex; flex-direction: column; gap: 10px; padding: 10px; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; }
.markdown :deep(a) { pointer-events: none; }
.field-preview { display: flex; flex-direction: column; gap: 4px; padding: 8px; border: 1px dashed #d0d5dd; border-radius: 6px; background: #f8fafc; }
.field-name { font-size: 11px; font-weight: 600; color: #475569; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.action-style-primary { --el-button-disabled-text-color: #155eef; --el-button-disabled-bg-color: #eff4ff; --el-button-disabled-border-color: #b2ccff; }
.action-style-default { --el-button-disabled-text-color: #475467; --el-button-disabled-bg-color: #f2f4f7; --el-button-disabled-border-color: #d0d5dd; }
.action-style-accent { --el-button-disabled-text-color: #6941c6; --el-button-disabled-bg-color: #f4ebff; --el-button-disabled-border-color: #d6bbfb; }
.action-style-ghost { --el-button-disabled-text-color: #344054; --el-button-disabled-bg-color: #ffffff; --el-button-disabled-border-color: #d0d5dd; }
</style>
