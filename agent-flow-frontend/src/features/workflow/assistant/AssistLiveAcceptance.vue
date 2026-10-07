<template>
  <section class="live-acceptance" :aria-label="copy.liveAcceptanceTitle">
    <header class="live-header">
      <div class="live-heading">
        <strong>{{ copy.liveAcceptanceTitle }}</strong>
        <p>{{ copy.liveAcceptanceNotice }}</p>
      </div>
    </header>
    <details class="live-budget">
      <summary>{{ copy.liveAcceptanceLimitSummary(request) }}</summary>
      <p>{{ copy.liveAcceptanceBudget(request) }}</p>
    </details>
    <div class="live-actions">
      <button type="button" class="live-secondary" :disabled="disabled" @click="answer(false)">{{ copy.liveAcceptanceSimulate }}</button>
      <button type="button" class="live-primary" :disabled="disabled" @click="answer(true)">{{ copy.liveAcceptanceApprove }}</button>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { assistCopy } from './assistLanguage.js'
const props = defineProps({
  request: { type: Object, required: true },
  language: { type: String, default: 'zh-Hans' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['submit'])
const copy = computed(() => assistCopy(props.language))
function answer(approved) {
  emit('submit', [{ question_id: 'live_run_consent', approved, text: approved ? copy.value.liveAcceptanceApprove : copy.value.liveAcceptanceSimulate }])
}
</script>

<style scoped>
.live-acceptance {
  box-sizing: border-box;
  display: grid;
  min-width: 0;
  max-width: 100%;
  gap: 14px;
  overflow: hidden;
  border: 1px solid var(--el-border-color-light, #e4e7ec);
  border-radius: 12px;
  background: var(--el-bg-color, #fff);
  box-shadow: 0 1px 2px rgb(16 24 40 / 5%);
  padding: 16px;
  color: var(--el-text-color-primary, #101828);
}

.live-acceptance p {
  margin: 0;
}

.live-header {
  min-width: 0;
}

.live-heading {
  min-width: 0;
}

.live-heading > strong {
  display: block;
  margin-top: 1px;
  font-size: 15px;
  font-weight: 650;
  line-height: 1.4;
}

.live-heading p {
  margin-top: 4px;
  color: var(--el-text-color-secondary, #667085);
  font-size: 13px;
  line-height: 1.55;
}

.live-budget {
  min-width: 0;
  border-top: 1px solid var(--el-border-color-lighter, #eaecf0);
  padding-top: 10px;
  color: var(--el-text-color-secondary, #667085);
  font-size: 12px;
  line-height: 1.5;
}

.live-budget summary {
  cursor: pointer;
  font-weight: 500;
  user-select: none;
}

.live-budget p {
  margin-top: 7px;
  overflow-wrap: anywhere;
}

.live-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.live-actions button {
  min-width: 0;
  min-height: 40px;
  border-radius: 8px;
  padding: 8px 10px;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.35;
  cursor: pointer;
  transition: border-color .15s ease, background-color .15s ease, box-shadow .15s ease, transform .15s ease;
}

.live-secondary {
  border: 1px solid var(--el-border-color, #d0d5dd);
  background: var(--el-bg-color, #fff);
  color: var(--el-text-color-regular, #344054);
}

.live-secondary:hover:not(:disabled) {
  border-color: #98a2b3;
  background: #f9fafb;
}

.live-primary {
  border: 1px solid var(--el-color-primary, #175cd3);
  background: var(--el-color-primary, #175cd3);
  color: #fff;
  box-shadow: 0 1px 2px rgb(16 24 40 / 8%);
}

.live-primary:hover:not(:disabled) {
  border-color: #1849a9;
  background: #1849a9;
}

.live-actions button:active:not(:disabled) {
  transform: translateY(1px);
}

.live-actions button:focus-visible,
.live-budget summary:focus-visible {
  outline: 2px solid var(--el-color-primary, #175cd3);
  outline-offset: 2px;
}

.live-actions button:disabled {
  cursor: not-allowed;
  opacity: .5;
}

@media (prefers-reduced-motion: reduce) {
  .live-actions button {
    transition: none;
  }
}
</style>
