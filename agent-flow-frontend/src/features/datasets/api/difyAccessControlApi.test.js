import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('access control API exposes rbac dataset endpoints', () => {
  const source = readFileSync(new URL('./difyAccessControlApi.js', import.meta.url), 'utf8')
  assert.match(source, /rbac\/datasets/)
  assert.match(source, /user-access-policies/)
  assert.match(source, /whitelist/)
  assert.match(source, /member-bindings/)
})

test('datasets API exposes external hit-testing', () => {
  const source = readFileSync(new URL('./difyDatasetsApi.js', import.meta.url), 'utf8')
  assert.match(source, /external-hit-testing/)
  assert.match(source, /export function externalHitTesting/)
})

test('datasets API exposes document governance endpoints', () => {
  const source = readFileSync(new URL('./difyDatasetsApi.js', import.meta.url), 'utf8')
  assert.match(source, /documents\/status\/\$\{encodeURIComponent\(action\)\}\/batch/)
  assert.match(source, /export function patchDocumentsStatus/)
  assert.match(source, /\/rename/)
  assert.match(source, /export function renameDocument/)
  assert.match(source, /processing\/pause/)
  assert.match(source, /processing\/resume/)
})

test('datasets API exposes segment child chunks and csv import', () => {
  const source = readFileSync(new URL('./difyDatasetsApi.js', import.meta.url), 'utf8')
  assert.match(source, /child_chunks/)
  assert.match(source, /export function fetchChildChunks/)
  assert.match(source, /export function addChildChunk/)
  assert.match(source, /export function updateChildChunk/)
  assert.match(source, /export function deleteChildChunk/)
  assert.match(source, /export function importSegmentsCsv/)
  assert.match(source, /segments\/batch_import/)
  assert.match(source, /batch_import_status/)
})

test('datasets API exposes metadata schema and document batch update', () => {
  const source = readFileSync(new URL('./difyDatasetsApi.js', import.meta.url), 'utf8')
  assert.match(source, /export function fetchDatasetMetadata/)
  assert.match(source, /export function createDatasetMetadata/)
  assert.match(source, /export function renameDatasetMetadata/)
  assert.match(source, /export function deleteDatasetMetadata/)
  assert.match(source, /metadata\/built-in/)
  assert.match(source, /export function updateDocumentsMetadata/)
  assert.match(source, /documents\/metadata/)
})

test('pipeline API exposes template and create endpoints', () => {
  const source = readFileSync(new URL('./difyPipelineApi.js', import.meta.url), 'utf8')
  assert.match(source, /rag\/pipeline\/templates/)
  assert.match(source, /rag\/pipeline\/dataset/)
  assert.match(source, /empty-dataset/)
  assert.match(source, /rag\/pipelines\/imports/)
  assert.match(source, /workflows\/draft/)
  assert.match(source, /workflows\/publish/)
  assert.match(source, /workflows\/draft\/run/)
  assert.match(source, /workflow-runs\/tasks/)
  assert.match(source, /listPipelineRuns/)
  assert.match(source, /getPipelineRunNodeExecutions/)
  assert.match(source, /listPublishedPipelines/)
  assert.match(source, /restorePipelineVersion/)
  assert.match(source, /transform\/datasets/)
  assert.match(source, /isDraftWorkflowNotExistError/)
})

test('empty pipeline seed builds knowledge-index node', async () => {
  const { buildEmptyPipelineGraph } = await import('../model/pipelineTemplates.js')
  const graph = buildEmptyPipelineGraph()
  assert.equal(graph.nodes.length, 1)
  assert.equal(graph.edges.length, 0)
  assert.equal(graph.nodes[0].type, 'knowledge-index')
  assert.equal(graph.nodes[0].id, 'knowledgeBase')
})
