export const CANVAS_CHROME_ACTIONS = Object.freeze({
  header: Object.freeze([
    'back',
    'run',
    'run-history',
    'checklist',
    'env',
    'global-variables',
  ]),
  rail: Object.freeze([
    'add-node',
    'note',
    'pointer',
    'hand',
    'organize',
    'more',
  ]),
  dock: Object.freeze([
    'undo',
    'redo',
    'variable-inspect',
    'zoom-out',
    'zoom-in',
    'fit-view',
    'minimap',
  ]),
})

export const CANVAS_MORE_ACTIONS = Object.freeze(['agent'])

const VARIABLE_ACTION_TABS = Object.freeze({
  env: 'env',
  'global-variables': 'sys',
})

export function variableTabForAction(action) {
  return VARIABLE_ACTION_TABS[action] || null
}

export function normalizeCanvasControlMode(mode) {
  return mode === 'hand' ? 'hand' : 'pointer'
}

export function formatCanvasSaveStatus({
  draftStatus = 'saved',
  draftUpdatedAt = 0,
  publishStatus = '',
} = {}) {
  let saveLabel = '已保存'

  if (draftStatus === 'saving')
    saveLabel = '保存中…'
  else if (draftStatus === 'dirty')
    saveLabel = '有未保存更改'
  else if (draftStatus === 'error')
    saveLabel = '保存失败'
  else if (draftUpdatedAt > 0) {
    const updated = new Date(draftUpdatedAt)
    const hours = String(updated.getHours()).padStart(2, '0')
    const minutes = String(updated.getMinutes()).padStart(2, '0')
    const seconds = String(updated.getSeconds()).padStart(2, '0')
    saveLabel = `自动保存 ${hours}:${minutes}:${seconds}`
  }

  return publishStatus ? `${saveLabel} · ${publishStatus}` : saveLabel
}
