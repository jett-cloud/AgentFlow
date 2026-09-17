<template>
  <div v-if="files.length" class="chat-message-files" aria-label="消息附件">
    <div
      v-for="(file, index) in files"
      :key="file.id || `${index}-${file.name}`"
      class="file-chip"
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
      <template v-else>
        <span class="file-name" :title="file.name">{{ file.name || 'file' }}</span>
        <button
          type="button"
          class="download"
          :disabled="!file.url"
          @click="downloadFile(file)"
        >
          下载
        </button>
      </template>
    </div>

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
import { ref } from 'vue'
import { downloadUrl } from './downloadUrl.js'
import { isImageResultFile } from './resultFiles.js'

defineProps({
  files: { type: Array, default: () => [] },
})

const previewUrl = ref('')

function downloadFile(file) {
  if (!file?.url)
    return
  downloadUrl({ url: file.url, fileName: file.name })
}

function previewImage(file) {
  if (!file?.url)
    return
  previewUrl.value = file.url
}
</script>

<style scoped>
.chat-message-files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.file-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
}

.thumb {
  padding: 0;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  cursor: pointer;
}

.thumb img {
  display: block;
  width: 72px;
  height: 72px;
  object-fit: cover;
}

.file-name {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: inherit;
  font-size: 11px;
}

.download {
  padding: 2px 6px;
  border: 0;
  border-radius: 4px;
  background: rgb(16 24 40 / 8%);
  color: inherit;
  font-size: 11px;
  cursor: pointer;
}

.download:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.lightbox {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgb(16 24 40 / 72%);
}

.lightbox img {
  max-width: min(900px, 100%);
  max-height: 90vh;
  border-radius: 8px;
  background: #fff;
}

.lightbox .close {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 999px;
  background: #fff;
  color: #101828;
  font-size: 20px;
  cursor: pointer;
}
</style>
