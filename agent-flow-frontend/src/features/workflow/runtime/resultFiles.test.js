import test from 'node:test'
import assert from 'node:assert/strict'
import {
  countResultFiles,
  getFilesInLogs,
  isImageResultFile,
  normalizeResultFile,
  resolveResultFileGroups,
} from './resultFiles.js'

const sampleFile = {
  dify_model_identity: '__dify__file__',
  filename: 'photo.png',
  mime_type: 'image/png',
  url: 'https://example.com/photo.png',
  related_id: 'f1',
  size: 12,
  type: 'image',
  transfer_method: 'local_file',
}

test('getFilesInLogs extracts single file and file list outputs', () => {
  const groups = getFilesInLogs({
    answer: 'hi',
    doc: sampleFile,
    docs: [sampleFile, { ...sampleFile, filename: 'a.pdf', mime_type: 'application/pdf', type: 'document' }],
  })
  assert.equal(groups.length, 2)
  assert.equal(groups[0].varName, 'doc')
  assert.equal(groups[0].list[0].name, 'photo.png')
  assert.equal(groups[0].list[0].url, 'https://example.com/photo.png')
  assert.equal(groups[1].varName, 'docs')
  assert.equal(groups[1].list.length, 2)
  assert.equal(countResultFiles(groups), 3)
})

test('normalizeResultFile and isImageResultFile', () => {
  const file = normalizeResultFile(sampleFile)
  assert.equal(file.id, 'f1')
  assert.equal(isImageResultFile(file), true)
  assert.equal(isImageResultFile({ name: 'a.pdf', type: 'application/pdf' }), false)
})

test('resolveResultFileGroups prefers grouped result.files', () => {
  const groups = resolveResultFileGroups({
    files: [{ varName: 'out', list: [sampleFile] }],
    outputs: {},
  })
  assert.equal(groups.length, 1)
  assert.equal(groups[0].varName, 'out')
})

test('resolveResultFileGroups falls back to outputs', () => {
  const groups = resolveResultFileGroups({
    outputs: { file: sampleFile },
  })
  assert.equal(groups[0].varName, 'file')
})
