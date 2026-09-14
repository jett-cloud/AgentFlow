import test from 'node:test'
import assert from 'node:assert/strict'
import {
  needsFollowUpSave,
  nextDraftStatusOnSignature,
  shouldRestartAutosaveTimer,
} from './draftAutosave.js'
import { shouldFlushDraftOnLeave } from './draftFlush.js'

test('polling the same dirty signature does not restart the autosave timer', () => {
  assert.equal(shouldRestartAutosaveTimer({
    lastSavedSignature: 'saved',
    lastObservedSignature: 'dirty-a',
    nextSignature: 'dirty-a',
  }), false)
})

test('a real graph change restarts the autosave timer', () => {
  assert.equal(shouldRestartAutosaveTimer({
    lastSavedSignature: 'saved',
    lastObservedSignature: 'dirty-a',
    nextSignature: 'dirty-b',
  }), true)
})

test('matching the saved signature does not restart the timer', () => {
  assert.equal(shouldRestartAutosaveTimer({
    lastSavedSignature: 'saved',
    lastObservedSignature: 'saved',
    nextSignature: 'saved',
  }), false)
})

test('status becomes dirty only when the signature actually diverges', () => {
  assert.equal(nextDraftStatusOnSignature({
    lastSavedSignature: 'saved',
    nextSignature: 'saved',
    draftStatus: 'dirty',
  }), 'saved')
  assert.equal(nextDraftStatusOnSignature({
    lastSavedSignature: 'saved',
    nextSignature: 'dirty-a',
    draftStatus: 'saved',
  }), 'dirty')
  assert.equal(nextDraftStatusOnSignature({
    lastSavedSignature: 'saved',
    nextSignature: 'dirty-b',
    draftStatus: 'saving',
  }), 'saving')
  assert.equal(nextDraftStatusOnSignature({
    lastSavedSignature: 'saved',
    lastObservedSignature: 'failed',
    nextSignature: 'failed',
    draftStatus: 'error',
  }), 'error')
  assert.equal(nextDraftStatusOnSignature({
    lastSavedSignature: 'saved',
    lastObservedSignature: 'failed',
    nextSignature: 'retry',
    draftStatus: 'error',
  }), 'dirty')
})

test('saving the in-flight graph does not drop later edits', () => {
  assert.equal(needsFollowUpSave({
    inFlightSignature: 'v1',
    latestSignature: 'v2',
  }), true)
  assert.equal(needsFollowUpSave({
    inFlightSignature: 'v2',
    latestSignature: 'v2',
  }), false)
})

test('failed saves still flush on leave and retry after the next edit', () => {
  assert.equal(shouldFlushDraftOnLeave({ draftStatus: 'error', readOnly: false }), true)
  assert.equal(shouldRestartAutosaveTimer({
    lastSavedSignature: 'saved',
    lastObservedSignature: 'failed',
    nextSignature: 'retry',
  }), true)
  assert.equal(nextDraftStatusOnSignature({
    lastSavedSignature: 'saved',
    lastObservedSignature: 'failed',
    nextSignature: 'retry',
    draftStatus: 'error',
  }), 'dirty')
})

test('leaving during an in-flight save flushes a newer signature', () => {
  assert.equal(shouldFlushDraftOnLeave({
    draftStatus: 'saving',
    readOnly: false,
    inFlightSignature: 's1',
    latestSignature: 's2',
  }), true)
})