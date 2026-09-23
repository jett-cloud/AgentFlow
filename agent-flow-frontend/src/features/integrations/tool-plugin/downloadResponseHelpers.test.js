import assert from 'node:assert/strict'
import test from 'node:test'

let helpers = {}
try {
  helpers = await import('./downloadResponseHelpers.js')
}
catch {
  // The red test intentionally starts before the helper exists.
}

test('reads the API message from a JSON blob error response', async () => {
  assert.equal(typeof helpers.readBlobErrorMessage, 'function')
  const blob = new Blob([
    JSON.stringify({ message: 'plugin_name must not be empty' }),
  ], { type: 'application/json' })

  assert.equal(await helpers.readBlobErrorMessage(blob), 'plugin_name must not be empty')
})

test('falls back cleanly for a non-JSON blob error response', async () => {
  assert.equal(typeof helpers.readBlobErrorMessage, 'function')
  const blob = new Blob(['Bad request'], { type: 'text/plain' })

  assert.equal(await helpers.readBlobErrorMessage(blob), 'Bad request')
})
