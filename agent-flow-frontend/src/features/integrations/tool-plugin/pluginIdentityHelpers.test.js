import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  isValidPluginIdentityName,
  isValidToolIdentityName,
  PLUGIN_IDENTITY_NAME_HINT,
  TOOL_IDENTITY_NAME_HINT,
  pluginIdentityFieldError,
  sanitizePluginIdSegment,
  sanitizePluginIdentityName,
  sanitizeToolIdentityName,
  toolIdentityFieldError,
} from './pluginIdentityHelpers.js'
import { normalizePluginProviderId } from './previewFromFiles.js'

describe('sanitizePluginIdentityName', () => {
  it('maps illegal chars to hyphen and lowercases', () => {
    assert.equal(sanitizePluginIdentityName('Remove.bg'), 'remove-bg')
    assert.equal(sanitizePluginIdentityName('My Plugin'), 'my-plugin')
    assert.equal(sanitizePluginIdentityName('weather_plugin'), 'weather_plugin')
    assert.equal(sanitizePluginIdentityName('remove-bg'), 'remove-bg')
  })
})

describe('sanitizeToolIdentityName', () => {
  it('maps hyphens and illegal chars to underscore', () => {
    assert.equal(sanitizeToolIdentityName('remove-image-background'), 'remove_image_background')
    assert.equal(sanitizeToolIdentityName('Remove.Image'), 'remove_image')
    assert.equal(sanitizeToolIdentityName('query_weather'), 'query_weather')
  })
})

describe('isValidPluginIdentityName', () => {
  it('accepts only a-z 0-9 _ -', () => {
    assert.equal(isValidPluginIdentityName('remove-bg'), true)
    assert.equal(isValidPluginIdentityName('remove.bg'), false)
    assert.equal(isValidPluginIdentityName(''), false)
  })
})

describe('isValidToolIdentityName', () => {
  it('rejects hyphens', () => {
    assert.equal(isValidToolIdentityName('remove_image_background'), true)
    assert.equal(isValidToolIdentityName('remove-image-background'), false)
    assert.equal(isValidToolIdentityName(''), false)
  })
})

describe('pluginIdentityFieldError / toolIdentityFieldError', () => {
  it('keeps illegal input as error text without suggesting rewrite', () => {
    assert.equal(pluginIdentityFieldError('Remove.bg'), PLUGIN_IDENTITY_NAME_HINT)
    assert.equal(pluginIdentityFieldError('remove-bg'), '')
    assert.equal(pluginIdentityFieldError('', { required: true }), '不能为空')
    assert.equal(toolIdentityFieldError('bad-name'), TOOL_IDENTITY_NAME_HINT)
    assert.equal(toolIdentityFieldError('good_name'), '')
  })
})

describe('sanitizePluginIdSegment + normalizePluginProviderId', () => {
  it('repairs dotted plugin segment to hyphen', () => {
    assert.equal(sanitizePluginIdSegment('remove.bg'), 'remove-bg')
    assert.equal(
      normalizePluginProviderId('ghy/remove.bg', { providerName: 'remove-bg' }),
      'ghy/remove-bg/remove-bg',
    )
    assert.equal(
      normalizePluginProviderId('ghy/remove.bg/remove-bg'),
      'ghy/remove-bg/remove-bg',
    )
  })
})
