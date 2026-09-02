import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildCredentialsPayload,
  buildInitialCredentialFormValues,
  getVisibleCredentialFields,
  normalizeCredentialFormFields,
} from './credentialFormHelpers.js'

const tongyiSchemas = [
  {
    variable: 'dashscope_api_key',
    label: { zh_Hans: 'API Key', en_US: 'API Key' },
    type: 'secret-input',
    required: true,
  },
  {
    variable: 'use_international_endpoint',
    label: { zh_Hans: '使用国际端点', en_US: 'Use International Endpoint' },
    type: 'radio',
    required: true,
    default: 'false',
    options: [
      { label: { zh_Hans: '是', en_US: 'True' }, value: 'true' },
      { label: { zh_Hans: '否', en_US: 'False' }, value: 'false' },
    ],
  },
]

test('normalizeCredentialFormFields maps tongyi radio options and default', () => {
  const fields = normalizeCredentialFormFields(tongyiSchemas)
  assert.equal(fields.length, 2)
  assert.equal(fields[1].type, 'radio')
  assert.equal(fields[1].default, 'false')
  assert.equal(fields[1].options.length, 2)
  assert.equal(fields[1].options[0].value, 'true')
  assert.equal(fields[1].options[0].label, '是')
})

test('buildInitialCredentialFormValues uses radio default false for tongyi', () => {
  const fields = normalizeCredentialFormFields(tongyiSchemas)
  const values = buildInitialCredentialFormValues(fields)
  assert.equal(values.use_international_endpoint, 'false')
  assert.equal(values.dashscope_api_key, '')
})

test('buildCredentialsPayload rejects international endpoint URL', () => {
  const fields = normalizeCredentialFormFields(tongyiSchemas)
  assert.throws(
    () => buildCredentialsPayload(fields, {
      dashscope_api_key: 'sk-test',
      use_international_endpoint: 'https://dashscope-intl.aliyuncs.com/api/v1',
    }),
    /使用国际端点/,
  )
})

test('buildCredentialsPayload accepts true/false radio values', () => {
  const fields = normalizeCredentialFormFields(tongyiSchemas)
  const payload = buildCredentialsPayload(fields, {
    dashscope_api_key: 'sk-test',
    use_international_endpoint: 'true',
  })
  assert.equal(payload.dashscope_api_key, 'sk-test')
  assert.equal(payload.use_international_endpoint, 'true')
})

test('show_on hides fields that do not match', () => {
  const fields = normalizeCredentialFormFields([
    {
      variable: 'mode',
      type: 'radio',
      default: 'basic',
      options: [
        { value: 'basic', label: 'Basic' },
        { value: 'advanced', label: 'Advanced' },
      ],
    },
    {
      variable: 'extra',
      type: 'text-input',
      required: true,
      show_on: [{ variable: 'mode', value: 'advanced' }],
    },
  ])
  const basicVisible = getVisibleCredentialFields(fields, { mode: 'basic' })
  assert.equal(basicVisible.length, 1)
  assert.equal(basicVisible[0].variable, 'mode')

  const advancedVisible = getVisibleCredentialFields(fields, { mode: 'advanced' })
  assert.equal(advancedVisible.length, 2)

  const payload = buildCredentialsPayload(fields, { mode: 'basic', extra: 'should-not-send' })
  assert.equal(payload.mode, 'basic')
  assert.equal(payload.extra, undefined)
})

test('normalizeCredentialFormFields accepts tool schema name field', () => {
  const fields = normalizeCredentialFormFields({
    credentials_schema: [
      { name: 'api_key', type: 'secret-input', label: 'Key', required: true },
    ],
  })
  assert.equal(fields[0].variable, 'api_key')
  assert.equal(fields[0].secret, true)
})
