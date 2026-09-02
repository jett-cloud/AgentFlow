<template>
  <el-dialog
    :model-value="modelValue"
    title="裁剪应用图标"
    width="480px"
    append-to-body
    destroy-on-close
    :close-on-click-modal="false"
    @close="cancel"
  >
    <div class="crop-dialog-body">
      <p class="crop-hint">拖动图片选择展示范围，使用滑杆调整缩放。</p>
      <div
        class="crop-frame"
        :class="{ dragging: dragState }"
        @pointerdown="startDrag"
        @pointermove="moveDrag"
        @pointerup="endDrag"
        @pointercancel="endDrag"
      >
        <img
          v-if="sourceUrl && !loadError"
          :src="sourceUrl"
          alt="待裁剪图片"
          draggable="false"
          :style="imageStyle"
        />
        <span v-if="loading" class="crop-status">正在读取图片…</span>
        <span v-else-if="loadError" class="crop-status error">{{ loadError }}</span>
        <span class="crop-grid" aria-hidden="true" />
      </div>

      <label class="zoom-control">
        <span>缩放</span>
        <input v-model.number="zoom" type="range" min="1" max="3" step="0.01" :disabled="!image" />
        <strong>{{ Math.round(zoom * 100) }}%</strong>
      </label>
    </div>

    <template #footer>
      <el-button :disabled="confirming" @click="cancel">取消</el-button>
      <el-button type="primary" :loading="confirming" :disabled="!image || !!loadError" @click="confirmCrop">
        使用此范围
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  calculateSquareCrop,
  clampCropOffset,
  createAppIconSource,
  cropImageToPng,
} from '../model/svgAppIcon.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  file: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'cancel', 'confirm'])
const FRAME_SIZE = 320

const sourceUrl = ref('')
const image = ref(null)
const imageWidth = ref(0)
const imageHeight = ref(0)
const zoom = ref(1)
const offsetX = ref(0)
const offsetY = ref(0)
const loading = ref(false)
const loadError = ref('')
const confirming = ref(false)
const dragState = ref(null)

const display = computed(() => {
  if (!imageWidth.value || !imageHeight.value)
    return { x: 0, y: 0, displayWidth: 0, displayHeight: 0 }
  return clampCropOffset({
    width: imageWidth.value,
    height: imageHeight.value,
    frameSize: FRAME_SIZE,
    zoom: zoom.value,
    offsetX: offsetX.value,
    offsetY: offsetY.value,
  })
})

const imageStyle = computed(() => ({
  width: `${display.value.displayWidth}px`,
  height: `${display.value.displayHeight}px`,
  left: `calc(50% + ${display.value.x}px)`,
  top: `calc(50% + ${display.value.y}px)`,
}))

watch(() => [props.modelValue, props.file], async ([open, file]) => {
  if (!open || !file) {
    cleanupSource()
    return
  }
  await loadFile(file)
}, { immediate: true })

watch(zoom, () => {
  offsetX.value = display.value.x
  offsetY.value = display.value.y
})

async function loadFile(file) {
  cleanupSource()
  loading.value = true
  loadError.value = ''
  zoom.value = 1
  offsetX.value = 0
  offsetY.value = 0
  try {
    sourceUrl.value = await createAppIconSource(file)
    const loaded = await loadImage(sourceUrl.value)
    image.value = loaded
    imageWidth.value = loaded.naturalWidth
    imageHeight.value = loaded.naturalHeight
  }
  catch (error) {
    loadError.value = error.message || '无法读取图片'
  }
  finally {
    loading.value = false
  }
}

function startDrag(event) {
  if (!image.value)
    return
  event.currentTarget.setPointerCapture(event.pointerId)
  dragState.value = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    offsetX: display.value.x,
    offsetY: display.value.y,
  }
}

function moveDrag(event) {
  if (!dragState.value || dragState.value.pointerId !== event.pointerId)
    return
  offsetX.value = dragState.value.offsetX + event.clientX - dragState.value.startX
  offsetY.value = dragState.value.offsetY + event.clientY - dragState.value.startY
  offsetX.value = display.value.x
  offsetY.value = display.value.y
}

function endDrag(event) {
  if (dragState.value?.pointerId === event.pointerId)
    dragState.value = null
}

async function confirmCrop() {
  if (!image.value || !props.file)
    return
  confirming.value = true
  try {
    const crop = calculateSquareCrop({
      width: imageWidth.value,
      height: imageHeight.value,
      frameSize: FRAME_SIZE,
      zoom: zoom.value,
      offsetX: display.value.x,
      offsetY: display.value.y,
    })
    const pngFile = await cropImageToPng(image.value, crop, props.file.name)
    emit('confirm', pngFile)
  }
  catch (error) {
    loadError.value = error.message || '图片裁剪失败'
  }
  finally {
    confirming.value = false
  }
}

function cancel() {
  emit('cancel')
  emit('update:modelValue', false)
}

function cleanupSource() {
  if (sourceUrl.value)
    URL.revokeObjectURL(sourceUrl.value)
  sourceUrl.value = ''
  image.value = null
  imageWidth.value = 0
  imageHeight.value = 0
  dragState.value = null
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const candidate = new Image()
    candidate.onload = () => resolve(candidate)
    candidate.onerror = () => reject(new Error('无法读取这张图片'))
    candidate.src = url
  })
}

onBeforeUnmount(cleanupSource)
</script>

<style scoped>
.crop-dialog-body { display: flex; flex-direction: column; align-items: center; gap: 16px; }
.crop-hint { width: 100%; margin: 0; color: var(--af-text-muted); font-size: 13px; }
.crop-frame {
  position: relative;
  width: 320px;
  height: 320px;
  max-width: 100%;
  overflow: hidden;
  border: 1px solid var(--af-border-strong);
  border-radius: var(--af-radius-lg);
  background: #e2e8f0;
  cursor: grab;
  touch-action: none;
  user-select: none;
}
.crop-frame.dragging { cursor: grabbing; }
.crop-frame img { position: absolute; max-width: none; transform: translate(-50%, -50%); pointer-events: none; }
.crop-grid { position: absolute; inset: 0; pointer-events: none; background: linear-gradient(to right, transparent 33.2%, rgb(255 255 255 / 55%) 33.3%, rgb(255 255 255 / 55%) 33.7%, transparent 33.8%, transparent 66.2%, rgb(255 255 255 / 55%) 66.3%, rgb(255 255 255 / 55%) 66.7%, transparent 66.8%), linear-gradient(to bottom, transparent 33.2%, rgb(255 255 255 / 55%) 33.3%, rgb(255 255 255 / 55%) 33.7%, transparent 33.8%, transparent 66.2%, rgb(255 255 255 / 55%) 66.3%, rgb(255 255 255 / 55%) 66.7%, transparent 66.8%); box-shadow: inset 0 0 0 1px rgb(15 23 42 / 12%); }
.crop-status { position: absolute; inset: 0; display: grid; place-items: center; color: var(--af-text-muted); font-size: 13px; }
.crop-status.error { padding: 24px; color: #b42318; text-align: center; }
.zoom-control { display: grid; width: 100%; grid-template-columns: auto 1fr 44px; align-items: center; gap: 12px; color: var(--af-text-secondary); font-size: 13px; }
.zoom-control input { width: 100%; accent-color: var(--af-brand); }
.zoom-control strong { color: var(--af-text-muted); font-size: 12px; text-align: right; }
@media (max-width: 520px) { .crop-frame { width: min(320px, calc(100vw - 72px)); height: min(320px, calc(100vw - 72px)); } }
</style>
