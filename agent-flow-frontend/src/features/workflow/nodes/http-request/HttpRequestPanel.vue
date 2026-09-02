<!-- src/views/copilot/components/workflow/panel/http-request/HttpRequestPanel.vue -->
<template>
  <div class="http-panel">
    <div class="panel-header">
      <div class="header-left">
        <BlockIcon type="http-request" :size="20" />
        <input v-model="nodeTitle" class="title-input" placeholder="HTTP 请求" :disabled="readOnly" />
      </div>
      <button class="close-btn" @click="$emit('close')"><el-icon><Close /></el-icon></button>
    </div>

    <div class="panel-body">
      <div class="form-section">
        <label class="section-label">请求方法 (HTTP Method)</label>
        <el-select v-model="method" class="w-full" size="small" :disabled="readOnly">
          <el-option label="GET" value="get" />
          <el-option label="POST" value="post" />
          <el-option label="PUT" value="put" />
          <el-option label="DELETE" value="delete" />
          <el-option label="PATCH" value="patch" />
          <el-option label="HEAD" value="head" />
        </el-select>
      </div>

      <div class="form-section">
        <label class="section-label">请求 URL</label>
        <el-input v-model="url" placeholder="https://api.example.com/v1/endpoint" size="small" :disabled="readOnly" />
      </div>

      <div class="form-section">
        <label class="section-label">Headers (请求头)</label>
        <el-input v-model="headers" type="textarea" :rows="3" placeholder="Key: Value" class="font-mono text-xs" :disabled="readOnly" />
      </div>

      <div class="form-section">
        <label class="section-label">Query Params (查询参数)</label>
        <el-input v-model="params" type="textarea" :rows="2" placeholder="key=value" class="font-mono text-xs" :disabled="readOnly" />
      </div>

      <div class="form-section">
        <label class="section-label">认证</label>
        <el-select v-model="authorization.type" class="w-full" size="small" :disabled="readOnly">
          <el-option label="无认证" value="no-auth" />
          <el-option label="API Key" value="api-key" />
        </el-select>
      </div>

      <div class="form-section">
        <label class="section-label">Body 类型</label>
        <el-select v-model="bodyType" class="w-full" size="small" :disabled="readOnly">
          <el-option label="none" value="none" />
          <el-option label="JSON" value="json" />
          <el-option label="raw-text" value="raw-text" />
          <el-option label="form-data" value="form-data" />
          <el-option label="x-www-form-urlencoded" value="x-www-form-urlencoded" />
          <el-option label="binary" value="binary" />
        </el-select>
      </div>

      <div class="form-section">
        <label class="section-label">超时 (毫秒)</label>
        <el-input-number v-model="timeout.max_read_timeout" :min="0" size="small" :disabled="readOnly" />
      </div>
      <div class="form-section inline-section">
        <label class="section-label">验证 SSL</label>
        <el-switch v-model="sslVerify" :disabled="readOnly" />
      </div>
      <div class="form-section inline-section">
        <label class="section-label">失败重试</label>
        <el-switch v-model="retryConfig.retry_enabled" :disabled="readOnly" />
      </div>

      <div class="form-section" v-if="bodyType !== 'none'">
        <label class="section-label">Body</label>
        <el-input
          v-model="body"
          type="textarea"
          :rows="5"
          placeholder='{\n  "query": "{{#start.query#}}"\n}'
          class="font-mono text-xs"
          :disabled="readOnly"
        />
      </div>

      <NextStep :node-id="nodeId" :node-data="nodeData" :read-only="readOnly" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Close } from '@element-plus/icons-vue'
import BlockIcon from '../base/BlockIcon.vue'
import NextStep from '../shared/NextStep.vue'
import { useHttpRequestConfig } from './useHttpRequestConfig.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false }
})
const emit = defineEmits(['close', 'update:nodeData'])

const { readOnly, method, url, headers, params, body, bodyType, authorization, timeout, sslVerify, retryConfig } = useHttpRequestConfig(props, emit)

const nodeTitle = computed({
  get: () => props.nodeData?.title || 'HTTP 请求',
  set: (val) => emit('update:nodeData', { ...props.nodeData, title: val })
})
</script>

<style scoped>
.http-panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: #fff; border-left: 1px solid #eaecf0; }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid #f2f4f7; background: #fafafa; }
.header-left { display: flex; align-items: center; gap: 8px; flex: 1; }
.title-input { font-size: 14px; font-weight: 600; color: #101828; border: none; background: transparent; }
.close-btn { background: transparent; border: none; cursor: pointer; color: #667085; }
.panel-body { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.form-section { display: flex; flex-direction: column; gap: 8px; }
.section-label { font-size: 12px; font-weight: 600; color: #344054; }
</style>
