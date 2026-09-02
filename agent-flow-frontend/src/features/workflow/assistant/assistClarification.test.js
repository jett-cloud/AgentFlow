import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildClarificationAnswers,
  canSubmitClarification,
  clarificationAnswerText,
  shouldSubmitOnChipClick,
  toggleClarificationOption,
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

test('a lone single-choice question submits when a chip is clicked', () => {
  assert.equal(shouldSubmitOnChipClick([knowledge], knowledge), true)
  assert.equal(shouldSubmitOnChipClick([knowledge, extras], knowledge), false)
  assert.equal(shouldSubmitOnChipClick([extras], extras), false)

  const draft = toggleClarificationOption({}, knowledge, 'wiki')
  assert.equal(canSubmitClarification([knowledge], draft), true)
  assert.equal(buildClarificationAnswers([knowledge], draft)[0].text, 'Team wiki')
})

test('other text is enough to submit a choice question', () => {
  assert.equal(canSubmitClarification([knowledge], { knowledge: { selected: [], other: 'custom kb' } }), true)
  assert.equal(
    buildClarificationAnswers([knowledge], { knowledge: { selected: [], other: 'custom kb' } })[0].other_text,
    'custom kb',
  )
})
