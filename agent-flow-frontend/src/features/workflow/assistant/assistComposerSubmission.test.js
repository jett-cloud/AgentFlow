import test from 'node:test'
import assert from 'node:assert/strict'

import { createAssistComposerSubmission } from './assistComposerSubmission.js'

test('composer retains the draft until the parent acknowledges an accepted Turn', () => {
  let draft = ' build a workflow '
  let receipt
  const composer = createAssistComposerSubmission({
    readText: () => draft,
    clearText: () => { draft = '' },
    emitSend(message, nextReceipt) {
      assert.equal(message, 'build a workflow')
      receipt = nextReceipt
    },
  })

  assert.equal(composer.submit(), true)
  assert.equal(draft, ' build a workflow ')
  receipt.accepted()
  assert.equal(draft, '')
})

test('late acceptance never clears edits typed during Turn preflight', () => {
  let draft = 'first'
  let receipt
  const composer = createAssistComposerSubmission({
    readText: () => draft,
    clearText: () => { draft = '' },
    emitSend(_message, nextReceipt) { receipt = nextReceipt },
  })

  composer.submit()
  draft = 'second'
  assert.equal(receipt.accepted(), false)
  assert.equal(draft, 'second')
})

test('composer send includes serialized mention references without replacing the text', () => {
  let draft = '把 知识库检索 接到 LLM'
  let sent
  const composer = createAssistComposerSubmission({
    readText: () => draft,
    readReferences: () => [{ kind: 'node', id: 'n1', label: '知识库检索' }],
    clearText: () => { draft = '' },
    emitSend(message, receipt, references) {
      sent = { message, references }
      receipt.accepted()
    },
  })

  assert.equal(composer.submit(), true)
  assert.deepEqual(sent, {
    message: '把 知识库检索 接到 LLM',
    references: [{ kind: 'node', id: 'n1', label: '知识库检索' }],
  })
  assert.equal(draft, '')
})
