import { needsFollowUpSave } from './draftAutosave.js'

/**
 * @param {{
 *   draftStatus: string,
 *   readOnly: boolean,
 *   inFlightSignature?: string,
 *   latestSignature?: string,
 * }} state
 * @returns {boolean} whether a leave/unload flush save should run
 */
export function shouldFlushDraftOnLeave({
  draftStatus,
  readOnly,
  inFlightSignature,
  latestSignature,
} = {}) {
  if (readOnly) return false
  if (draftStatus === 'dirty' || draftStatus === 'error') return true
  if (draftStatus === 'saving')
    return needsFollowUpSave({ inFlightSignature, latestSignature })
  return false
}

/**
 * Prefer appId captured on the draft payload (canvas props at flush time).
 * Route query may already be cleared on leave/unmount before async save runs.
 * @param {{ payloadAppId?: string, routeAppId?: string }} ids
 * @returns {string}
 */
export function resolveDraftSaveAppId({ payloadAppId, routeAppId } = {}) {
  const fromPayload = String(payloadAppId || '').trim()
  if (fromPayload) return fromPayload
  return String(routeAppId || '').trim()
}
