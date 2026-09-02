import test from 'node:test'
import assert from 'node:assert/strict'
import { buildAssistGraphSnapshot } from './graphSnapshot.js'

test('snapshot reflects added node id', () => {
  const base = buildAssistGraphSnapshot({
    nodes: [{ id: 'start', type: 'start', position: { x: 0, y: 0 }, data: {} }],
    edges: [],
    viewport: { x: 0, y: 0, zoom: 1 },
  })
  const withLlm = buildAssistGraphSnapshot({
    nodes: [
      { id: 'start', type: 'start', position: { x: 0, y: 0 }, data: {} },
      { id: 'llm-1', type: 'llm', position: { x: 100, y: 50 }, data: { title: 'LLM' } },
    ],
    edges: [],
    viewport: { x: 0, y: 0, zoom: 1 },
  })

  assert.equal(base.nodes.length, 1)
  assert.equal(withLlm.nodes.length, 2)
  assert.ok(withLlm.nodes.some(node => node.id === 'llm-1'))
})

test('snapshot quantizes viewport', () => {
  const snap = buildAssistGraphSnapshot({
    nodes: [],
    edges: [],
    viewport: { x: 1.234567, y: -2.345678, zoom: 1.2345678 },
  })
  assert.deepEqual(snap.viewport, { x: 1.23, y: -2.35, zoom: 1.235 })
})
