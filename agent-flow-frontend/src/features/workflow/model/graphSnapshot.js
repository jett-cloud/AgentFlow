import {
  normalizeEdgesForSignature,
  normalizeNodesForSignature,
  quantizeViewport,
} from './draftSignature.js'

export function buildAssistGraphSnapshot({ nodes, edges, viewport }) {
  return {
    nodes: normalizeNodesForSignature(nodes || []),
    edges: normalizeEdgesForSignature(edges || []),
    viewport: quantizeViewport(viewport || {}),
  }
}
