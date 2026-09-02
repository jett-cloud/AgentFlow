import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getEntryLabel,
  getNodePresentation,
  normalizePresentationType,
} from './nodePresentation.js'

test('normalizes compatibility aliases before resolving presentation rules', () => {
  assert.equal(normalizePresentationType('agent-v2'), 'agent')
  assert.equal(normalizePresentationType('assigner'), 'variable-assigner')
  assert.equal(normalizePresentationType('custom-iteration-start'), 'iteration-start')
  assert.equal(normalizePresentationType('custom-loop-start'), 'loop-start')
})

test('entry and terminal nodes expose Dify handle rules', () => {
  assert.deepEqual(getNodePresentation('start'), {
    kind: 'entry',
    showEntryShell: true,
    showTargetHandle: false,
    showSourceHandle: true,
    sourceHandleMode: 'header',
  })
  assert.equal(getEntryLabel('start'), 'START')
  assert.equal(getEntryLabel('datasource'), 'DATA SOURCE')
  assert.equal(getEntryLabel('trigger-webhook'), 'TRIGGER')

  const end = getNodePresentation('end')
  assert.equal(end.kind, 'terminal')
  assert.equal(end.showTargetHandle, true)
  assert.equal(end.showSourceHandle, false)
})

test('branch and container nodes use dedicated source handle behavior', () => {
  const branch = getNodePresentation('if-else')
  assert.equal(branch.kind, 'branch')
  assert.equal(branch.showTargetHandle, true)
  assert.equal(branch.showSourceHandle, false)
  assert.equal(branch.sourceHandleMode, 'rows')

  const container = getNodePresentation('iteration')
  assert.equal(container.kind, 'container')
  assert.equal(container.showTargetHandle, true)
  assert.equal(container.showSourceHandle, true)
  assert.equal(container.sourceHandleMode, 'header')
})

test('start placeholder and fallback nodes remain connection-safe', () => {
  assert.deepEqual(getNodePresentation('start-placeholder'), {
    kind: 'entry',
    showEntryShell: true,
    showTargetHandle: false,
    showSourceHandle: false,
    sourceHandleMode: 'none',
  })

  const fallback = getNodePresentation('custom')
  assert.equal(fallback.kind, 'standard')
  assert.equal(fallback.showTargetHandle, true)
  assert.equal(fallback.showSourceHandle, true)
})
