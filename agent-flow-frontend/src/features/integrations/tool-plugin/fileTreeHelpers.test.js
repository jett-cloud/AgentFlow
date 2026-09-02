import test from 'node:test'
import assert from 'node:assert/strict'
import { filesArrayToMap, filesMapToArray } from './fileTreeHelpers.js'

test('round-trip files map', () => {
  const map = filesArrayToMap([{ path: 'a.yaml', content: 'x' }])

  assert.equal(map['a.yaml'], 'x')
  assert.deepEqual(filesMapToArray(map), [{ path: 'a.yaml', content: 'x' }])
})
