import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const dir = dirname(fileURLToPath(import.meta.url))
test('VarReferencePicker imports formatValueSelector', () => {
  const src = readFileSync(join(dir, 'VarReferencePicker.vue'), 'utf8')
  assert.match(src, /formatValueSelector/)
  assert.match(src, /from ['"].*variableOutputs\.js['"]/)
})
