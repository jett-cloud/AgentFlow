import assert from 'node:assert/strict'
import test from 'node:test'
import * as helpers from './sandboxParameterHelpers.js'

test('direct publish payload excludes credentials, test parameters, and authorization', () => {
  const payload = helpers.buildDirectPublishPayload?.({
    expectedRevision: 7,
    toolName: 'image_to_image',
  })

  assert.deepEqual(payload, {
    expected_revision: 7,
    tool_name: 'image_to_image',
    publish_mode: 'direct',
    parameters: {},
    credentials: {},
  })
})
