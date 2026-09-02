import test from 'node:test'
import assert from 'node:assert/strict'
import { resolveDraftSaveAppId, shouldFlushDraftOnLeave } from './draftFlush.js'

test('flush when dirty and not readOnly', () => {
  assert.equal(shouldFlushDraftOnLeave({ draftStatus: 'dirty', readOnly: false }), true)
})

test('no flush when saved', () => {
  assert.equal(shouldFlushDraftOnLeave({ draftStatus: 'saved', readOnly: false }), false)
})

test('no flush when readOnly', () => {
  assert.equal(shouldFlushDraftOnLeave({ draftStatus: 'dirty', readOnly: true }), false)
})

test('resolveDraftSaveAppId prefers payload when route cleared on leave', () => {
  assert.equal(
    resolveDraftSaveAppId({ payloadAppId: 'app-123', routeAppId: '' }),
    'app-123',
  )
})

test('resolveDraftSaveAppId falls back to route', () => {
  assert.equal(
    resolveDraftSaveAppId({ payloadAppId: '', routeAppId: 'app-456' }),
    'app-456',
  )
})

test('resolveDraftSaveAppId empty when both missing (avoid apps//)', () => {
  assert.equal(resolveDraftSaveAppId({ payloadAppId: '', routeAppId: '' }), '')
  assert.equal(resolveDraftSaveAppId({}), '')
})

