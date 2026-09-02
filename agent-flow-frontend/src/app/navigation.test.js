import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { navigationItems, resolveActiveNavigation } from './navigation.js'

test('navigation items map the three top-level destinations', () => {
  assert.deepEqual(
    navigationItems.map(({ id, label, to }) => ({ id, label, to })),
    [
      { id: 'copilot', label: 'CoPilot 协同设计', to: '/' },
      { id: 'integrations', label: 'Integrations', to: '/integrations' },
      { id: 'knowledge', label: 'Knowledge', to: '/datasets' },
    ],
  )
})

test('navigation configuration only contains routing and display data', () => {
  assert.deepEqual(
    navigationItems.map(item => Object.keys(item).sort()),
    navigationItems.map(() => ['id', 'label', 'to']),
  )
})

test('resolveActiveNavigation groups nested routes under their top-level destination', () => {
  assert.equal(resolveActiveNavigation('/'), 'copilot')
  assert.equal(resolveActiveNavigation('/integrations/tools/ai-create'), 'integrations')
  assert.equal(resolveActiveNavigation('/datasets/example/documents'), 'knowledge')
})

test('top navigation uses a single native CSS face without fixed item widths', () => {
  const source = readFileSync(new URL('./components/TopNavigation.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(source, /motion-v|navigation-glow|navigation-face-back/)
  assert.doesNotMatch(source, /min-width:\s*104px/)
  assert.match(source, /aria-current/)
})
