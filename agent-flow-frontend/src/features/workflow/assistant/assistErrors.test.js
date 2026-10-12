import test from 'node:test'
import assert from 'node:assert/strict'

import * as assistErrors from './assistErrors.js'

const { assistErrorAction, friendlyAssistError } = assistErrors

test('friendlyAssistError maps provider_error to readable copy', () => {
  const result = friendlyAssistError({ code: 'provider_error', detail: 'provider_error' }, 'zh-Hans')
  assert.match(result.text, /模型/)
  assert.equal(result.raw, 'provider_error')
})

test('friendlyAssistError keeps the provider exception as raw detail', () => {
  const result = friendlyAssistError({ code: 'provider_error', detail: '429 rate limit' }, 'zh-Hans')
  assert.equal(result.text, '模型请求过于频繁（HTTP 429）。')
  assert.equal(result.hint, '请稍后重试，或切换到限额更充足的模型。')
  assert.equal(result.raw, '429 rate limit')
  assert.equal(result.code, 'provider_error')
  assert.equal(result.openRaw, true)
})

test('friendlyAssistError exposes an actionable balance error above the raw provider traceback', () => {
  const detail = `req_id: 89ab9823bd PluginInvokeError: {'args': {'description': '[models] Error 402: {"error":{"message":"Insufficient Balance"}}'}}`
  const result = friendlyAssistError({ code: 'provider_error', detail }, 'zh-Hans')

  assert.deepEqual(result, {
    text: '模型账户余额不足（HTTP 402）。',
    hint: '请充值或切换到有可用额度的模型后重试。',
    raw: detail,
    code: 'provider_error',
    openRaw: true,
  })
})

test('friendlyAssistError distinguishes provider authentication and timeout failures', () => {
  assert.deepEqual(
    friendlyAssistError({ code: 'provider_error', detail: 'HTTP 401 Unauthorized: invalid API key' }, 'zh-Hans'),
    {
      text: '模型服务鉴权失败（HTTP 401/403）。',
      hint: '请检查模型凭据和访问权限，或切换模型后重试。',
      raw: 'HTTP 401 Unauthorized: invalid API key',
      code: 'provider_error',
      openRaw: true,
    },
  )
  assert.deepEqual(
    friendlyAssistError({ code: 'provider_error', detail: 'upstream request timed out' }, 'zh-Hans'),
    {
      text: '模型服务请求超时。',
      hint: '请检查网络或稍后重试。',
      raw: 'upstream request timed out',
      code: 'provider_error',
      openRaw: true,
    },
  )
})

test('copyAssistErrorText writes the complete raw error to the clipboard boundary', async () => {
  assert.equal(typeof assistErrors.copyAssistErrorText, 'function')
  let copied = ''
  const ok = await assistErrors.copyAssistErrorText('full traceback\nline 2', async text => { copied = text })

  assert.equal(ok, true)
  assert.equal(copied, 'full traceback\nline 2')
})

test('assistErrorAction retries provider_error', () => {
  assert.equal(assistErrorAction([{ code: 'provider_error', detail: 'provider down' }]), 'retry')
})
