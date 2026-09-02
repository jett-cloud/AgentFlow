import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('tool selection persists provider_icon for workflow nodes', () => {
  const selector = readFileSync(new URL('../../canvas/components/BlockSelectorMenu.vue', import.meta.url), 'utf8')
  const config = readFileSync(new URL('./useToolConfig.js', import.meta.url), 'utf8')
  const baseNode = readFileSync(new URL('../base/BaseNode.vue', import.meta.url), 'utf8')
  const blockIcon = readFileSync(new URL('../base/BlockIcon.vue', import.meta.url), 'utf8')

  assert.match(selector, /provider_icon:\s*tool\.icon/)
  assert.match(config, /provider_icon:\s*tool\.icon/)
  assert.match(baseNode, /:tool-icon="resolvedToolIcon"/)
  assert.match(baseNode, /provider_icon/)
  assert.match(blockIcon, /toolIcon/)
  assert.match(blockIcon, /toolProviderIcon/)
})
