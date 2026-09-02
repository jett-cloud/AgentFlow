import test from 'node:test'
import assert from 'node:assert/strict'

import * as assistLanguage from './assistLanguage.js'

test('recovered copy follows the latest authoritative user message', () => {
  assert.equal(typeof assistLanguage.detectRecoveredAssistLanguage, 'function')

  const messages = [
    { role: 'user', text: '请添加一个节点' },
    { role: 'assistant', text: 'Working' },
    { role: 'user', text: 'Add a final answer node' },
    { role: 'assistant', text: 'Done' },
  ]

  assert.equal(assistLanguage.detectRecoveredAssistLanguage(messages), 'en')
  assert.equal(assistLanguage.detectRecoveredAssistLanguage([]), 'zh-Hans')
})

test('English completion copy is available to mounted message and live-status paths', () => {
  const copy = assistLanguage.assistCopy('en')

  assert.equal(copy.statusCompleted, 'Operations completed')
  assert.equal(copy.statusRunDone, 'Run completed.')
  assert.equal(copy.retryThisStep, 'Retry this step')
  assert.equal(assistLanguage.assistCopy('zh-Hans').retryThisStep, '重试此步')
})

test('tool activity labels prefer arguments over a generic ok summary', () => {
  assert.equal(
    assistLanguage.formatAssistToolActivity(
      {
        name: 'build_node',
        arguments: { title: '生成答案', type: 'llm' },
        summary: 'ok',
        ok: true,
      },
      null,
      'zh-Hans',
    ),
    '写入节点「生成答案」',
  )
  assert.equal(
    assistLanguage.formatAssistToolActivity(
      {
        name: 'connect',
        summary: 'ok',
        ok: true,
      },
      { action: 'connect', arguments: { source: 'start', target: 'end' } },
      'en',
    ),
    'Connect start → end',
  )
})

test('completion markdown keeps summary, diff, and validation as formatted copy', () => {
  assert.equal(
    assistLanguage.formatAssistCompletionMarkdown(
      {
        summary: '已搭好 RAG 测试工作流',
        diff: { added: ['n1'], removed: [], updated: ['n2'] },
        validation: { ok: true },
      },
      'zh-Hans',
    ),
    '已搭好 RAG 测试工作流\n\n**变更:** +1 ~1 −0\n\n**校验通过**',
  )
})
