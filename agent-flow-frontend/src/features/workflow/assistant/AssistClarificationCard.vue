<template>
  <AssistLiveAcceptance
    v-if="liveRequest"
    :request="liveRequest"
    :language="language"
    :disabled="disabled"
    @submit="answers => emit('submit', answers)"
  />
  <form v-else class="clarification-card" @submit.prevent="submit">
    <fieldset :disabled="disabled">
      <fieldset v-for="question in questions" :key="question.id" class="question">
        <legend class="prompt">{{ question.question }}</legend>
        <template v-if="isChoiceQuestion(question)">
          <span class="question-hint">{{ question.kind === 'multi_choice' ? copy.chooseMultiple : copy.chooseOne }}</span>
          <div class="options">
            <label
              v-for="option in questionOptions(question)"
              :key="optionValue(option)"
              :class="['option-row', { selected: isSelected(question, optionValue(option)) }]"
            >
              <input
                :type="question.kind === 'multi_choice' ? 'checkbox' : 'radio'"
                :name="`${formId}-${question.id}`"
                :checked="isSelected(question, optionValue(option))"
                @change="selectOption(question, optionValue(option))"
              >
              <span>{{ optionLabel(option) }}</span>
            </label>
            <label :class="['option-row', { selected: otherSelected(question) }]">
              <input
                :type="question.kind === 'multi_choice' ? 'checkbox' : 'radio'"
                :name="`${formId}-${question.id}`"
                :checked="otherSelected(question)"
                @change="selectOther(question)"
              >
              <span>{{ copy.other }}</span>
            </label>
          </div>
        </template>
        <textarea
          v-if="!isChoiceQuestion(question) || otherSelected(question)"
          v-model="draftFor(question).other"
          class="answer-input"
          :aria-label="isChoiceQuestion(question) ? `${question.question} — ${copy.other}` : question.question"
          :placeholder="copy.answerPlaceholder"
          rows="2"
        />
      </fieldset>
      <div class="submit-row">
        <button type="submit" :disabled="!canSubmit">{{ copy.submitAnswers }}</button>
      </div>
    </fieldset>
  </form>
</template>

<script setup>
import { computed, reactive, useId } from 'vue'
import AssistLiveAcceptance from './AssistLiveAcceptance.vue'
import {
  buildClarificationAnswers,
  canSubmitClarification,
  isChoiceQuestion,
  optionLabel,
  optionValue,
  questionOptions,
  emptyClarificationDraft,
  isClarificationOtherSelected,
  toggleClarificationOther,
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
const liveRequest = computed(() => props.questions.find(question => question?.kind === 'live_acceptance')?.execution_request)
const draft = reactive({})
const formId = useId()

function draftFor(question) {
  if (!draft[question.id])
    draft[question.id] = emptyClarificationDraft(question)
  return draft[question.id]
}

const canSubmit = computed(() => canSubmitClarification(props.questions, draft))

function isSelected(question, value) {
  return (draftFor(question).selected || []).includes(value)
}

function selectOption(question, value) {
  const next = toggleClarificationOption(draft, question, value)
  draft[question.id] = next[question.id]
}

function otherSelected(question) {
  return isClarificationOtherSelected(draftFor(question))
}

function selectOther(question) {
  draft[question.id] = toggleClarificationOther(draft, question)[question.id]
}

function submit() {
  if (props.disabled || !canSubmit.value)
    return
  const answers = buildClarificationAnswers(props.questions, draft)
  if (!answers.length)
    return
  emit('submit', answers)
}
</script>

<style scoped>
.clarification-card { width: 100%; min-width: 0; }
.clarification-card fieldset { min-width: 0; margin: 0; padding: 0; border: 0; }
.question + .question { margin-top: 24px; }
.prompt { padding: 0; margin-bottom: 6px; color: var(--el-text-color-primary, #344054); font-size: 14px; font-weight: 600; line-height: 1.6; overflow-wrap: anywhere; }
.question-hint { display: block; margin-bottom: 10px; color: var(--el-text-color-secondary, #667085); font-size: 12px; }
.options { display: grid; gap: 7px; }
.option-row { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; border: 1px solid var(--el-border-color, #d0d5dd); border-radius: 8px; background: var(--el-bg-color, #fff); color: var(--el-text-color-regular, #475467); font-size: 13px; font-weight: 400; line-height: 1.6; text-align: left; cursor: pointer; }
.option-row span { min-width: 0; overflow-wrap: anywhere; }
.option-row input { flex: 0 0 auto; width: 15px; height: 15px; margin: 3px 0 0; padding: 0; accent-color: var(--el-color-primary, #175cd3); }
.option-row:hover { border-color: var(--el-color-primary-light-5, #a4bcfd); }
.option-row.selected { border-color: var(--el-color-primary, #175cd3); background: var(--el-color-primary-light-9, #eff4ff); color: var(--el-text-color-primary, #344054); }
.answer-input { display: block; box-sizing: border-box; width: 100%; min-height: 72px; margin-top: 10px; padding: 10px 12px; border: 1px solid var(--el-border-color, #d0d5dd); border-radius: 8px; background: var(--el-bg-color, #fff); color: var(--el-text-color-primary, #344054); font: inherit; font-size: 13px; line-height: 1.6; resize: vertical; }
.answer-input::placeholder { color: var(--el-text-color-placeholder, #98a2b3); }
.submit-row { display: flex; justify-content: flex-end; margin-top: 20px; }
button[type='submit'] { min-height: 36px; padding: 8px 16px; border: 0; border-radius: 8px; background: var(--el-color-primary, #175cd3); color: #fff; font-size: 13px; font-weight: 500; cursor: pointer; }
button[type='submit']:disabled { opacity: .45; cursor: not-allowed; }
fieldset:disabled .option-row { opacity: .6; cursor: not-allowed; }
.option-row:has(input:focus-visible), .answer-input:focus-visible, button[type='submit']:focus-visible { outline: 2px solid var(--el-color-primary, #175cd3); outline-offset: 2px; }
</style>
