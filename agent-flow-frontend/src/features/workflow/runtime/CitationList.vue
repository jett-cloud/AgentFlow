<template>
  <!-- Contrasts Dify chat/citation chips + popup (document + segment + score + download). -->
  <div class="citation-list" aria-label="引用来源">
    <div class="citation-title">引用</div>
    <div class="chips">
      <div
        v-for="(group, index) in groups"
        :key="group.documentId || `${index}-${group.documentName}`"
        class="chip-wrap"
      >
        <button
          type="button"
          class="chip"
          :aria-expanded="openIndex === index"
          @click.stop="toggle(index)"
        >
          <span class="chip-label">{{ group.documentName }}</span>
          <span v-if="group.sources.length > 1" class="chip-count">{{ group.sources.length }}</span>
        </button>

        <div
          v-if="openIndex === index"
          class="popup"
          role="dialog"
          aria-label="引用详情"
          @click.stop
        >
          <header>
            <strong>{{ group.documentName }}</strong>
            <div class="header-actions">
              <button
                v-if="canDownloadCitationGroup(group)"
                type="button"
                class="download"
                :disabled="downloadingKey === groupKey(group)"
                @click="downloadGroup(group)"
              >
                {{ downloadingKey === groupKey(group) ? '下载中…' : '下载' }}
              </button>
              <button type="button" class="close" aria-label="关闭" @click="openIndex = -1">×</button>
            </div>
          </header>
          <p v-if="group.datasetName" class="dataset">{{ group.datasetName }}</p>
          <p v-if="downloadError && openIndex === index" class="download-error">{{ downloadError }}</p>
          <div
            v-for="(source, sourceIndex) in group.sources"
            :key="source.segment_id || `${sourceIndex}-${source.score}`"
            class="segment"
          >
            <div class="segment-meta">
              <span v-if="source.segment_position != null">#{{ source.segment_position }}</span>
              <span v-if="source.score != null" class="score">
                {{ Number(source.score).toFixed(2) }}
              </span>
            </div>
            <pre class="content">{{ source.content || '（无片段内容）' }}</pre>
            <div v-if="hasHitInfo(source)" class="hit-info">
              <span v-if="source.word_count != null">字数 {{ source.word_count }}</span>
              <span v-if="source.hit_count != null">命中 {{ source.hit_count }}</span>
              <span v-if="source.index_node_hash" :title="source.index_node_hash">
                hash {{ source.index_node_hash.slice(0, 7) }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { fetchDocumentDownloadUrl } from '@/features/datasets/api/difyDatasetsApi.js'
import { canDownloadCitationGroup, groupCitationsByDocument } from './citationUtils.js'

const props = defineProps({
  items: { type: Array, default: () => [] },
})

const openIndex = ref(-1)
const downloadingKey = ref('')
const downloadError = ref('')
const groups = computed(() => groupCitationsByDocument(props.items))

function toggle(index) {
  downloadError.value = ''
  openIndex.value = openIndex.value === index ? -1 : index
}

function groupKey(group) {
  return `${group.documentId || group.documentName}|${group.sources?.[0]?.dataset_id || ''}`
}

function hasHitInfo(source) {
  return source.word_count != null
    || source.hit_count != null
    || Boolean(source.index_node_hash)
}

async function downloadGroup(group) {
  if (!canDownloadCitationGroup(group) || downloadingKey.value)
    return
  const datasetId = group.sources[0].dataset_id
  const documentId = group.documentId || group.sources[0].document_id
  downloadingKey.value = groupKey(group)
  downloadError.value = ''
  try {
    const res = await fetchDocumentDownloadUrl(datasetId, documentId)
    const url = res?.url || res?.data?.url
    if (!url)
      throw new Error('未返回下载地址')
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = group.documentName || 'document'
    anchor.target = '_blank'
    anchor.rel = 'noopener noreferrer'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  }
  catch (err) {
    downloadError.value = err?.message || '下载失败'
  }
  finally {
    downloadingKey.value = ''
  }
}

function onDocumentClick() {
  openIndex.value = -1
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
})
</script>

<style scoped>
.citation-list {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #eaecf0;
}

.citation-title {
  margin-bottom: 6px;
  color: #98a2b3;
  font-size: 11px;
  font-weight: 600;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip-wrap {
  position: relative;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 220px;
  padding: 4px 8px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #f9fafb;
  color: #344054;
  font-size: 11px;
  cursor: pointer;
}

.chip:hover {
  border-color: #84adff;
  background: #eff4ff;
  color: #0033ff;
}

.chip-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-count {
  flex-shrink: 0;
  min-width: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: #e0e7ff;
  color: #3538cd;
  font-size: 10px;
  text-align: center;
}

.popup {
  position: absolute;
  left: 0;
  bottom: calc(100% + 6px);
  z-index: 20;
  display: flex;
  width: min(320px, 70vw);
  max-height: 280px;
  flex-direction: column;
  overflow: auto;
  border: 1px solid #eaecf0;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 12px 28px rgb(16 24 40 / 16%);
}

.popup header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid #f2f4f7;
}

.popup header strong {
  overflow: hidden;
  color: #101828;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-actions {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 4px;
}

.popup .download {
  border: 0;
  border-radius: 6px;
  background: #eff8ff;
  color: #175cd3;
  font-size: 11px;
  padding: 2px 8px;
  cursor: pointer;
}

.popup .download:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.popup .close {
  flex-shrink: 0;
  border: 0;
  background: transparent;
  color: #667085;
  font-size: 16px;
  cursor: pointer;
}

.dataset {
  margin: 0;
  padding: 6px 10px 0;
  color: #98a2b3;
  font-size: 11px;
}

.download-error {
  margin: 0;
  padding: 4px 10px 0;
  color: #b42318;
  font-size: 11px;
}

.segment {
  padding: 8px 10px;
  border-top: 1px solid #f2f4f7;
  overflow: auto;
}

.segment:first-of-type {
  border-top: 0;
}

.segment-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
  color: #667085;
  font-size: 11px;
}

.score {
  font-variant-numeric: tabular-nums;
}

.content {
  margin: 0;
  max-height: 120px;
  overflow: auto;
  color: #344054;
  font: 11px/1.45 ui-sans-serif, system-ui, sans-serif;
  white-space: pre-wrap;
  word-break: break-word;
}

.hit-info {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 6px;
  color: #98a2b3;
  font-size: 10px;
}
</style>
