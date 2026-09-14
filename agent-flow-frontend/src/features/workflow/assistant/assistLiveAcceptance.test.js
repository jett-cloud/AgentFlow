import assert from 'node:assert/strict'
import test from 'node:test'
import { liveAcceptanceApproval } from './assistLiveAcceptance.js'

test('only an explicit answer for the current server request grants a live trial', () => {
  const questions = [{ id: 'live_run_consent', kind: 'live_acceptance', execution_request: { request_id: 'a'.repeat(32) } }]
  assert.equal(liveAcceptanceApproval([{ question_id: 'live_run_consent', approved: true }], questions), 'a'.repeat(32))
  assert.equal(liveAcceptanceApproval([{ question_id: 'live_run_consent', text: 'yes' }], questions), undefined)
  assert.equal(liveAcceptanceApproval([{ question_id: 'live_run_consent', approved: false }], questions), undefined)
  assert.equal(liveAcceptanceApproval([{ question_id: 'other', approved: true }], questions), undefined)
  assert.equal(liveAcceptanceApproval([{ question_id: 'live_run_consent', approved: true }], []), undefined)
})
