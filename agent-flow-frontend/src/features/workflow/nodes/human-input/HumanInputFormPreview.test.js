import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { humanInputPreviewActionClass } from './humanInputNode.js'

const previewSource = readFileSync(new URL('./HumanInputFormPreview.vue', import.meta.url), 'utf8')

test('preview action class maps each button_style to a distinct style hook', () => {
  assert.equal(humanInputPreviewActionClass('primary'), 'action-style-primary')
  assert.equal(humanInputPreviewActionClass('default'), 'action-style-default')
  assert.equal(humanInputPreviewActionClass('accent'), 'action-style-accent')
  assert.equal(humanInputPreviewActionClass('ghost'), 'action-style-ghost')
  assert.equal(humanInputPreviewActionClass('unknown'), 'action-style-default')
})

test('preview stylesheet paints accent and ghost differently from default', () => {
  assert.match(previewSource, /humanInputPreviewActionClass/)
  assert.match(previewSource, /\.action-style-accent\b[\s\S]*#f4ebff/)
  assert.match(previewSource, /\.action-style-ghost\b[\s\S]*#ffffff/)
  assert.match(previewSource, /\.action-style-default\b[\s\S]*#f2f4f7/)
  assert.match(previewSource, /\.action-style-ghost\b[\s\S]*#d0d5dd/)
})
