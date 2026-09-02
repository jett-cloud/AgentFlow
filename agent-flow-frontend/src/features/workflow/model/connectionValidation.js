// Vue Flow calls isValidConnection for interactive connects AND during setEdges.
// Rejecting "already existing" endpoints during setEdges wipes edges on re-init.

import { DEFAULT_SOURCE_HANDLE, DEFAULT_TARGET_HANDLE } from './constants.js'

function sameEndpoints(a, b) {
  return (
    a.source === b.source
    && a.target === b.target
    && (a.sourceHandle || DEFAULT_SOURCE_HANDLE) === (b.sourceHandle || DEFAULT_SOURCE_HANDLE)
    && (a.targetHandle || DEFAULT_TARGET_HANDLE) === (b.targetHandle || DEFAULT_TARGET_HANDLE)
  )
}

/**
 * @returns {boolean} true when this connection should be rejected as a duplicate
 */
export function shouldRejectDuplicateConnection(connection, existingEdges = []) {
  const match = existingEdges.find(edge => sameEndpoints(edge, connection))
  if (!match) return false
  // Same id → setEdges re-applying current graph; must stay valid.
  if (connection.id && match.id === connection.id) return false
  return true
}
