import test from 'node:test'
import assert from 'node:assert/strict'
import {
  CANVAS_CHROME_ACTIONS,
  CANVAS_MORE_ACTIONS,
  formatCanvasSaveStatus,
  normalizeCanvasControlMode,
  variableTabForAction,
} from './canvasChrome.js'

test('canvas chrome exposes only the phase-one Dify actions', () => {
  assert.deepEqual(CANVAS_CHROME_ACTIONS.header, [
    'back',
    'run',
    'run-history',
    'checklist',
    'env',
    'global-variables',
  ])
  assert.deepEqual(CANVAS_CHROME_ACTIONS.rail, [
    'add-node',
    'note',
    'pointer',
    'hand',
    'organize',
    'more',
  ])
  assert.deepEqual(CANVAS_MORE_ACTIONS, ['agent'])

  const allActions = Object.values(CANVAS_CHROME_ACTIONS).flat().concat(CANVAS_MORE_ACTIONS)
  for (const hiddenAction of ['publish', 'comment', 'features', 'integrations', 'dsl', 'save', 'version-history'])
    assert.equal(allActions.includes(hiddenAction), false)
})

test('save status includes autosave time and publication state', () => {
  const updatedAt = new Date(2026, 7, 12, 2, 18, 34).getTime()
  assert.equal(
    formatCanvasSaveStatus({ draftStatus: 'saved', draftUpdatedAt: updatedAt, publishStatus: '未发布' }),
    '自动保存 02:18:34 · 未发布',
  )
  assert.equal(
    formatCanvasSaveStatus({ draftStatus: 'saving', publishStatus: '未发布' }),
    '保存中… · 未发布',
  )
  assert.equal(
    formatCanvasSaveStatus({ draftStatus: 'dirty', publishStatus: '未发布' }),
    '有未保存更改 · 未发布',
  )
  assert.equal(
    formatCanvasSaveStatus({ draftStatus: 'error', publishStatus: '已发布' }),
    '保存失败 · 已发布',
  )
})

test('header variable actions map to controlled panel tabs', () => {
  assert.equal(variableTabForAction('env'), 'env')
  assert.equal(variableTabForAction('global-variables'), 'sys')
  assert.equal(variableTabForAction('unknown'), null)
})

test('only pointer and hand are visible control modes', () => {
  assert.equal(normalizeCanvasControlMode('pointer'), 'pointer')
  assert.equal(normalizeCanvasControlMode('hand'), 'hand')
  assert.equal(normalizeCanvasControlMode('comment'), 'pointer')
})
