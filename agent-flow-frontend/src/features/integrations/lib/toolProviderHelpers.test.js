import test from 'node:test'
import assert from 'node:assert/strict'
import { marketplaceIconUrl, toolProviderIcon } from './toolProviderHelpers.js'

test('toolProviderIcon prefers console asset url strings', () => {
  const icon = toolProviderIcon({
    label: 'Demo',
    icon: 'http://localhost:5001/console/api/workspaces/current/plugin/icon?id=x',
  })
  assert.equal(icon.type, 'url')
  assert.match(icon.value, /\/console\/api\//)
})

test('toolProviderIcon supports emoji icon objects', () => {
  const icon = toolProviderIcon({
    label: 'Demo',
    icon: { content: '🔧', background: '#fff7ed' },
  })
  assert.equal(icon.type, 'emoji')
  assert.equal(icon.value, '🔧')
})

test('marketplaceIconUrl prefers explicit http icon then official path', () => {
  assert.equal(marketplaceIconUrl({ icon: 'https://cdn.example/a.png' }), 'https://cdn.example/a.png')
  assert.equal(
    marketplaceIconUrl({ org: 'langgenius', name: 'tavily' }),
    'https://marketplace.dify.ai/api/v1/plugins/langgenius/tavily/icon',
  )
})
