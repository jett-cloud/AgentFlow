import assert from 'node:assert/strict'
import test from 'node:test'

import difyClient from '../../../shared/http/difyClient.js'
import { exportAppDsl } from './difyWorkflowApi.js'

test('DSL export encodes the app id and explicitly chooses whether to include secrets', async () => {
  const originalGet = difyClient.get
  const response = { data: 'version: 0.3.0' }
  let call
  difyClient.get = async (...args) => {
    call = args
    return response
  }
  try {
    const result = await exportAppDsl('app /1')
    assert.equal(result, response)
    assert.deepEqual(call, [
      '/apps/app%20%2F1/export',
      { params: { include_secret: false } },
    ])

    await exportAppDsl('app /1', { includeSecret: true })
    assert.deepEqual(call, [
      '/apps/app%20%2F1/export',
      { params: { include_secret: true } },
    ])
  }
  finally {
    difyClient.get = originalGet
  }
})
