<template>
  <div class="cursor-layer" aria-hidden="true">
    <div
      v-for="cursor in cursors"
      :key="cursor.userId"
      class="remote-cursor"
      :style="cursorStyle(cursor)"
    >
      <svg width="18" height="22" viewBox="0 0 18 22" fill="none">
        <path d="M1 1L16 11L9.5 12.5L6 20L1 1Z" :fill="cursor.color || 'currentColor'" stroke="white" />
      </svg>
      <span :style="{ background: cursor.color || 'currentColor' }">{{ cursor.name || 'User' }}</span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  cursors: { type: Array, default: () => [] },
})

function cursorStyle(cursor) {
  return {
    transform: `translate3d(${cursor.x || 0}px, ${cursor.y || 0}px, 0)`,
    color: cursor.color || '#7f56d9',
  }
}
</script>

<style scoped>
.cursor-layer {
  position: absolute;
  inset: 0;
  z-index: 60;
  overflow: hidden;
  pointer-events: none;
}

.remote-cursor {
  position: absolute;
  top: 0;
  left: 0;
  display: flex;
  align-items: flex-start;
  transition: transform 80ms linear;
}

.remote-cursor span {
  margin: 15px 0 0 -2px;
  padding: 2px 5px;
  border-radius: 4px;
  color: #fff;
  font-size: 9px;
  white-space: nowrap;
}

@media (prefers-reduced-motion: reduce) {
  .remote-cursor {
    transition: none;
  }
}
</style>
