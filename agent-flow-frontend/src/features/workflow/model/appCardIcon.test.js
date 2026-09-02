import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveAppCardIcon } from './appCardIcon.js'

test('image app icons use the preview URL instead of exposing the stored file id', () => {
  assert.deepEqual(resolveAppCardIcon({
    name: '客服工作流',
    icon_type: 'image',
    icon: '16bb977f-560e-4e09-9cac-97bc080aa851',
    icon_url: '/console/api/files/16bb977f-560e-4e09-9cac-97bc080aa851/image-preview',
  }), {
    type: 'image',
    src: '/console/api/files/16bb977f-560e-4e09-9cac-97bc080aa851/image-preview',
  })
})

test('image app icons without a preview URL fall back to the app initial', () => {
  const icon = resolveAppCardIcon({
    name: '客服工作流',
    icon_type: 'image',
    icon: '16bb977f-560e-4e09-9cac-97bc080aa851',
  })
  assert.equal(icon.type, 'initial')
  assert.equal(icon.value, '客')
  assert.match(icon.background, /^#[0-9a-f]{6}$/i)
})

test('legacy emoji app icons render the app initial instead', () => {
  const icon = resolveAppCardIcon({
    name: 'Agent',
    icon_type: 'emoji',
    icon: '🤖',
    icon_background: '#fce7f3',
  })
  assert.equal(icon.type, 'initial')
  assert.equal(icon.value, 'A')
  assert.match(icon.background, /^#[0-9a-f]{6}$/i)
})

test('initial backgrounds are stable per name and vary between names', () => {
  const first = resolveAppCardIcon({ name: 'Alpha', icon_type: 'emoji' })
  const repeated = resolveAppCardIcon({ name: 'Alpha', icon_type: 'emoji' })
  const another = resolveAppCardIcon({ name: 'Beta', icon_type: 'emoji' })

  assert.equal(first.background, repeated.background)
  assert.notEqual(first.background, another.background)
})
