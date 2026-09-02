import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildRecordingBlob,
  mergeTranscriptIntoQuery,
  pickRecorderMimeType,
} from './sttRecorder.js'

test('pickRecorderMimeType returns first supported type', () => {
  const Fake = {
    isTypeSupported: (type) => type === 'audio/webm',
  }
  assert.equal(pickRecorderMimeType(Fake), 'audio/webm')
})

test('pickRecorderMimeType returns empty when unsupported', () => {
  assert.equal(pickRecorderMimeType({ isTypeSupported: () => false }), '')
  assert.equal(pickRecorderMimeType(undefined), '')
})

test('buildRecordingBlob joins chunks', () => {
  const blob = buildRecordingBlob([new Blob(['a']), new Blob(['b'])], 'audio/webm')
  assert.ok(blob)
  assert.equal(blob.type, 'audio/webm')
  assert.equal(buildRecordingBlob([]), null)
})

test('mergeTranscriptIntoQuery appends with space', () => {
  assert.equal(mergeTranscriptIntoQuery('', '你好'), '你好')
  assert.equal(mergeTranscriptIntoQuery('hi', 'there'), 'hi there')
  assert.equal(mergeTranscriptIntoQuery('hi', '  '), 'hi')
})
