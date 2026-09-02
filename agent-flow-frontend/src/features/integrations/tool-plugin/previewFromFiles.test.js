import test from 'node:test'
import assert from 'node:assert/strict'
import { enrichPreviewToolFromFiles, extractCredentialsSchemaFromFiles } from './previewFromFiles.js'

const FILES = {
  'provider/doubao_image_tools.yaml': `
identity:
  name: doubao_image_tools
credentials_for_provider:
  volcengine_access_key:
    type: secret-input
    required: true
    label:
      zh_Hans: 火山引擎 Access Key
  volcengine_secret_key:
    type: secret-input
    required: true
    label:
      zh_Hans: 火山引擎 Secret Key
`,
  'tools/generate_image.yaml': `
identity:
  name: generate_image
  label:
    en_US: Generate Image
parameters:
  - name: prompt
    type: string
    required: true
`,
}

test('extracts credentials schema from provider yaml', () => {
  const schema = extractCredentialsSchemaFromFiles(FILES)
  assert.equal(schema.length, 2)
  assert.equal(schema[0].name, 'volcengine_access_key')
  assert.equal(schema[1].name, 'volcengine_secret_key')
})

test('enriches stale preview_tool missing credentials_schema', () => {
  const enriched = enrichPreviewToolFromFiles(
    {
      provider_id: 'ghy/doubao_image_tools',
      tool_name: 'generate_image',
      parameters_schema: [{ name: 'prompt', type: 'string' }],
    },
    FILES,
  )
  assert.equal(enriched.credentials_schema.length, 2)
  assert.equal(enriched.tool_name, 'generate_image')
  assert.equal(enriched.provider_id, 'ghy/doubao_image_tools/doubao_image_tools')
})

test('normalizes hyphenated tool identity to underscore for sandbox', () => {
  const files = {
    ...FILES,
    'tools/remove-image-background.yaml': `
identity:
  name: remove-image-background
  label:
    en_US: Remove Image Background
parameters: []
`,
  }
  const enriched = enrichPreviewToolFromFiles(
    { provider_id: 'ghy/remove-bg', tool_name: 'remove_image_background' },
    files,
    { toolName: 'remove_image_background' },
  )
  assert.equal(enriched.tool_name, 'remove_image_background')
})
