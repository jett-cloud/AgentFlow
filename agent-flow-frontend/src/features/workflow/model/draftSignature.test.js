import test from 'node:test'
import assert from 'node:assert/strict'
import { buildDraftCanonicalContent, buildDraftContentSignature } from './draftSignature.js'

const base = { nodes: [], edges: [], environmentVariables: [], conversationVariables: [] }

test('signature includes workflowName', () => {
  const a = buildDraftContentSignature({ ...base, workflowName: 'A' })
  const b = buildDraftContentSignature({ ...base, workflowName: 'B' })
  assert.notEqual(a, b)
})

test('signature is a fixed 128-bit revision for a 40 node graph', () => {
  const nodes = Array.from({ length: 40 }, (_, index) => ({
    id: `node-${index}`,
    type: 'custom',
    position: { x: index * 100, y: 0 },
    data: { type: 'llm', title: `Node ${index}`, prompt: 'x'.repeat(100) },
  }))

  const canonical = buildDraftCanonicalContent({ ...base, nodes })
  const revision = buildDraftContentSignature({ ...base, nodes })

  assert.ok(canonical.length > 255)
  assert.match(revision, /^[a-f0-9]{32}$/)
})

test('signature is deterministic and changes with persisted draft content', () => {
  const input = { ...base, nodes: [{ id: 'a', data: { title: 'A' } }] }
  assert.equal(buildDraftContentSignature(input), buildDraftContentSignature(input))
  assert.notEqual(
    buildDraftContentSignature(input),
    buildDraftContentSignature({ ...input, nodes: [{ id: 'a', data: { title: 'B' } }] }),
  )
  assert.notEqual(
    buildDraftContentSignature(input),
    buildDraftContentSignature({ ...input, edges: [{ id: 'e', source: 'a', target: 'b' }] }),
  )
  assert.notEqual(
    buildDraftContentSignature(input),
    buildDraftContentSignature({ ...input, environmentVariables: [{ id: 'env-1', value: 'changed' }] }),
  )
  assert.notEqual(
    buildDraftContentSignature(input),
    buildDraftContentSignature({ ...input, conversationVariables: [{ id: 'var-1', value: 'changed' }] }),
  )
})
