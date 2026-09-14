<template>
  <section class="live-acceptance" :aria-label="copy.liveAcceptanceTitle">
    <strong>{{ copy.liveAcceptanceTitle }}</strong>
    <p>{{ copy.liveAcceptanceNotice }}</p>
    <ul>
      <li v-for="node in request.nodes" :key="node.node_id">
        {{ node.title }} ({{ node.node_type }})
        <span v-if="node.capabilities?.length"> — {{ node.capabilities.join(', ') }}</span>
        <strong v-if="node.may_have_side_effects"> · {{ copy.liveAcceptanceEffects }}</strong>
      </li>
    </ul>
    <p>{{ copy.liveAcceptanceBudget(request) }}</p>
    <div class="live-actions">
      <button type="button" :disabled="disabled" @click="answer(false)">{{ copy.liveAcceptanceSimulate }}</button>
      <button type="button" :disabled="disabled" @click="answer(true)">{{ copy.liveAcceptanceApprove }}</button>
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
.live-acceptance { display: grid; gap: 10px; }
.live-acceptance p { margin: 0; }
.live-acceptance ul { margin: 0; padding-left: 20px; overflow-wrap: anywhere; }
.live-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.live-actions button { padding: 8px 12px; cursor: pointer; }
.live-actions button:disabled { cursor: not-allowed; opacity: .6; }
</style>
