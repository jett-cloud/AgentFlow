import test from 'node:test'
import assert from 'node:assert/strict'
import {
  getProcessedStartVariableInputs,
  getStartVariableDefault,
  normalizeStartVariableType,
  validateStartVariableInputs,
} from './startVariableUtils.js'

test('normalizes AgentFlow file aliases to Dify input types', () => {
  assert.equal(normalizeStartVariableType('single-file'), 'file')
  assert.equal(normalizeStartVariableType('multi-files'), 'file-list')
  assert.equal(normalizeStartVariableType('file'), 'file')
})

test('normalizes legacy JSON aliases to the canonical Dify input type', () => {
  assert.equal(normalizeStartVariableType('json-object'), 'json_object')
  assert.equal(normalizeStartVariableType('json_object'), 'json_object')
})

test('builds empty defaults for file variables', () => {
  assert.equal(getStartVariableDefault({ type: 'single-file' }), null)
  assert.deepEqual(getStartVariableDefault({ type: 'multi-files' }), [])
})

test('validates uploaded file entities instead of their display text', () => {
  const variables = [{ variable: 'document', type: 'single-file', label: '文档', required: true }]
  assert.deepEqual(validateStartVariableInputs(variables, { document: { name: 'draft.pdf' } }), ['文档'])
  assert.deepEqual(validateStartVariableInputs(variables, {
    document: { uploadedId: 'upload-1', supportFileType: 'document', transferMethod: 'local_file' },
  }), [])
})

test('converts uploaded start files to Dify run payloads', () => {
  const variables = [
    { variable: 'document', type: 'single-file' },
    { variable: 'attachments', type: 'multi-files' },
  ]
  const result = getProcessedStartVariableInputs(variables, {
    document: {
      uploadedId: 'upload-1',
      supportFileType: 'document',
      transferMethod: 'local_file',
      url: '',
    },
    attachments: [{
      uploadedId: 'upload-2',
      supportFileType: 'image',
      transferMethod: 'remote_url',
      url: 'https://example.com/a.png',
    }],
  })
  assert.deepEqual(result.document, {
    type: 'document',
    transfer_method: 'local_file',
    url: '',
    upload_file_id: 'upload-1',
  })
  assert.deepEqual(result.attachments, [{
    type: 'image',
    transfer_method: 'remote_url',
    url: 'https://example.com/a.png',
    upload_file_id: 'upload-2',
  }])
})

test('converts canonical JSON Start input text to an object', () => {
  const result = getProcessedStartVariableInputs(
    [{ variable: 'payload', type: 'json_object' }],
    { payload: '{"enabled":true}' },
  )

  assert.deepEqual(result.payload, { enabled: true })
})
