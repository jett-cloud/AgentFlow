import test from 'node:test'
import assert from 'node:assert/strict'
import { applyPanelExclusivity, panelsToCloseWhenOpening, PANEL_KEYS } from './panelExclusivity.js'

test('opening debug closes variables/features overlays', () => {
  const closed = panelsToCloseWhenOpening(PANEL_KEYS.debug)
  assert.equal(closed[PANEL_KEYS.variables], false)
  assert.equal(closed[PANEL_KEYS.features], false)
  assert.equal(closed[PANEL_KEYS.debug], undefined)
})

test('applyPanelExclusivity mutates refs', () => {
  const flags = {
    debug: { value: true },
    variables: { value: true },
    inspect: { value: true },
    features: { value: false },
    checklist: { value: false },
    versionHistory: { value: false },
    runHistory: { value: false },
  }
  applyPanelExclusivity(flags, PANEL_KEYS.variables, { open: true })
  assert.equal(flags.variables.value, true)
  assert.equal(flags.debug.value, false)
  assert.equal(flags.inspect.value, false)
})

test('closing a panel does not force-close siblings', () => {
  const flags = {
    debug: { value: true },
    variables: { value: true },
    inspect: { value: false },
    features: { value: false },
    checklist: { value: false },
    versionHistory: { value: false },
    runHistory: { value: false },
  }
  applyPanelExclusivity(flags, PANEL_KEYS.variables, { open: false })
  assert.equal(flags.debug.value, true)
  assert.equal(flags.variables.value, true)
})
