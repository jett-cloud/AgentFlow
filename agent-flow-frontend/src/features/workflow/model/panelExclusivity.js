/**
 * Panel exclusivity helpers (Dify hideAllPanel pattern).
 * Opening env/vars/debug/features/history should not stack all overlays.
 */

export const PANEL_KEYS = {
  debug: 'debug',
  variables: 'variables',
  inspect: 'inspect',
  features: 'features',
  checklist: 'checklist',
  versionHistory: 'versionHistory',
  runHistory: 'runHistory',
}

/**
 * @param {string} opening
 * @returns {Record<string, boolean>} flags that should be forced closed
 */
export function panelsToCloseWhenOpening(opening) {
  const all = {
    [PANEL_KEYS.debug]: false,
    [PANEL_KEYS.variables]: false,
    [PANEL_KEYS.inspect]: false,
    [PANEL_KEYS.features]: false,
    [PANEL_KEYS.checklist]: false,
    [PANEL_KEYS.versionHistory]: false,
    [PANEL_KEYS.runHistory]: false,
  }
  // Keep the panel being opened; close the rest of the overlay group.
  if (opening && Object.prototype.hasOwnProperty.call(all, opening))
    delete all[opening]
  return all
}

/**
 * Apply exclusivity onto a mutable flags object { debug, variables, ... }.
 * @param {Record<string, { value: boolean }|boolean>} flags
 * @param {string} opening
 * @param {{ open?: boolean }} [options] open=false means closing current → no-op on others
 */
export function applyPanelExclusivity(flags, opening, { open = true } = {}) {
  if (!open)
    return
  // panelsToCloseWhenOpening returns siblings keyed with forced-closed `false`;
  // every remaining key must be closed.
  const toClose = panelsToCloseWhenOpening(opening)
  for (const key of Object.keys(toClose)) {
    const target = flags[key]
    if (target && typeof target === 'object' && 'value' in target)
      target.value = false
    else if (key in flags)
      flags[key] = false
  }
}
