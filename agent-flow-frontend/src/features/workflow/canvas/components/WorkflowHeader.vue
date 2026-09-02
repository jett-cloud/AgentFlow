<template>
  <header class="workflow-header" aria-label="工作流状态与操作">
    <div class="status-group">
      <button type="button" class="back-button" aria-label="返回主页" title="返回主页" @click="$emit('back')">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m12.5 4.5-5.5 5.5 5.5 5.5M7 10h9" /></svg>
      </button>
      <p class="save-status" :data-status="draftStatus" role="status" aria-live="polite">
        {{ saveStatusLabel }}
      </p>
    </div>

    <nav class="header-actions" aria-label="工作流操作">
      <div class="action-group run-group">
        <button
          type="button"
          class="run-action"
          :class="{ active: isRunning }"
          :aria-label="isRunning && canStop ? '停止测试运行' : '测试运行'"
          :disabled="readOnly || (isRunning && !canStop)"
          @click="$emit(isRunning && canStop ? 'stop' : 'run')"
        >
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path v-if="!isRunning" d="m6.5 4 8 6-8 6V4Z" />
            <path v-else d="M6 6h8v8H6z" />
          </svg>
          <span>{{ isRunning ? '停止运行' : '测试运行' }}</span>
          <kbd v-if="!isRunning">Alt R</kbd>
        </button>
        <button
          type="button"
          class="icon-button"
          :class="{ active: runHistoryOpen }"
          aria-label="运行历史"
          title="运行历史"
          @click="$emit('run-history')"
        >
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M3.5 10a6.5 6.5 0 1 0 2-4.7M3.5 3.5v4h4M10 6.5V10l2.5 1.5" />
          </svg>
        </button>
        <button
          type="button"
          class="icon-button checklist-button"
          :class="{ active: checklistOpen }"
          aria-label="检查清单"
          title="检查清单"
          @click="$emit('checklist')"
        >
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="m4 5 1.3 1.3L7.8 4M10 5h6M4 10l1.3 1.3L7.8 9M10 10h6M4 15l1.3 1.3L7.8 14M10 15h6" />
          </svg>
          <span v-if="checklistCount > 0" class="checklist-badge">{{ checklistCount > 99 ? '99+' : checklistCount }}</span>
        </button>
      </div>

      <div class="action-group variable-group">
        <button
          type="button"
          class="env-action"
          :class="{ active: variablesOpen && variablesTab === 'env' }"
          aria-label="环境变量"
          @click="$emit('variables', 'env')"
        >
          ENV
        </button>
        <button
          type="button"
          class="icon-button"
          :class="{ active: variablesOpen && variablesTab === 'sys' }"
          aria-label="全局变量"
          title="全局变量"
          @click="$emit('variables', 'sys')"
        >
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M7.2 4.5H5.8A1.8 1.8 0 0 0 4 6.3v7.4a1.8 1.8 0 0 0 1.8 1.8h1.4M12.8 4.5h1.4A1.8 1.8 0 0 1 16 6.3v7.4a1.8 1.8 0 0 1-1.8 1.8h-1.4M8.5 7.2l3 5.6M11.5 7.2l-3 5.6" />
          </svg>
        </button>
      </div>

    </nav>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { formatCanvasSaveStatus } from '../../model/canvasChrome.js'

const props = defineProps({
  draftStatus: { type: String, default: 'saved' },
  draftUpdatedAt: { type: Number, default: 0 },
  publishStatus: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
  isRunning: { type: Boolean, default: false },
  canStop: { type: Boolean, default: false },
  checklistOpen: { type: Boolean, default: false },
  checklistCount: { type: Number, default: 0 },
  runHistoryOpen: { type: Boolean, default: false },
  variablesOpen: { type: Boolean, default: false },
  variablesTab: { type: String, default: 'sys' },
})

defineEmits(['back', 'checklist', 'run-history', 'variables', 'run', 'stop'])

const saveStatusLabel = computed(() => formatCanvasSaveStatus(props))
</script>

<style scoped>
.workflow-header {
  position: absolute;
  inset: 0 0 auto;
  z-index: 60;
  pointer-events: none;
}

.status-group {
  position: absolute;
  top: 14px;
  left: 14px;
  display: flex;
  min-height: 40px;
  align-items: center;
  gap: 8px;
  pointer-events: auto;
}

.save-status {
  margin: 0;
  color: var(--text-secondary, #667085);
  font-size: 12px;
  line-height: 20px;
}

.back-button {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  padding: 0;
  border: 1px solid var(--components-actionbar-border, rgb(16 24 40 / 6%));
  border-radius: 12px;
  background: var(--components-actionbar-bg, rgb(255 255 255 / 95%));
  box-shadow: 0 2px 8px rgb(16 24 40 / 8%);
}

.save-status[data-status='dirty'],
.save-status[data-status='error'] {
  color: var(--text-warning, #b54708);
}

.save-status[data-status='saving'] {
  color: var(--text-accent, #155eef);
}

.header-actions {
  position: absolute;
  top: 14px;
  right: clamp(14px, var(--canvas-panel-offset, 14px), calc(100% - 420px));
  display: flex;
  align-items: center;
  gap: 10px;
  pointer-events: auto;
  transition: right 180ms ease;
}

.action-group {
  display: flex;
  min-height: 40px;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--components-panel-border, rgb(16 24 40 / 6%));
  border-radius: 12px;
  background: var(--components-actionbar-bg, rgb(255 255 255 / 95%));
  box-shadow: 0 2px 8px rgb(16 24 40 / 8%);
  backdrop-filter: blur(8px);
}

button {
  min-width: 40px;
  height: 34px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary, #475467);
  cursor: pointer;
}

button:hover:not(:disabled) {
  background: var(--components-actionbar-item-bg-hover, #f2f4f7);
}

button:focus-visible {
  outline: 2px solid var(--border-accent, #528bff);
  outline-offset: 2px;
}

button.active {
  background: var(--components-actionbar-item-bg-active, #eff4ff);
  color: var(--text-accent, #155eef);
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

svg {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.7;
}

.run-action {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 9px;
  color: var(--text-accent, #155eef);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}

.run-action svg {
  fill: currentColor;
  stroke: currentColor;
}

kbd {
  border: 0;
  border-radius: 4px;
  background: var(--components-actionbar-item-bg-hover, #f2f4f7);
  color: var(--text-secondary, #667085);
  font-family: inherit;
  font-size: 11px;
  font-weight: 500;
  line-height: 18px;
}

.icon-button {
  display: grid;
  place-items: center;
  padding: 0;
}

.checklist-button {
  position: relative;
}

.checklist-badge {
  position: absolute;
  top: -7px;
  right: -5px;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  border: 2px solid var(--components-actionbar-bg, #fff);
  border-radius: 999px;
  background: #f79009;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  line-height: 14px;
}

.variable-group {
  padding-inline: 4px;
}

.env-action {
  padding: 0 8px;
  font-size: 11px;
  font-weight: 700;
}

@media (max-width: 1100px) {
  .header-actions {
    top: 48px;
  }
}
</style>
