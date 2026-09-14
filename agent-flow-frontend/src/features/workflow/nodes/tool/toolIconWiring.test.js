import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { applyToolSelection } from './toolNode.js'

test('tool selection persists provider_icon for workflow nodes', () => {
  assert.equal(
    applyToolSelection({}, { provider_id: 'p', tool_name: 't', icon: 'big', icon_small: 'small' }).provider_icon,
    'big',
  )
  assert.equal(
    applyToolSelection({}, { provider_id: 'p', tool_name: 't', icon_small: 'small' }).provider_icon,
    'small',
  )
  assert.equal(
    applyToolSelection({}, { provider_id: 'p', tool_name: 't' }).provider_icon,
    null,
  )

  const selector = readFileSync(new URL('../../canvas/components/BlockSelectorMenu.vue', import.meta.url), 'utf8')
  const baseNode = readFileSync(new URL('../base/BaseNode.vue', import.meta.url), 'utf8')
  const blockIcon = readFileSync(new URL('../base/BlockIcon.vue', import.meta.url), 'utf8')

  assert.match(selector, /provider_icon:\s*tool\.icon/)
  assert.match(baseNode, /:tool-icon="resolvedToolIcon"/)
  assert.match(baseNode, /provider_icon/)
  assert.match(blockIcon, /toolIcon/)
  assert.match(blockIcon, /toolProviderIcon/)
})
