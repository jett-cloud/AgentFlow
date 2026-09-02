import test from 'node:test'
import assert from 'node:assert/strict'

import { assistErrorAction, friendlyAssistError } from './assistErrors.js'

test('friendlyAssistError maps provider_error to readable copy', () => {
  const result = friendlyAssistError({ code: 'provider_error', detail: 'provider_error' }, 'zh-Hans')
  assert.match(result.text, /模型/)
  assert.equal(result.raw, 'provider_error')
})

test('friendlyAssistError keeps the provider exception as raw detail', () => {
  const result = friendlyAssistError({ code: 'provider_error', detail: '429 rate limit' }, 'zh-Hans')
  assert.match(result.text, /模型/)
  assert.equal(result.raw, '429 rate limit')
})

test('assistErrorAction retries provider_error', () => {
  assert.equal(assistErrorAction([{ code: 'provider_error', detail: 'provider down' }]), 'retry')
})
