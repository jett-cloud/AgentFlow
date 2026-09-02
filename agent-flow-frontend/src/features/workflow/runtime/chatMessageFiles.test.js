import test from 'node:test'
import assert from 'node:assert/strict'
import {
  extractMessageEndFiles,
  mergeChatMessageFiles,
  normalizeChatMessageFilesFromPending,
  normalizeMessageFileEvent,
} from './chatMessageFiles.js'

test('normalizeChatMessageFilesFromPending maps uploaded entities', () => {
  const files = normalizeChatMessageFilesFromPending([
    {
      id: 'local-1',
      name: 'a.png',
      size: 12,
      type: 'image/png',
      supportFileType: 'image',
      transferMethod: 'local_file',
      progress: 100,
      uploadedId: 'up-1',
      url: 'https://cdn.example/a.png',
    },
    { id: 'bad', progress: -1, name: 'x' },
  ])
  assert.equal(files.length, 1)
  assert.equal(files[0].id, 'up-1')
  assert.equal(files[0].name, 'a.png')
  assert.equal(files[0].url, 'https://cdn.example/a.png')
  assert.equal(files[0].supportFileType, 'image')
})

test('normalizeMessageFileEvent and mergeChatMessageFiles', () => {
  const file = normalizeMessageFileEvent({
    event: 'message_file',
    id: 'f1',
    type: 'image',
    url: 'https://cdn.example/b.jpg',
  })
  assert.equal(file.id, 'f1')
  assert.equal(file.url, 'https://cdn.example/b.jpg')

  const merged = mergeChatMessageFiles([file], [{
    id: 'f1',
    filename: 'b.jpg',
    url: 'https://cdn.example/b2.jpg',
  }])
  assert.equal(merged.length, 1)
  assert.equal(merged[0].url, 'https://cdn.example/b2.jpg')
  assert.equal(merged[0].name, 'b.jpg')
})

test('extractMessageEndFiles reads event.files', () => {
  const files = extractMessageEndFiles({
    event: 'message_end',
    files: [{
      related_id: 'r1',
      filename: 'out.pdf',
      mime_type: 'application/pdf',
      url: 'https://cdn.example/out.pdf',
    }],
  })
  assert.equal(files.length, 1)
  assert.equal(files[0].id, 'r1')
  assert.equal(files[0].name, 'out.pdf')
})
