import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

test('shared panel header exposes a backwards-compatible node description editor', () => {
  const source = readFileSync(new URL('../nodes/shared/PanelHeader.vue', import.meta.url), 'utf8')
  assert.match(source, /description \|\| legacyDescription/)
  assert.match(source, /update:description/)
  assert.match(source, /textarea/)
})

test('node panel shell normalizes description updates to desc', () => {
  const source = readFileSync(new URL('../nodes/shared/NodePanelShell.vue', import.meta.url), 'utf8')
  assert.match(source, /@update:description="updateDescription"/)
  assert.match(source, /desc: description/)
})
