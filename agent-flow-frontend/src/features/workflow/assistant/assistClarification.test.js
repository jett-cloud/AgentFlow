import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildClarificationAnswers,
  canSubmitClarification,
  clarificationAnswerText,
  shouldSubmitOnChipClick,
  toggleClarificationOption,
  toggleClarificationOther,
} from './assistClarification.js'

const knowledge = {
  id: 'knowledge',
  kind: 'single_choice',
  question: 'Which knowledge base?',
  options: [
    { value: 'docs', label: 'Product docs' },
    { value: 'wiki', label: 'Team wiki' },
  ],
}

const extras = {
  id: 'extras',
  kind: 'multi_choice',
  question: 'What else?',
  options: [
    { value: 'rag', label: 'RAG' },
    { value: 'eval', label: 'Eval' },
  ],
}

const note = {
  id: 'note',
  kind: 'text',
  question: 'Anything else?',
}

test('clarification answers serialize labels and supported scalar values', () => {
  const text = clarificationAnswerText([
    { question_id: 'knowledge', kind: 'resource_select', labels: [' Product docs ', 'Team wiki'] },
    { question_id: 'format', kind: 'text', text: ' markdown ' },
    { question_id: 'other', other_text: ' custom ' },
    { question_id: 'value', value: ' draft ' },
    { question_id: 'selected', selected_value: ' workflow ' },
    { question_id: 'empty', kind: 'text', text: '   ' },
  ])

  assert.equal(text, 'Product docs、Team wiki\nmarkdown\ncustom\ndraft\nworkflow')
})

test('chip answers cover every question including optional other text', () => {
  const answers = buildClarificationAnswers([knowledge, extras, note], {
    knowledge: { selected: ['docs'], other: '' },
    extras: { selected: ['rag', 'eval'], other: '' },
    note: { selected: [], other: 'keep citations' },
  })

  assert.deepEqual(answers.map(answer => answer.text), [
    'Product docs',
    'RAG、Eval',
    'keep citations',
  ])
  assert.equal(clarificationAnswerText(answers), 'Product docs\nRAG、Eval\nkeep citations')
})

test('choice selection waits for explicit submission', () => {
  assert.equal(shouldSubmitOnChipClick([knowledge], knowledge), false)
  assert.equal(shouldSubmitOnChipClick([knowledge, extras], knowledge), false)
  assert.equal(shouldSubmitOnChipClick([extras], extras), false)

  const draft = toggleClarificationOption({}, knowledge, 'wiki')
  assert.equal(canSubmitClarification([knowledge], draft), true)
  assert.equal(buildClarificationAnswers([knowledge], draft)[0].text, 'Team wiki')
})

test('single choice switches exclusively between options and other', () => {
  let draft = toggleClarificationOption({}, knowledge, 'docs')
  draft = toggleClarificationOther(draft, knowledge)
  assert.deepEqual(draft.knowledge.selected, [])
  assert.equal(canSubmitClarification([knowledge], draft), false)
  draft.knowledge.other = 'Custom source'
  assert.equal(buildClarificationAnswers([knowledge], draft)[0].text, 'Custom source')
  draft = toggleClarificationOption(draft, knowledge, 'wiki')
  assert.equal(draft.knowledge.otherSelected, false)
  assert.equal(buildClarificationAnswers([knowledge], draft)[0].text, 'Team wiki')
})

test('serialization never submits conflicting single-choice values', () => {
  const answers = buildClarificationAnswers([knowledge], {
    knowledge: { selected: ['docs', 'wiki'], other: 'custom', otherSelected: true },
  })
  assert.deepEqual(answers[0].labels, [])
  assert.equal(answers[0].text, 'custom')
})

test('multiple choice permits other and retains it in submitted message text', () => {
  let draft = toggleClarificationOption({}, extras, 'rag')
  draft = toggleClarificationOther(draft, extras)
  draft.extras.other = 'Custom metric'
  assert.equal(clarificationAnswerText(buildClarificationAnswers([extras], draft)), 'RAG、Custom metric')
  draft = toggleClarificationOther(draft, extras)
  assert.equal(buildClarificationAnswers([extras], draft)[0].text, 'RAG')
})

test('other text is enough to submit a choice question', () => {
  assert.equal(canSubmitClarification([knowledge], { knowledge: { selected: [], other: 'custom kb' } }), true)
  assert.equal(
    buildClarificationAnswers([knowledge], { knowledge: { selected: [], other: 'custom kb' } })[0].other_text,
    'custom kb',
  )
})
