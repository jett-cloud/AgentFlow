import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  buildSandboxFilePayload,
  buildSandboxTestParameters,
  defaultSandboxParameterValue,
  missingRequiredSandboxParameters,
  parameterWidgetKind,
} from './sandboxParameterHelpers.js'

describe('parameterWidgetKind', () => {
  it('maps file / files / options / number / boolean', () => {
    assert.equal(parameterWidgetKind({ type: 'file' }), 'file')
    assert.equal(parameterWidgetKind({ type: 'files' }), 'files')
    assert.equal(parameterWidgetKind({
      type: 'string',
      options: [{ value: 'auto', label: { zh_Hans: '自动' } }],
    }), 'select')
    assert.equal(parameterWidgetKind({ type: 'number' }), 'number')
    assert.equal(parameterWidgetKind({ type: 'boolean' }), 'boolean')
    assert.equal(parameterWidgetKind({ type: 'string' }), 'text')
  })
})

describe('defaultSandboxParameterValue', () => {
  it('uses schema default for select options', () => {
    assert.equal(defaultSandboxParameterValue({
      type: 'string',
      default: 'auto',
      options: [
        { value: 'auto' },
        { value: 'full' },
      ],
    }), 'auto')
  })

  it('returns null / [] for file parameters', () => {
    assert.equal(defaultSandboxParameterValue({ type: 'file' }), null)
    assert.deepEqual(defaultSandboxParameterValue({ type: 'files' }), [])
  })
})

describe('buildSandboxFilePayload + test parameters', () => {
  it('builds local file payload and strips UI fields for test API', () => {
    const payload = buildSandboxFilePayload({
      uploadFileId: 'fid-1',
      transferMethod: 'local_file',
      url: 'https://example.com/a.png',
      name: 'a.png',
      mimeType: 'image/png',
      size: 12,
    })
    assert.equal(payload.type, 'image')
    assert.equal(payload.upload_file_id, 'fid-1')

    const params = buildSandboxTestParameters(
      [{ name: 'image_file', type: 'file', required: true }],
      { image_file: { type: 'constant', value: payload } },
    )
    assert.deepEqual(params.image_file, {
      type: 'image',
      transfer_method: 'local_file',
      url: 'https://example.com/a.png',
      upload_file_id: 'fid-1',
    })
  })
})

describe('missingRequiredSandboxParameters', () => {
  it('flags required file when missing upload_file_id', () => {
    const missing = missingRequiredSandboxParameters(
      [
        { name: 'image_file', type: 'file', required: true },
        { name: 'size', type: 'string', required: true, options: [{ value: 'auto' }], default: 'auto' },
      ],
      {
        image_file: { type: 'constant', value: null },
        size: { type: 'constant', value: 'auto' },
      },
    )
    assert.deepEqual(missing, ['image_file'])
  })

  it('passes when required file is uploaded', () => {
    const missing = missingRequiredSandboxParameters(
      [{ name: 'image_file', type: 'file', required: true }],
      {
        image_file: {
          type: 'constant',
          value: {
            type: 'image',
            transfer_method: 'local_file',
            upload_file_id: 'fid-1',
            url: '',
          },
        },
      },
    )
    assert.deepEqual(missing, [])
  })
})
