import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const source = fs.readFileSync(new URL('./StartVariableInput.vue', import.meta.url), 'utf8')

test('file input uses a styled upload card instead of exposing the native picker', () => {
  assert.match(source, /class="upload-card"/)
  assert.match(source, /class="visually-hidden"/)
  assert.match(source, /class="choose-file-button"/)
  assert.match(source, /选择文件/)
  assert.match(source, /支持本地上传/)
})

test('remote upload and uploaded files use dedicated styled rows', () => {
  assert.match(source, /class="remote-upload"/)
  assert.match(source, /class="file-item"/)
  assert.match(source, /class="remove-file-button"/)
})

test('JSON input renders from the canonical json_object type', () => {
  assert.match(source, /normalizedType === 'json_object'/)
  assert.doesNotMatch(source, /normalizedType === 'json-object'/)
})
