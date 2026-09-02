import test from 'node:test'
import assert from 'node:assert/strict'
import {
  integrationsTabPath,
  marketplaceDetailPath,
  MARKETPLACE_ROUTES,
} from './marketplaceRoutes.js'

test('marketplace routes are separate from integrations tabs', () => {
  assert.equal(MARKETPLACE_ROUTES.tools, '/integrations/marketplace/tools')
  assert.equal(MARKETPLACE_ROUTES.models, '/integrations/marketplace/models')
  assert.equal(
    marketplaceDetailPath('tool', 'langgenius', 'google'),
    '/integrations/marketplace/tools/langgenius/google',
  )
  assert.equal(integrationsTabPath('tools'), '/integrations?tab=tools')
})
