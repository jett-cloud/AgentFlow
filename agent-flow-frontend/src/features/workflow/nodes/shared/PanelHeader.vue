<!-- panel/base/PanelHeader.vue -->
<template>
  <div class="panel-header">
    <div class="header-left">
      <BlockIcon :type="blockType" :size="22" />
      <div class="header-fields">
        <input
          :value="title"
          class="title-input"
          :placeholder="placeholder"
          :disabled="readOnly"
          @input="$emit('update:title', $event.target.value)"
        />
        <textarea
          :value="description || legacyDescription"
          class="description-input"
          placeholder="添加节点描述…"
          rows="1"
          :disabled="readOnly"
          @change="$emit('update:description', $event.target.value)"
        />
      </div>
    </div>
    <div class="header-actions">
      <button
        v-if="canRun"
        type="button"
        class="run-btn"
        :class="{ running }"
        :disabled="readOnly"
        :aria-label="running ? '停止运行' : '运行此节点'"
        @click="$emit(running ? 'stop' : 'run')"
      >
        <el-icon><VideoPause v-if="running" /><CaretRight v-else /></el-icon>
        <span>{{ running ? '停止' : '运行' }}</span>
      </button>
      <button type="button" class="close-btn" aria-label="关闭面板" @click="$emit('close')">
        <el-icon><Close /></el-icon>
      </button>
    </div>
  </div>
</template>

<script setup>
import { CaretRight, Close, VideoPause } from '@element-plus/icons-vue'
import BlockIcon from '../base/BlockIcon.vue'

defineProps({
  blockType: { type: String, required: true },
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  legacyDescription: { type: String, default: '' },
  placeholder: { type: String, default: '节点名称' },
  readOnly: { type: Boolean, default: false },
  canRun: { type: Boolean, default: false },
  running: { type: Boolean, default: false },
})
defineEmits(['update:title', 'update:description', 'run', 'stop', 'close'])
</script>

<style scoped>
.panel-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 56px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
  background-color: var(--components-panel-bg, #fff);
}
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.header-fields { display: flex; flex: 1; min-width: 0; flex-direction: column; gap: 2px; }
.header-actions { display: flex; flex-shrink: 0; align-items: center; gap: 6px; }
.title-input {
  font-size: 14px;
  font-weight: 600;
  color: #101828;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 4px 6px;
  background: transparent;
  outline: none;
  width: 100%;
}
.description-input {
  width: 100%;
  resize: vertical;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 3px 6px;
  background: transparent;
  color: #667085;
  font: inherit;
  font-size: 12px;
  line-height: 1.4;
  outline: none;
}
.description-input:hover:not(:disabled), .description-input:focus:not(:disabled) {
  border-color: #d0d5dd;
  background: var(--components-panel-bg, #fff);
}
.title-input:hover:not(:disabled),
.title-input:focus:not(:disabled) {
  border-color: #d0d5dd;
  background: var(--components-panel-bg, #fff);
}
.close-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #667085;
  padding: 4px;
  border-radius: 6px;
  flex-shrink: 0;
}
.run-btn {
  display: inline-flex;
  min-height: 32px;
  align-items: center;
  gap: 4px;
  padding: 0 10px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #fff;
  color: #344054;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.run-btn:hover:not(:disabled) { border-color: #84adff; color: #155eef; }
.run-btn.running { border-color: #fda29b; color: #d92d20; }
.run-btn:disabled { cursor: not-allowed; opacity: 0.45; }
.run-btn:focus-visible,
.close-btn:focus-visible { outline: 2px solid var(--state-accent-border, #155eef); outline-offset: 2px; }
.close-btn:hover {
  background: var(--components-actionbar-item-bg-hover, #f2f4f7);
  color: #101828;
}
</style>
