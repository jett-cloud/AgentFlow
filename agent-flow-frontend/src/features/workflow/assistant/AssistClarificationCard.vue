<template>
  <form class="clarification-card" @submit.prevent="submit">
    <fieldset :disabled="disabled">
      <div
        v-for="question in questions"
        :key="question.id"
        class="question"
      >
        <p class="prompt">{{ question.question }}</p>
        <div v-if="isChoiceQuestion(question)" class="chips" role="group">
          <button
            v-for="option in questionOptions(question)"
            :key="optionValue(option)"
            type="button"
            :class="['chip', { selected: isSelected(question, optionValue(option)) }]"
            :aria-pressed="isSelected(question, optionValue(option))"
            @click="selectOption(question, optionValue(option))"
          >
            {{ optionLabel(option) }}
          </button>
        </div>
        <label class="other">
          <span>{{ copy.other }}</span>
          <input
            v-model="draftFor(question).other"
            type="text"
            :placeholder="copy.otherPlaceholder"
          >
        </label>
      </div>
      <button type="submit" :disabled="!canSubmit">
        {{ copy.send }}
      </button>
    </fieldset>
  </form>
</template>

<script setup>
import { computed, reactive } from 'vue'
import {
  buildClarificationAnswers,
  canSubmitClarification,
  isChoiceQuestion,
  optionLabel,
  optionValue,
  questionOptions,
  shouldSubmitOnChipClick,
  toggleClarificationOption,
} from './assistClarification.js'
import { assistCopy } from './assistLanguage.js'

const props = defineProps({
  questions: { type: Array, default: () => [] },
  language: { type: String, default: 'zh-Hans' },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['submit'])
const copy = computed(() => assistCopy(props.language))
const draft = reactive({})

function draftFor(question) {
  if (!draft[question.id])
    draft[question.id] = { selected: [], other: '' }
  return draft[question.id]
}

const canSubmit = computed(() => canSubmitClarification(props.questions, draft))

function isSelected(question, value) {
  return (draftFor(question).selected || []).includes(value)
}

function selectOption(question, value) {
  const next = toggleClarificationOption(draft, question, value)
  draftFor(question).selected = next[question.id].selected
  if (shouldSubmitOnChipClick(props.questions, question))
    submit()
}

function submit() {
  const answers = buildClarificationAnswers(props.questions, draft)
  if (!answers.length)
    return
  emit('submit', answers)
}
</script>

<style scoped>
.clarification-card fieldset {
  display: grid;
  gap: 12px;
  min-width: 240px;
  margin: 0;
  border: 0;
  padding: 0;
}

.question {
  display: grid;
  gap: 8px;
}

.prompt {
  margin: 0;
  color: #344054;
  font-weight: 600;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  min-height: 32px;
  padding: 4px 12px;
  border: 1px solid #d0d5dd;
  border-radius: 999px;
  background: #fff;
  color: #344054;
  line-height: 1.3;
  cursor: pointer;
}

.chip.selected {
  border-color: #175cd3;
  background: #eff4ff;
  color: #175cd3;
}

.other {
  display: grid;
  gap: 4px;
  color: #667085;
  font-size: 12px;
}

.other input {
  min-height: 32px;
  padding: 4px 8px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
}

button[type='submit'] {
  min-height: 32px;
  justify-self: start;
  padding: 0 12px;
  border: 0;
  border-radius: 8px;
  background: #175cd3;
  color: #fff;
}

button[type='submit']:disabled {
  opacity: 0.5;
}

.chip:focus-visible,
.other input:focus-visible,
button[type='submit']:focus-visible {
  outline: 2px solid #175cd3;
  outline-offset: 2px;
}
</style>
