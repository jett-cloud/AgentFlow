import test from 'node:test'
import assert from 'node:assert/strict'

import * as assistLanguage from './assistLanguage.js'

test('workflow node names do not switch a Chinese instruction to English', () => {
  assert.equal(assistLanguage.detectAssistLanguage('生成 Start → LLM → End'), 'zh-Hans')
  assert.equal(assistLanguage.detectRecoveredAssistLanguage([
    { role: 'user', text: '生成 Start → LLM → End' },
  ]), 'zh-Hans')
})

test('recovered copy follows explicit language changes', () => {
  assert.equal(typeof assistLanguage.detectRecoveredAssistLanguage, 'function')

  const messages = [
    { role: 'user', text: '请添加一个节点' },
    { role: 'assistant', text: 'Working' },
    { role: 'user', text: 'Please respond in English' },
    { role: 'assistant', text: 'Done' },
  ]

  assert.equal(assistLanguage.detectRecoveredAssistLanguage(messages), 'en')
  assert.equal(assistLanguage.detectRecoveredAssistLanguage([]), 'zh-Hans')
})

test('model clarification and subsequent instructions inherit the conversation language', () => {
  const messages = [
    { role: 'user', text: '请生成抠图工作流' },
    { role: 'assistant', text: 'Which model?' },
    { role: 'user', text: 'deepseek-v4-pro 深度求索\ndoubao-seedream-3-0-t2i-250415' },
    { role: 'user', text: 'continue' },
  ]
  assert.equal(assistLanguage.detectRecoveredAssistLanguage(messages), 'zh-Hans')
  assert.equal(assistLanguage.detectRecoveredAssistLanguage([
    ...messages, { role: 'user', text: '请改用英文回答' },
  ]), 'en')
  assert.equal(assistLanguage.detectRecoveredAssistLanguage([
    { role: 'user', text: 'Build a workflow' }, { role: 'user', text: '请用中文回答' },
  ]), 'zh-Hans')
  assert.equal(assistLanguage.detectRecoveredAssistLanguage([
    ...messages, { role: 'user', text: '不要用英文回答' },
  ]), 'zh-Hans')
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

test('successful tool activities do not append model-generated summaries', () => {
  assert.equal(
    assistLanguage.formatAssistToolActivity(
      {
        name: 'finish',
        summary: '一段非常长而且只应该出现在最终结果卡片里的总结',
        ok: true,
      },
      null,
      'zh-Hans',
    ),
    '完成校验',
  )
})

test('unknown tool activities do not expose internal method names', () => {
  assert.equal(
    assistLanguage.formatAssistToolActivity(
      { name: 'new_internal_method', ok: true },
      null,
      'zh-Hans',
    ),
    '处理中…',
  )
})

test('legacy execution tools have readable fallback labels', () => {
  assert.equal(
    assistLanguage.formatAssistToolActivity({ name: 'run_workflow', ok: true }, null, 'zh-Hans'),
    '试运行工作流',
  )
  assert.equal(
    assistLanguage.formatAssistToolActivity({ name: 'run_acceptance', ok: true }, null, 'zh-Hans'),
    '运行验收',
  )
  assert.equal(
    assistLanguage.formatAssistToolActivity({ name: 'inspect_mock_targets', ok: true }, null, 'zh-Hans'),
    '检查模拟运行条件',
  )
})

test('completion markdown keeps summary, diff, and validation as formatted copy', () => {
  assert.equal(
    assistLanguage.formatAssistCompletionMarkdown(
      {
        summary: '已搭好 RAG 测试工作流',
        diff: { added: ['n1'], removed: [], updated: ['n2'] },
        validation: { ok: true },
        verification: { structure: 'passed', runtime: 'simulated_passed', business: 'unverified' },
      },
      'zh-Hans',
    ),
    '**工作流已更新**\n\n已搭好 RAG 测试工作流\n\n- ✓ 结构校验通过\n- ✓ 模拟试运行通过\n- ! 自动化业务断言尚未验证\n\n**变更:** +1 ~1 −0',
  )
})

test('completion markdown distinguishes a live workflow run from business assertion coverage', () => {
  assert.equal(
    assistLanguage.formatAssistCompletionMarkdown(
      {
        verification: { structure: 'passed', runtime: 'live_passed', business: 'unverified' },
      },
      'zh-Hans',
    ),
    '**工作流已更新**\n\n- ✓ 结构校验通过\n- ✓ 真实运行通过\n- ! 自动化业务断言尚未验证',
  )
})
