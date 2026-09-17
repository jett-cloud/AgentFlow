/**
 * Pure autosave timing policy. Vue owns timers; this module decides whether
 * a polled signature should restart the delay or follow up after a save.
 */

export function shouldRestartAutosaveTimer({
  lastSavedSignature,
  lastObservedSignature,
  nextSignature,
} = {}) {
  if (!lastSavedSignature)
    return false
  if (nextSignature === lastSavedSignature)
    return false
  return nextSignature !== lastObservedSignature
}

export function nextDraftStatusOnSignature({
  lastSavedSignature,
  lastObservedSignature,
  nextSignature,
  draftStatus,
} = {}) {
  if (!lastSavedSignature)
    return draftStatus || 'saved'
  if (nextSignature === lastSavedSignature)
    return draftStatus === 'dirty' ? 'saved' : draftStatus
  if (draftStatus === 'saving')
    return 'saving'
  if (draftStatus === 'error' && nextSignature === lastObservedSignature)
    return 'error'
  return 'dirty'
}

export function needsFollowUpSave({ inFlightSignature, latestSignature } = {}) {
  return Boolean(inFlightSignature) && inFlightSignature !== latestSignature
}
