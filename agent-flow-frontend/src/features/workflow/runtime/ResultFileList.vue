<template>
  <div v-if="groups.length" class="result-file-list" aria-label="结果文件">
    <h3>Files ({{ totalCount }})</h3>
    <section
      v-for="group in groups"
      :key="group.varName"
      class="file-group"
    >
      <div class="var-name">{{ group.varName }}</div>
      <ul class="file-rows">
        <li
          v-for="(file, index) in group.list"
          :key="file.id || `${group.varName}-${index}`"
          class="file-row"
        >
          <button
            v-if="isImageResultFile(file) && file.url"
            type="button"
            class="thumb"
            :title="file.name"
            @click="previewImage(file)"
          >
            <img :src="file.url" :alt="file.name" />
          </button>
          <div v-else class="icon" aria-hidden="true">📄</div>
          <div class="meta">
            <strong>{{ file.name }}</strong>
            <span>{{ typeLabel(file) }}</span>
          </div>
          <div class="actions">
            <button
              v-if="isImageResultFile(file) && file.url"
              type="button"
              @click="previewImage(file)"
            >
              预览
            </button>
            <button
              type="button"
              :disabled="!file.url"
              @click="downloadFile(file)"
            >
              下载
            </button>
          </div>
        </li>
      </ul>
    </section>

    <div
      v-if="previewUrl"
      class="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label="图片预览"
      @click.self="previewUrl = ''"
    >
      <img :src="previewUrl" alt="" />
      <button type="button" class="close" aria-label="关闭预览" @click="previewUrl = ''">×</button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { downloadUrl } from './downloadUrl.js'
import { countResultFiles, isImageResultFile } from './resultFiles.js'

const props = defineProps({
  groups: { type: Array, default: () => [] },
})

const previewUrl = ref('')
const totalCount = computed(() => countResultFiles(props.groups))

function typeLabel(file) {
  return file.type || file.supportFileType || 'file'
}

function downloadFile(file) {
  downloadUrl({ url: file.url, fileName: file.name })
}

function previewImage(file) {
  if (!file?.url)
    return
  previewUrl.value = file.url
}
</script>

<style scoped>
.result-file-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

h3 {
  margin: 0;
  color: #667085;
  font-size: 11px;
  text-transform: uppercase;
}

.file-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.var-name {
  color: #667085;
  font-size: 11px;
}

.file-rows {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border: 1px solid #eaecf0;
  border-radius: 8px;
  background: #fff;
}

.thumb {
  width: 40px;
  height: 40px;
  padding: 0;
  overflow: hidden;
  border: 0;
  border-radius: 6px;
  background: #f2f4f7;
  cursor: pointer;
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.icon {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  border-radius: 6px;
  background: #f2f4f7;
  font-size: 16px;
}

.meta {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.meta strong {
  overflow: hidden;
  color: #101828;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta span {
  color: #98a2b3;
  font-size: 10px;
}

.actions {
  display: flex;
  gap: 4px;
}

.actions button {
  padding: 4px 8px;
  border: 1px solid #eaecf0;
  border-radius: 6px;
  background: #fff;
  color: #344054;
  font-size: 11px;
  cursor: pointer;
}

.actions button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.lightbox {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  background: rgb(16 24 40 / 72%);
  padding: 24px;
}

.lightbox img {
  max-width: min(920px, 100%);
  max-height: min(80vh, 100%);
  border-radius: 8px;
  background: #fff;
}

.lightbox .close {
  position: absolute;
  top: 16px;
  right: 16px;
  padding: 4px 10px;
  border: 0;
  border-radius: 8px;
  background: #fff;
  color: #101828;
  font-size: 20px;
  cursor: pointer;
}
</style>
