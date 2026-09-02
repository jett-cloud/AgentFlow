import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('knowledge retrieval config exposes rerank / single / metadata fields', () => {
  const source = readFileSync(new URL('./useKnowledgeRetrievalConfig.js', import.meta.url), 'utf8')
  assert.match(source, /reranking_enable/)
  assert.match(source, /score_threshold:\s*null/)
  assert.match(source, /single_retrieval_config/)
  assert.match(source, /metadata_filtering_mode/)
  assert.match(source, /metadata_filtering_conditions/)
  assert.match(source, /METADATA_FILTER_MODES/)
})

test('knowledge retrieval panel wires rerank and metadata UI', () => {
  const panel = readFileSync(
    new URL('./KnowledgeRetrievalPanel.vue', import.meta.url),
    'utf8',
  )
  assert.match(panel, /rerankingEnable/)
  assert.match(panel, /scoreThresholdEnabled/)
  assert.match(panel, /singleModel/)
  assert.match(panel, /metadataFilteringMode/)
  assert.match(panel, /addMetadataCondition/)
  assert.match(panel, /fetchModelsByType\('rerank'\)/)
  assert.match(panel, /metadata_id/)
  assert.match(panel, /operatorsForMetadataType/)
})
