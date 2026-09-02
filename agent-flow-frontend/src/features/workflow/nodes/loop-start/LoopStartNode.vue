<template>
  <div class="loop-start-node nodrag" title="循环起点 (Loop Start)">
    <div class="start-icon-circle">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="12" height="12" fill="currentColor">
        <path d="M19 21H5a1 1 0 0 1-1-1v-9H1l10.327-9.388a1 1 0 0 1 1.346 0L23 11h-3v9a1 1 0 0 1-1 1zm-6-2h4v-7h-4v7z" />
      </svg>
    </div>

    <NodeHandle :node-id="id" :data="data" type="source" position="right" handle-id="source" centered />
  </div>
</template>

<script setup>
import NodeHandle from '../base/NodeHandle.vue'

defineProps({
  id: { type: String, required: true },
  data: { type: Object, default: () => ({}) },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})
</script>

<style scoped>
.loop-start-node {
  position: relative;
  width: 44px;
  height: 44px;
  border: 1px solid #eaecf0;
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  user-select: none;
  z-index: 10;
}

.start-icon-circle {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #155eef;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.2);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
