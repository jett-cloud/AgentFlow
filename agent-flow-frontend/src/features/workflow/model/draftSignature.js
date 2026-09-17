/**
 * Stable draft dirty-check signature.
 * Must ignore Vue Flow layout/runtime noise, otherwise measure/select updates
 * mutate draftStatus in the same flush and crash with
 * "Maximum recursive updates exceeded".
 */

function stripRuntimeFields(data) {
  if (!data || typeof data !== 'object')
    return {}
  const out = {}
  for (const [key, value] of Object.entries(data)) {
    if (key.startsWith('_'))
      continue
    out[key] = value
  }
  return out
}

export function normalizeNodesForSignature(nodes = []) {
  return (nodes || []).map((node) => ({
    id: node.id,
    type: node.type,
    parentId: node.parentId || node.parentNode || undefined,
    position: node.position
      ? {
          x: Math.round(Number(node.position.x) || 0),
          y: Math.round(Number(node.position.y) || 0),
        }
      : { x: 0, y: 0 },
    data: stripRuntimeFields(node.data),
  }))
}

export function normalizeEdgesForSignature(edges = []) {
  return (edges || []).map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle || null,
    targetHandle: edge.targetHandle || null,
    data: stripRuntimeFields(edge.data),
  }))
}

export function quantizeViewport(vp = {}) {
  return {
    x: Math.round((Number(vp.x) || 0) * 100) / 100,
    y: Math.round((Number(vp.y) || 0) * 100) / 100,
    zoom: Math.round((Number(vp.zoom) || 1) * 1000) / 1000,
  }
}

export function buildDraftCanonicalContent({
  nodes = [],
  edges = [],
  environmentVariables = [],
  conversationVariables = [],
  workflowName = '',
} = {}) {
  return JSON.stringify({
    nodes: normalizeNodesForSignature(nodes),
    edges: normalizeEdgesForSignature(edges),
    environmentVariables,
    conversationVariables,
    workflowName,
  })
}

function hashCanonicalContent(content) {
  let h1 = 0x9e3779b9
  let h2 = 0x243f6a88
  let h3 = 0xb7e15162
  let h4 = 0xdeadbeef
  for (let index = 0; index < content.length; index += 1) {
    const code = content.charCodeAt(index)
    h1 = Math.imul(h1 ^ code, 0x85ebca6b)
    h2 = Math.imul(h2 ^ code, 0xc2b2ae35)
    h3 = Math.imul(h3 ^ code, 0x27d4eb2f)
    h4 = Math.imul(h4 ^ code, 0x165667b1)
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 0x85ebca6b) ^ h2
  h2 = Math.imul(h2 ^ (h2 >>> 13), 0xc2b2ae35) ^ h3
  h3 = Math.imul(h3 ^ (h3 >>> 16), 0x85ebca6b) ^ h4
  h4 = Math.imul(h4 ^ (h4 >>> 13), 0xc2b2ae35) ^ h1
  return [h1, h2, h3, h4].map(value => (value >>> 0).toString(16).padStart(8, '0')).join('')
}

export function buildDraftContentSignature(draft = {}) {
  return hashCanonicalContent(buildDraftCanonicalContent(draft))
}
