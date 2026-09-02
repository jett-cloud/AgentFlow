import test from 'node:test'
import assert from 'node:assert/strict'
import {
  findInstallationForPluginId,
  getMarketplacePluginIconUrl,
  unwrapPluginList,
} from './difyPluginsApi.js'

test('unwrapPluginList supports common payload shapes', () => {
  assert.deepEqual(unwrapPluginList({ plugins: [{ id: 1 }] }), [{ id: 1 }])
  assert.deepEqual(unwrapPluginList({ data: { plugins: [{ id: 2 }] } }), [{ id: 2 }])
})

test('findInstallationForPluginId matches plugin_id and unique identifier prefix', () => {
  const plugins = [
    {
      plugin_id: 'acme/demo',
      plugin_unique_identifier: 'acme/demo:0.0.1',
      installation_id: 'inst-1',
    },
  ]
  assert.equal(findInstallationForPluginId(plugins, 'acme/demo')?.installation_id, 'inst-1')
  assert.equal(findInstallationForPluginId(plugins, 'missing'), null)
})

test('marketplace icon uses official plugins/org/name/icon URL', () => {
  assert.equal(
    getMarketplacePluginIconUrl({ org: 'langgenius', name: 'google' }),
    'https://marketplace.dify.ai/api/v1/plugins/langgenius/google/icon',
  )
})
