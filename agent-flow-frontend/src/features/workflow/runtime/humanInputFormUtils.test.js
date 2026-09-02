import test from 'node:test'
import assert from 'node:assert/strict'
import {
  allowsLocalHumanInputUpload,
  allowsRemoteHumanInputUpload,
  createLocalHumanInputFileEntity,
  createRemoteHumanInputFileEntity,
  getHumanInputFileNumberLimit,
  getHumanInputSelectOptions,
  getProcessedHumanInputFormInputs,
  getRenderableHumanInputFields,
  getVisibleHumanInputForms,
  guessSupportFileType,
  initializeHumanInputValues,
  isHumanInputFileUploaded,
  isValidRemoteFileUrl,
  markHumanInputFileUploaded,
  removeHumanInputFormByNodeId,
  validateHumanInputValues,
} from './humanInputFormUtils.js'

test('getVisibleHumanInputForms requires token and display_in_ui', () => {
  const list = getVisibleHumanInputForms([
    { node_id: 'a', form_token: 't1', display_in_ui: true },
    { node_id: 'b', form_token: null, display_in_ui: true },
    { node_id: 'c', form_token: 't3', display_in_ui: false },
    { node_id: 'd', form_token: 't4' },
  ])
  assert.deepEqual(list.map(f => f.node_id), ['a', 'd'])
})

test('initializeHumanInputValues includes file defaults', () => {
  const values = initializeHumanInputValues({
    resolved_default_values: { note: '预填' },
    inputs: [
      { type: 'paragraph', output_variable_name: 'note', default: { value: 'fallback' } },
      { type: 'select', output_variable_name: 'choice', option_source: { value: ['x', 'y'] } },
      { type: 'file', output_variable_name: 'doc' },
      { type: 'file-list', output_variable_name: 'docs', number_limits: 3 },
    ],
  })
  assert.deepEqual(values, {
    note: '预填',
    choice: '',
    doc: null,
    docs: [],
  })
  assert.deepEqual(
    getRenderableHumanInputFields({
      inputs: [
        { type: 'paragraph', output_variable_name: 'note' },
        { type: 'file', output_variable_name: 'doc' },
        { type: 'file-list', output_variable_name: 'docs' },
      ],
    }).map(f => f.output_variable_name),
    ['note', 'doc', 'docs'],
  )
  assert.deepEqual(getHumanInputSelectOptions({ option_source: { value: ['a'] } }), ['a'])
  assert.equal(getHumanInputFileNumberLimit({ type: 'file' }), 1)
  assert.equal(getHumanInputFileNumberLimit({ type: 'file-list' }), 5)
  assert.equal(getHumanInputFileNumberLimit({ type: 'file-list', number_limits: 3 }), 3)
})

test('file entity upload marking and processed submit payload', () => {
  assert.equal(guessSupportFileType('a.png', 'image/png'), 'image')
  assert.equal(guessSupportFileType('a.pdf', 'application/pdf'), 'document')

  const entity = createLocalHumanInputFileEntity({
    name: 'a.png',
    size: 12,
    type: 'image/png',
  })
  assert.equal(isHumanInputFileUploaded(entity), false)
  const uploaded = markHumanInputFileUploaded(entity, { id: 'fid-1', mime_type: 'image/png' })
  assert.equal(isHumanInputFileUploaded(uploaded), true)
  assert.equal(uploaded.uploadedId, 'fid-1')

  const processed = getProcessedHumanInputFormInputs(
    [
      { type: 'paragraph', output_variable_name: 'note' },
      { type: 'file', output_variable_name: 'doc' },
      { type: 'file-list', output_variable_name: 'docs' },
    ],
    {
      note: 'hi',
      doc: uploaded,
      docs: [uploaded],
    },
  )
  assert.equal(processed.note, 'hi')
  assert.deepEqual(processed.doc, {
    type: 'image',
    transfer_method: 'local_file',
    url: '',
    upload_file_id: 'fid-1',
  })
  assert.equal(processed.docs.length, 1)
  assert.equal(processed.docs[0].upload_file_id, 'fid-1')
})

test('validateHumanInputValues blocks missing required files', () => {
  const fields = [
    { type: 'file', output_variable_name: 'doc', required: true, label: '附件' },
    { type: 'file-list', output_variable_name: 'docs', required: true },
  ]
  assert.match(validateHumanInputValues(fields, { doc: null, docs: [] }), /附件/)
  const uploaded = markHumanInputFileUploaded(
    createLocalHumanInputFileEntity({ name: 'a.txt', size: 1, type: 'text/plain' }),
    { id: 'x' },
  )
  assert.equal(
    validateHumanInputValues(fields, { doc: uploaded, docs: [uploaded] }),
    '',
  )
})

test('remote_url methods and processed payload', () => {
  assert.equal(allowsLocalHumanInputUpload({}), true)
  assert.equal(allowsRemoteHumanInputUpload({}), true)
  assert.equal(allowsRemoteHumanInputUpload({
    allowed_file_upload_methods: ['local_file'],
  }), false)
  assert.equal(allowsLocalHumanInputUpload({
    allowed_file_upload_methods: ['remote_url'],
  }), false)
  assert.equal(isValidRemoteFileUrl('https://example.com/a.png'), true)
  assert.equal(isValidRemoteFileUrl('ftp://x'), false)
  assert.equal(isValidRemoteFileUrl('not-a-url'), false)

  const entity = createRemoteHumanInputFileEntity('https://cdn.example.com/a.png')
  assert.equal(entity.transferMethod, 'remote_url')
  assert.equal(isHumanInputFileUploaded(entity), false)
  const uploaded = markHumanInputFileUploaded(entity, {
    id: 'rid-1',
    name: 'a.png',
    mime_type: 'image/png',
    size: 12,
    url: 'https://cdn.example.com/a.png',
  })
  assert.equal(isHumanInputFileUploaded(uploaded), true)
  const processed = getProcessedHumanInputFormInputs(
    [{ type: 'file', output_variable_name: 'doc' }],
    { doc: uploaded },
  )
  assert.deepEqual(processed.doc, {
    type: 'image',
    transfer_method: 'remote_url',
    url: 'https://cdn.example.com/a.png',
    upload_file_id: 'rid-1',
  })
})

test('removeHumanInputFormByNodeId drops matching form', () => {
  const next = removeHumanInputFormByNodeId([
    { node_id: 'a' },
    { node_id: 'b' },
  ], 'a')
  assert.deepEqual(next.map(f => f.node_id), ['b'])
})
